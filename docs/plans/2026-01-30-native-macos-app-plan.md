# Native macOS App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a SwiftUI macOS menu bar app that controls the existing claude-voice Python daemon, with settings UI, daemon lifecycle management, and DMG distribution.

**Architecture:** SwiftUI menu bar app communicates with the Python daemon over a new Unix control socket (`~/.claude-voice/.control.sock`). The daemon remains fully self-contained — the app is an optional companion. Config is read/written as YAML at `~/.claude-voice/config.yaml`.

**Tech Stack:** Swift 5.9+, SwiftUI, macOS 14+ (Sonoma), Yams (YAML parsing), Sparkle (auto-update), `xcodebuild`, `hdiutil`

**Design doc:** `docs/plans/2026-01-30-native-macos-app-design.md`

## Two-Repo Structure

This is an **open core** setup:

| Repo | Visibility | Contents |
|------|-----------|----------|
| `claude-voice` (existing) | Public, MIT | Python daemon, CLI, hooks, install.sh |
| `claude-voice-app` (new) | Private, proprietary | SwiftUI menu bar app |

The repos share NO code. They communicate via:
- Control socket protocol (`~/.claude-voice/.control.sock`)
- Config file format (`~/.claude-voice/config.yaml`)

**Task 1** (control socket) is done in the **public repo**.
**Tasks 2-13** are done in the **private repo**.
**Task 14** (verification) spans both.

---

## Task 1: Control Socket Server (Public Repo: `claude-voice`)

Add a control socket server to the Python daemon that accepts JSON commands and emits events. This is the public API that the SwiftUI app connects to.

**Files:**
- Create: `daemon/control.py`
- Modify: `daemon/main.py`

**Step 1: Create `daemon/control.py`**

```python
"""Control socket server for external app communication."""

import json
import os
import socket
import threading

CONTROL_SOCK_PATH = os.path.expanduser("~/.claude-voice/.control.sock")


class ControlServer:
    """JSON command/event server over Unix socket."""

    def __init__(self, daemon):
        self.daemon = daemon
        self._shutting_down = False
        self._event_connections = []
        self._lock = threading.Lock()

    def _handle_command(self, data: dict) -> dict:
        cmd = data.get("cmd")

        if cmd == "status":
            return {
                "daemon": True,
                "mode": self.daemon.get_mode(),
                "voice": self.daemon.get_voice_enabled(),
                "recording": self.daemon.recorder.is_recording
                    if hasattr(self.daemon.recorder, 'is_recording') else False,
            }
        if cmd == "set_mode":
            mode = data.get("mode", "notify")
            self.daemon.set_mode(mode)
            self.emit({"event": "mode_changed", "mode": mode})
            return {"ok": True}
        if cmd == "voice_on":
            self.daemon.set_voice_enabled(True)
            return {"ok": True}
        if cmd == "voice_off":
            self.daemon.set_voice_enabled(False)
            return {"ok": True}
        if cmd == "reload_config":
            self.daemon.reload_config()
            return {"ok": True}
        if cmd == "stop":
            self.daemon._shutdown()
            return {"ok": True}
        if cmd == "subscribe":
            return {"subscribed": True}

        return {"error": f"unknown command: {cmd}"}

    def emit(self, event: dict):
        msg = json.dumps(event).encode() + b"\n"
        with self._lock:
            dead = []
            for conn in self._event_connections:
                try:
                    conn.sendall(msg)
                except (BrokenPipeError, OSError):
                    dead.append(conn)
            for conn in dead:
                self._event_connections.remove(conn)

    def run(self):
        if os.path.exists(CONTROL_SOCK_PATH):
            os.unlink(CONTROL_SOCK_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(CONTROL_SOCK_PATH)
        server.listen(5)
        server.settimeout(1.0)

        while not self._shutting_down:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

        server.close()
        if os.path.exists(CONTROL_SOCK_PATH):
            os.unlink(CONTROL_SOCK_PATH)

    def _handle_connection(self, conn):
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    request = json.loads(data.decode())
                    break
                except json.JSONDecodeError:
                    continue

            if not data:
                conn.close()
                return

            request = json.loads(data.decode())
            response = self._handle_command(request)

            if request.get("cmd") == "subscribe":
                conn.sendall(json.dumps(response).encode() + b"\n")
                with self._lock:
                    self._event_connections.append(conn)
                return

            conn.sendall(json.dumps(response).encode())
            conn.close()
        except Exception as e:
            print(f"Control server error: {e}")
            try:
                conn.close()
            except:
                pass

    def shutdown(self):
        self._shutting_down = True
        with self._lock:
            for conn in self._event_connections:
                try:
                    conn.close()
                except:
                    pass
            self._event_connections.clear()
```

**Step 2: Add helper methods to `VoiceDaemon` in `daemon/main.py`**

Add these methods to the `VoiceDaemon` class:

```python
def get_mode(self) -> str:
    return _read_mode()

def set_mode(self, mode: str) -> None:
    _write_mode(mode)

def get_voice_enabled(self) -> bool:
    return not os.path.exists(SILENT_FLAG)

def set_voice_enabled(self, enabled: bool) -> None:
    if enabled:
        if os.path.exists(SILENT_FLAG):
            os.remove(SILENT_FLAG)
    else:
        with open(SILENT_FLAG, 'w') as f:
            pass

def reload_config(self) -> None:
    self.config = load_config()
    print("Config reloaded")
```

**Step 3: Start control server in `_finish_startup()`**

After the TTS server thread starts, add:

```python
from daemon.control import ControlServer
self.control_server = ControlServer(self)
control_thread = threading.Thread(target=self.control_server.run, daemon=True)
control_thread.start()
print(f"Control server listening on ~/.claude-voice/.control.sock")
```

**Step 4: Clean up in `_shutdown()`**

Add before existing TTS server cleanup:

```python
if hasattr(self, 'control_server'):
    self.control_server.shutdown()
```

**Step 5: Verify both sockets start**

```bash
~/.claude-voice/claude-voice-daemon foreground
# In another terminal:
ls -la ~/.claude-voice/.tts.sock ~/.claude-voice/.control.sock
```

**Step 6: Test control protocol**

```bash
echo '{"cmd":"status"}' | socat - UNIX-CONNECT:$HOME/.claude-voice/.control.sock
```

Expected: `{"daemon": true, "mode": "notify", "voice": true, "recording": false}`

**Step 7: Verify existing install.sh still works**

```bash
./install.sh
```

**Step 8: Commit (in claude-voice repo)**

```bash
git add daemon/control.py daemon/main.py
git commit -m "feat: add control socket server for external app communication"
```

---

## Task 2: Private Repo + SwiftUI Skeleton (Private Repo: `claude-voice-app`)

Create the private repo and bare minimum SwiftUI app with menu bar icon.

**Step 1: Create repo**

```bash
mkdir -p ~/IdeaProjects/claude-voice-app
cd ~/IdeaProjects/claude-voice-app
git init
```

**Step 2: Create Package.swift**

Create `Package.swift`:
```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Claude Voice",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/jpsim/Yams.git", from: "5.0.0"),
    ],
    targets: [
        .executableTarget(
            name: "Claude Voice",
            dependencies: ["Yams"],
            path: "Claude Voice"
        ),
    ]
)
```

**Step 3: Create directory structure**

```bash
mkdir -p "Claude Voice"/{Models,Views,Services,Resources}
```

**Step 4: Create App.swift**

Create `Claude Voice/App.swift`:
```swift
import SwiftUI

@main
struct ClaudeVoiceApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        MenuBarExtra("Claude Voice", systemImage: "waveform") {
            MenuBarView(appState: appState)
        }
        Settings {
            SettingsView(appState: appState)
        }
    }
}
```

**Step 5: Create AppState.swift**

Create `Claude Voice/Models/AppState.swift`:
```swift
import SwiftUI

@MainActor
class AppState: ObservableObject {
    @Published var daemonRunning = false
    @Published var currentMode = "notify"
    @Published var voiceEnabled = true
}
```

**Step 6: Create MenuBarView.swift**

Create `Claude Voice/Views/MenuBarView.swift`:
```swift
import SwiftUI

struct MenuBarView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        Text("Claude Voice")
            .font(.headline)
        Divider()
        Button("Quit") {
            NSApplication.shared.terminate(nil)
        }
        .keyboardShortcut("q")
    }
}
```

**Step 7: Create SettingsView.swift (placeholder)**

Create `Claude Voice/Views/SettingsView.swift`:
```swift
import SwiftUI

struct SettingsView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        Text("Settings placeholder")
            .frame(width: 500, height: 400)
    }
}
```

**Step 8: Create .gitignore**

```
.build/
.swiftpm/
build/
*.xcodeproj/xcuserdata/
DerivedData/
```

**Step 9: Build and verify**

```bash
swift build
```

Expected: Compiles successfully.

**Step 10: Run and verify menu bar icon appears**

```bash
swift run "Claude Voice"
```

Expected: Waveform icon in menu bar, click shows label + Quit.

**Step 11: Commit**

```bash
git add -A
git commit -m "feat: SwiftUI menu bar app skeleton"
```

---

## Task 3: Config Manager (Private Repo)

Read and write `~/.claude-voice/config.yaml` from Swift using Yams.

**Files:**
- Create: `Claude Voice/Models/Config.swift`
- Create: `Claude Voice/Services/ConfigManager.swift`

**Step 1: Create Config.swift**

Swift struct mirroring `daemon/config.py` dataclasses. Must be `Codable`. Use `snake_case` `CodingKeys` to match the YAML field names.

Reference: the YAML structure from `config.yaml.example` in the public repo.

```swift
import Foundation

struct VoiceConfig: Codable {
    var input: InputConfig
    var transcription: TranscriptionConfig
    var speech: SpeechConfig
    var audio: AudioConfig
    var overlay: OverlayConfig
    var afk: AfkConfig?

    struct InputConfig: Codable {
        var hotkey: String = "right_alt"
        var languageHotkey: String? = nil
        var autoSubmit: Bool = false
        var minAudioLength: Double = 0.5
        var typingDelay: Double = 0.01
        var transcriptionCleanup: Bool = false
        var cleanupModel: String = "qwen2.5:1.5b"

        enum CodingKeys: String, CodingKey {
            case hotkey
            case languageHotkey = "language_hotkey"
            case autoSubmit = "auto_submit"
            case minAudioLength = "min_audio_length"
            case typingDelay = "typing_delay"
            case transcriptionCleanup = "transcription_cleanup"
            case cleanupModel = "cleanup_model"
        }
    }

    // ... (same pattern for all sub-structs with CodingKeys)
}
```

**Step 2: Create ConfigManager.swift**

```swift
import Foundation
import Yams

class ConfigManager {
    static let configPath = NSString("~/.claude-voice/config.yaml").expandingTildeInPath

    func load() throws -> VoiceConfig {
        let url = URL(fileURLWithPath: Self.configPath)
        let data = try Data(contentsOf: url)
        let decoder = YAMLDecoder()
        return try decoder.decode(VoiceConfig.self, from: data)
    }

    func save(_ config: VoiceConfig) throws {
        let encoder = YAMLEncoder()
        let yamlString = try encoder.encode(config)
        try yamlString.write(toFile: Self.configPath, atomically: true, encoding: .utf8)
    }
}
```

**Step 3: Build and verify**

```bash
swift build
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: Config model and ConfigManager for YAML read/write"
```

---

## Task 4: Daemon Manager (Private Repo)

Start, stop, and monitor the Python daemon.

**Files:**
- Create: `Claude Voice/Services/DaemonManager.swift`
- Modify: `Claude Voice/Models/AppState.swift`

**Step 1: Create DaemonManager.swift**

```swift
import Foundation

class DaemonManager {
    private let installDir = NSString("~/.claude-voice").expandingTildeInPath

    var pidFilePath: String { "\(installDir)/daemon.pid" }
    var daemonScript: String { "\(installDir)/claude-voice-daemon" }

    var isInstalled: Bool {
        FileManager.default.fileExists(atPath: "\(installDir)/daemon/main.py")
    }

    func isRunning() -> Bool {
        guard let pidString = try? String(contentsOfFile: pidFilePath, encoding: .utf8),
              let pid = Int32(pidString.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return false
        }
        return kill(pid, 0) == 0
    }

    func start() throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [daemonScript, "start"]
        try process.run()
        process.waitUntilExit()
    }

    func stop() throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [daemonScript, "stop"]
        try process.run()
        process.waitUntilExit()
    }
}
```

**Step 2: Wire into AppState**

Update `AppState.swift` — add `daemonManager`, `configManager`, polling, `toggleDaemon()`.

**Step 3: Build, verify**

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: DaemonManager for daemon lifecycle control"
```

---

## Task 5: Full Menu Bar Dropdown (Private Repo)

**Files:**
- Modify: `Claude Voice/Views/MenuBarView.swift`

Build full dropdown: daemon status indicator, start/stop button, mode picker, voice toggle, settings link, quit. Start polling on appear.

**Commit:**
```bash
git commit -m "feat: full menu bar dropdown with daemon controls"
```

---

## Task 6: Control Socket Client (Private Repo)

Connect the SwiftUI app to the daemon's control socket.

**Files:**
- Create: `Claude Voice/Services/ControlSocket.swift`
- Modify: `Claude Voice/Models/AppState.swift`

Swift class that:
- Connects to `~/.claude-voice/.control.sock` via Unix domain socket
- Sends JSON commands, receives JSON responses
- Supports persistent "subscribe" connection for events
- Reconnects on failure

Replace polling with socket events in AppState. Fall back to polling if socket unavailable.

**Commit:**
```bash
git commit -m "feat: ControlSocket client for daemon communication"
```

---

## Task 7: Settings — Input & Transcription Tabs (Private Repo)

**Files:**
- Create: `Claude Voice/Views/InputSettingsView.swift`
- Create: `Claude Voice/Views/TranscriptionSettingsView.swift`
- Modify: `Claude Voice/Views/SettingsView.swift`

InputSettingsView: hotkey picker, language hotkey, auto-submit, min audio length, typing delay, cleanup toggle + model.

TranscriptionSettingsView: model picker, language, extra languages, backend picker.

Wire into `SettingsView` as `TabView`. On change → save config → send `reload_config` via control socket.

**Commit:**
```bash
git commit -m "feat: Input and Transcription settings tabs"
```

---

## Task 8: Settings — Voice & Overlay Tabs (Private Repo)

**Files:**
- Create: `Claude Voice/Views/VoiceSettingsView.swift`
- Create: `Claude Voice/Views/OverlaySettingsView.swift`
- Modify: `Claude Voice/Views/SettingsView.swift`

VoiceSettingsView: enabled toggle, mode picker, voice picker (54 Kokoro voices), speed slider, lang code, max chars, skip toggles.

OverlaySettingsView: enabled toggle, style picker, color pickers.

**Commit:**
```bash
git commit -m "feat: Voice and Overlay settings tabs"
```

---

## Task 9: Settings — AFK & Advanced Tabs (Private Repo)

**Files:**
- Create: `Claude Voice/Views/AfkSettingsView.swift`
- Create: `Claude Voice/Views/AdvancedSettingsView.swift`
- Modify: `Claude Voice/Views/SettingsView.swift`

AfkSettingsView: telegram bot token (SecureField), chat ID, hotkey, voice commands.

AdvancedSettingsView: audio device picker, sample rate.

**Commit:**
```bash
git commit -m "feat: AFK and Advanced settings tabs"
```

---

## Task 10: Launch at Login (Private Repo)

**Files:**
- Modify: `Claude Voice/Views/AdvancedSettingsView.swift`
- Modify: `Claude Voice/Models/AppState.swift`

Add `SMAppService.mainApp` toggle in Advanced settings. Auto-start daemon on app launch if not running.

**Commit:**
```bash
git commit -m "feat: launch-at-login support"
```

---

## Task 11: First-Run Setup Wizard (Private Repo)

**Files:**
- Create: `Claude Voice/Views/SetupWizardView.swift`
- Create: `Claude Voice/Services/Installer.swift`
- Modify: `Claude Voice/App.swift`

Installer.swift: checks for Python 3.12+, FFmpeg. Clones the public `claude-voice` repo (or downloads a release tarball). Runs install.sh logic. Reports progress.

SetupWizardView: welcome → progress → permissions → done.

Show wizard conditionally if `~/.claude-voice/` doesn't exist.

**Commit:**
```bash
git commit -m "feat: first-run setup wizard"
```

---

## Task 12: Sparkle Auto-Update (Private Repo)

**Files:**
- Modify: `Package.swift` (add Sparkle dependency)
- Modify: `Claude Voice/App.swift`
- Modify: `Claude Voice/Views/MenuBarView.swift`

Add Sparkle `SPUStandardUpdaterController`. "Check for Updates" menu item. Placeholder `appcast.xml`.

**Commit:**
```bash
git commit -m "feat: Sparkle auto-update support"
```

---

## Task 13: DMG Build Script (Private Repo)

**Files:**
- Create: `build-dmg.sh`

Script that:
1. `swift build -c release`
2. Creates `.app` bundle structure with `Info.plist`
3. Clones public `claude-voice` repo, copies daemon/hooks/install.sh into `Contents/Resources/`
4. Creates DMG with `hdiutil`

```bash
#!/bin/bash
set -e

# Build release
swift build -c release

# Create .app bundle
APP_DIR="build/Claude Voice.app"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

cp .build/release/Claude\ Voice "$APP_DIR/Contents/MacOS/"

# Bundle daemon from public repo for first-run setup
DAEMON_REPO="https://github.com/YOUR_USER/claude-voice.git"
TEMP_DIR=$(mktemp -d)
git clone --depth 1 "$DAEMON_REPO" "$TEMP_DIR/claude-voice"
cp -r "$TEMP_DIR/claude-voice/daemon" "$APP_DIR/Contents/Resources/"
cp -r "$TEMP_DIR/claude-voice/hooks" "$APP_DIR/Contents/Resources/"
cp "$TEMP_DIR/claude-voice/install.sh" "$APP_DIR/Contents/Resources/"
cp "$TEMP_DIR/claude-voice/config.yaml.example" "$APP_DIR/Contents/Resources/"
cp "$TEMP_DIR/claude-voice/claude-voice-daemon" "$APP_DIR/Contents/Resources/"
rm -rf "$TEMP_DIR"

# Create DMG
hdiutil create -volname "Claude Voice" \
    -srcfolder build/ -ov -format UDZO \
    "build/Claude-Voice.dmg"
```

**Commit:**
```bash
git commit -m "feat: DMG build script"
```

---

## Task 14: End-to-End Verification (Both Repos)

1. **Path A (developer):** `git clone claude-voice && ./install.sh` — works identically to before
2. **Path B (app):** Build and run SwiftUI app — menu bar icon, settings, daemon control all work
3. **Control socket:** Verify `.control.sock` and `.tts.sock` both work independently
4. **Settings round-trip:** Change setting in UI → `config.yaml` updates → daemon reloads
5. **Mode/voice toggles:** Menu bar controls work via control socket
6. **Daemon lifecycle:** Start/stop from menu bar, PID file correct
7. **Existing CLI:** `cv start`, `cv stop`, `cvf`, `cvs` still work alongside the app
8. **Both paths coexist:** Install via script, then also run the app — no conflicts