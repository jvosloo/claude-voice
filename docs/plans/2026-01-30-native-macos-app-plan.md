# Native macOS App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a SwiftUI macOS menu bar app that controls the existing claude-voice Python daemon, with settings UI, daemon lifecycle management, and DMG distribution.

**Architecture:** SwiftUI menu bar app communicates with the Python daemon over a new Unix control socket (`~/.claude-voice/.control.sock`). The daemon remains fully self-contained — the app is an optional companion. Config is read/written as YAML at `~/.claude-voice/config.yaml`.

**Tech Stack:** Swift 5.9+, SwiftUI, macOS 14+ (Sonoma), Yams (YAML parsing), Sparkle (auto-update), `xcodebuild`, `hdiutil`

**Design doc:** `docs/plans/2026-01-30-native-macos-app-design.md`

---

## Task 1: Xcode Project Skeleton

Create the bare minimum SwiftUI app that shows a menu bar icon and a "Quit" option.

**Files:**
- Create: `app/Claude Voice/Claude Voice.xcodeproj` (via `xcodebuild` or Xcode template)
- Create: `app/Claude Voice/App.swift`
- Create: `app/Claude Voice/Assets.xcassets/AppIcon.appiconset/Contents.json`

**Step 1: Create directory structure**

```bash
mkdir -p "app/Claude Voice/Claude Voice"
mkdir -p "app/Claude Voice/Claude Voice/Models"
mkdir -p "app/Claude Voice/Claude Voice/Views"
mkdir -p "app/Claude Voice/Claude Voice/Services"
mkdir -p "app/Claude Voice/Claude Voice/Resources"
```

**Step 2: Generate Xcode project**

Use `swift package init` is not ideal for a macOS app. Instead, create a `Package.swift` for SPM-based build, or create the Xcode project manually. The simplest approach: create a minimal Xcode project using a `project.yml` and `xcodegen`, OR create files and an `xcodebuild`-compatible structure.

Recommended: Use **Swift Package Manager** with an executable target for simplicity, avoiding Xcode project file complexity. The app entry point uses `@main` and `MenuBarExtra`.

Create `app/Claude Voice/Package.swift`:
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

Create `app/Claude Voice/Claude Voice/App.swift`:
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

Create `app/Claude Voice/Claude Voice/Models/AppState.swift`:
```swift
import SwiftUI

@MainActor
class AppState: ObservableObject {
    @Published var daemonRunning = false
    @Published var currentMode = "notify"
    @Published var voiceEnabled = true
}
```

Create `app/Claude Voice/Claude Voice/Views/MenuBarView.swift`:
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

Create `app/Claude Voice/Claude Voice/Views/SettingsView.swift` (placeholder):
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

**Step 3: Build and verify**

```bash
cd "app/Claude Voice" && swift build
```

Expected: Compiles successfully.

**Step 4: Run and verify menu bar icon appears**

```bash
cd "app/Claude Voice" && swift run
```

Expected: Waveform icon appears in menu bar, clicking shows "Claude Voice" label and "Quit" button.

**Step 5: Commit**

```bash
git add app/
git commit -m "feat: add SwiftUI menu bar app skeleton"
```

---

## Task 2: Config Manager (YAML Read/Write)

Read and write `~/.claude-voice/config.yaml` from Swift using the Yams library.

**Files:**
- Create: `app/Claude Voice/Claude Voice/Models/Config.swift`
- Create: `app/Claude Voice/Claude Voice/Services/ConfigManager.swift`

**Step 1: Create Config model**

Create `app/Claude Voice/Claude Voice/Models/Config.swift` — a Swift struct mirroring `daemon/config.py`'s dataclasses. Must be `Codable` for Yams serialization.

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
        var language_hotkey: String? = nil
        var auto_submit: Bool = false
        var min_audio_length: Double = 0.5
        var typing_delay: Double = 0.01
        var transcription_cleanup: Bool = false
        var cleanup_model: String = "qwen2.5:1.5b"
    }

    struct TranscriptionConfig: Codable {
        var model: String = "base.en"
        var language: String = "en"
        var device: String = "cpu"
        var backend: String = "faster-whisper"
        var extra_languages: [String] = []
    }

    struct SpeechConfig: Codable {
        var enabled: Bool = true
        var mode: String = "notify"
        var voice: String = "af_heart"
        var speed: Double = 1.0
        var lang_code: String = "a"
        var max_chars: Int? = nil
        var skip_code_blocks: Bool = true
        var skip_tool_results: Bool = true
        var notify_phrases: [String: String]? = nil
    }

    struct AudioConfig: Codable {
        var input_device: Int? = nil
        var sample_rate: Int = 16000
    }

    struct OverlayConfig: Codable {
        var enabled: Bool = true
        var style: String = "dark"
        var recording_color: String = "#34C759"
        var transcribing_color: String = "#A855F7"
    }

    struct AfkConfig: Codable {
        var telegram: TelegramConfig?
        var hotkey: String = "left_alt+a"
        var voice_commands_activate: [String]?
        var voice_commands_deactivate: [String]?

        struct TelegramConfig: Codable {
            var bot_token: String = ""
            var chat_id: String = ""
        }
    }
}
```

**Step 2: Create ConfigManager**

Create `app/Claude Voice/Claude Voice/Services/ConfigManager.swift`:

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
cd "app/Claude Voice" && swift build
```

Expected: Compiles with Yams dependency resolved.

**Step 4: Commit**

```bash
git add app/
git commit -m "feat: add Config model and ConfigManager for YAML read/write"
```

---

## Task 3: Daemon Manager (Lifecycle Control)

Start, stop, and monitor the Python daemon from Swift.

**Files:**
- Create: `app/Claude Voice/Claude Voice/Services/DaemonManager.swift`
- Modify: `app/Claude Voice/Claude Voice/Models/AppState.swift`

**Step 1: Create DaemonManager**

Create `app/Claude Voice/Claude Voice/Services/DaemonManager.swift`:

```swift
import Foundation

class DaemonManager {
    private let installDir = NSString("~/.claude-voice").expandingTildeInPath
    private var daemonProcess: Process?

    var pidFilePath: String { "\(installDir)/daemon.pid" }
    var daemonScript: String { "\(installDir)/claude-voice-daemon" }

    var isInstalled: Bool {
        FileManager.default.fileExists(atPath: "\(installDir)/daemon/main.py")
    }

    /// Check if daemon is running by reading PID file and checking process
    func isRunning() -> Bool {
        guard let pidString = try? String(contentsOfFile: pidFilePath, encoding: .utf8),
              let pid = Int32(pidString.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return false
        }
        return kill(pid, 0) == 0
    }

    /// Start daemon in background mode
    func start() throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [daemonScript, "start"]
        try process.run()
        process.waitUntilExit()
    }

    /// Stop daemon
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

Update `AppState.swift` to use DaemonManager:

```swift
@MainActor
class AppState: ObservableObject {
    @Published var daemonRunning = false
    @Published var currentMode = "notify"
    @Published var voiceEnabled = true

    let daemonManager = DaemonManager()
    let configManager = ConfigManager()
    private var pollTimer: Timer?

    func startPolling() {
        pollTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.daemonRunning = self?.daemonManager.isRunning() ?? false
            }
        }
        daemonRunning = daemonManager.isRunning()
    }

    func toggleDaemon() {
        do {
            if daemonRunning {
                try daemonManager.stop()
            } else {
                try daemonManager.start()
            }
            // Re-check after a brief delay
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                self.daemonRunning = self.daemonManager.isRunning()
            }
        } catch {
            print("Daemon toggle error: \(error)")
        }
    }
}
```

**Step 3: Build and verify**

```bash
cd "app/Claude Voice" && swift build
```

**Step 4: Commit**

```bash
git add app/
git commit -m "feat: add DaemonManager for daemon lifecycle control"
```

---

## Task 4: Menu Bar Dropdown

Build out the full menu bar dropdown with mode toggles, voice on/off, daemon start/stop.

**Files:**
- Modify: `app/Claude Voice/Claude Voice/Views/MenuBarView.swift`
- Modify: `app/Claude Voice/Claude Voice/App.swift`

**Step 1: Build full MenuBarView**

```swift
struct MenuBarView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        // Daemon status
        HStack {
            Circle()
                .fill(appState.daemonRunning ? .green : .red)
                .frame(width: 8, height: 8)
            Text(appState.daemonRunning ? "Daemon Running" : "Daemon Stopped")
        }

        Button(appState.daemonRunning ? "Stop Daemon" : "Start Daemon") {
            appState.toggleDaemon()
        }

        Divider()

        // Mode
        Picker("Mode", selection: $appState.currentMode) {
            Text("Notify").tag("notify")
            Text("Narrate").tag("narrate")
        }

        // Voice toggle
        Toggle("Voice Output", isOn: $appState.voiceEnabled)

        Divider()

        SettingsLink {
            Text("Settings...")
        }
        .keyboardShortcut(",")

        Divider()

        Button("Quit") {
            NSApplication.shared.terminate(nil)
        }
        .keyboardShortcut("q")
    }
}
```

**Step 2: Start polling on app launch**

Update `App.swift` to start polling:

```swift
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

    init() {
        // Polling starts in AppState.init or via .onAppear in MenuBarView
    }
}
```

**Step 3: Build, run, verify menu items appear**

```bash
cd "app/Claude Voice" && swift build && swift run
```

Expected: Menu bar icon shows dropdown with daemon status, start/stop, mode picker, voice toggle, settings, quit.

**Step 4: Commit**

```bash
git add app/
git commit -m "feat: build full menu bar dropdown with daemon controls"
```

---

## Task 5: Control Socket (Python Daemon Side)

Add a control socket server to the Python daemon that accepts JSON commands and emits events.

**Files:**
- Modify: `daemon/main.py` (add control socket server alongside existing TTS socket)
- Create: `daemon/control.py` (control socket server module)

**Step 1: Create control socket module**

Create `daemon/control.py`:

```python
"""Control socket server for SwiftUI app communication."""

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
        """Handle a command and return a response."""
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
        """Send event to all subscribed connections."""
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
        """Run the control socket server."""
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

            threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            ).start()

        server.close()
        if os.path.exists(CONTROL_SOCK_PATH):
            os.unlink(CONTROL_SOCK_PATH)

    def _handle_connection(self, conn):
        """Handle a single client connection."""
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                # Try to parse — commands are single JSON objects
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

            # If this is a subscribe request, keep connection open for events
            if request.get("cmd") == "subscribe":
                conn.sendall(json.dumps(response).encode() + b"\n")
                with self._lock:
                    self._event_connections.append(conn)
                return  # Don't close — stays open for events

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

**Step 2: Wire into VoiceDaemon in `daemon/main.py`**

Add helper methods to `VoiceDaemon` for the control server to call:
- `get_mode()` → reads `_read_mode()`
- `set_mode(mode)` → calls `_write_mode(mode)`
- `get_voice_enabled()` → checks `SILENT_FLAG`
- `set_voice_enabled(enabled)` → creates/removes `SILENT_FLAG`
- `reload_config()` → re-reads `config.yaml`

Start the control server thread in `_finish_startup()` alongside the TTS server.

Add to `_shutdown()`: call `self.control_server.shutdown()`.

**Step 3: Verify daemon starts both sockets**

```bash
~/.claude-voice/claude-voice-daemon foreground
# Check both sockets exist:
ls -la ~/.claude-voice/.tts.sock ~/.claude-voice/.control.sock
```

**Step 4: Test control socket manually**

```bash
echo '{"cmd":"status"}' | socat - UNIX-CONNECT:~/.claude-voice/.control.sock
```

Expected: JSON response with daemon status.

**Step 5: Commit**

```bash
git add daemon/
git commit -m "feat: add control socket server for SwiftUI app communication"
```

---

## Task 6: Control Socket (Swift Client Side)

Connect the SwiftUI app to the daemon's control socket.

**Files:**
- Create: `app/Claude Voice/Claude Voice/Services/ControlSocket.swift`
- Modify: `app/Claude Voice/Claude Voice/Models/AppState.swift`

**Step 1: Create ControlSocket client**

Create `app/Claude Voice/Claude Voice/Services/ControlSocket.swift`:

A Swift class that:
- Connects to `~/.claude-voice/.control.sock` via Unix domain socket
- Sends JSON commands, receives JSON responses
- Supports a persistent "subscribe" connection for receiving events
- Reconnects on failure

**Step 2: Replace polling with socket events in AppState**

Update `AppState` to:
- On launch, connect to control socket and subscribe for events
- Mode/voice changes send commands through the socket instead of writing files directly
- Fall back to polling if socket is unavailable (daemon not running)

**Step 3: Build and test**

```bash
cd "app/Claude Voice" && swift build && swift run
```

With daemon running, verify menu bar shows correct status and mode toggles work.

**Step 4: Commit**

```bash
git add app/
git commit -m "feat: add ControlSocket client for daemon communication"
```

---

## Task 7: Settings Window — Input & Transcription Tabs

Build the first two settings tabs.

**Files:**
- Modify: `app/Claude Voice/Claude Voice/Views/SettingsView.swift`
- Create: `app/Claude Voice/Claude Voice/Views/InputSettingsView.swift`
- Create: `app/Claude Voice/Claude Voice/Views/TranscriptionSettingsView.swift`

**Step 1: Build InputSettingsView**

Form with:
- Hotkey picker (dropdown of supported hotkeys: `right_alt`, `left_alt`, etc.)
- Language hotkey picker (same options + nil)
- Auto-submit toggle
- Min audio length stepper (0.1 - 5.0)
- Typing delay stepper (0.0 - 0.1)
- Transcription cleanup toggle
- Cleanup model text field

**Step 2: Build TranscriptionSettingsView**

Form with:
- Model picker (`tiny.en`, `base.en`, `small.en`, `medium.en`, `large-v3`)
- Language text field
- Extra languages (comma-separated text field, parsed to array)
- Backend picker (`mlx`, `faster-whisper`)

**Step 3: Wire into SettingsView with TabView**

```swift
struct SettingsView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        TabView {
            InputSettingsView(config: $appState.config)
                .tabItem { Label("Input", systemImage: "keyboard") }
            TranscriptionSettingsView(config: $appState.config)
                .tabItem { Label("Transcription", systemImage: "mic") }
        }
        .frame(width: 500, height: 400)
    }
}
```

On change, save config via `ConfigManager.save()` and send `reload_config` via control socket.

**Step 4: Build, run, verify settings window opens from menu bar**

**Step 5: Commit**

```bash
git add app/
git commit -m "feat: add Input and Transcription settings tabs"
```

---

## Task 8: Settings Window — Voice & Overlay Tabs

**Files:**
- Create: `app/Claude Voice/Claude Voice/Views/VoiceSettingsView.swift`
- Create: `app/Claude Voice/Claude Voice/Views/OverlaySettingsView.swift`
- Modify: `app/Claude Voice/Claude Voice/Views/SettingsView.swift`

**Step 1: Build VoiceSettingsView**

Form with:
- Enabled toggle
- Mode picker (notify / narrate)
- Voice picker (dropdown of Kokoro voice IDs — hardcode the list from README)
- Speed slider (0.5 - 2.0)
- Language code picker (a=American, b=British, j=Japanese, z=Chinese, e=Spanish, f=French)
- Max chars stepper (nil / 100-5000)
- Skip code blocks toggle
- Skip tool results toggle

**Step 2: Build OverlaySettingsView**

Form with:
- Enabled toggle
- Style picker (dark / frosted / colored)
- Recording color picker (native macOS `ColorPicker`)
- Transcribing color picker

**Step 3: Add tabs to SettingsView**

**Step 4: Build, verify all four tabs work**

**Step 5: Commit**

```bash
git add app/
git commit -m "feat: add Voice and Overlay settings tabs"
```

---

## Task 9: Settings Window — AFK & Advanced Tabs

**Files:**
- Create: `app/Claude Voice/Claude Voice/Views/AfkSettingsView.swift`
- Create: `app/Claude Voice/Claude Voice/Views/AdvancedSettingsView.swift`
- Modify: `app/Claude Voice/Claude Voice/Views/SettingsView.swift`

**Step 1: Build AfkSettingsView**

Form with:
- Telegram section: bot token (SecureField), chat ID text field
- AFK hotkey picker
- Voice commands (text fields, comma-separated)

**Step 2: Build AdvancedSettingsView**

Form with:
- Audio input device picker (list system audio devices via `AVCaptureDevice`)
- Sample rate picker (16000, 44100, 48000)

**Step 3: Add tabs, build, verify**

**Step 4: Commit**

```bash
git add app/
git commit -m "feat: add AFK and Advanced settings tabs"
```

---

## Task 10: Launch at Login

Add "Launch at Login" toggle using `SMAppService`.

**Files:**
- Modify: `app/Claude Voice/Claude Voice/Views/AdvancedSettingsView.swift`
- Modify: `app/Claude Voice/Claude Voice/Models/AppState.swift`

**Step 1: Add launch-at-login toggle to AdvancedSettingsView**

Use `SMAppService.mainApp` to register/unregister as login item:

```swift
import ServiceManagement

Toggle("Launch at Login", isOn: Binding(
    get: { SMAppService.mainApp.status == .enabled },
    set: { enabled in
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            print("Login item error: \(error)")
        }
    }
))
```

**Step 2: Auto-start daemon when app launches**

In `AppState.init()`, if daemon is not running, start it.

**Step 3: Build, verify toggle works**

**Step 4: Commit**

```bash
git add app/
git commit -m "feat: add launch-at-login support"
```

---

## Task 11: First-Run Setup Wizard

Show a setup wizard on first launch if `~/.claude-voice/` doesn't exist.

**Files:**
- Create: `app/Claude Voice/Claude Voice/Views/SetupWizardView.swift`
- Create: `app/Claude Voice/Claude Voice/Services/Installer.swift`
- Modify: `app/Claude Voice/Claude Voice/App.swift`

**Step 1: Create Installer service**

`Installer.swift` — runs the setup steps from `install.sh` as `Process` calls:
- Check for Python 3.12+, FFmpeg
- Create `~/.claude-voice/` directories
- Copy daemon files from app bundle (or clone from git)
- Create venv, install pip packages
- Install Claude Code hooks
- Reports progress via a callback/publisher

**Step 2: Create SetupWizardView**

Multi-step SwiftUI view:
1. Welcome page with "Set Up" button
2. Progress page showing installation steps with progress bar
3. Permissions page (open System Preferences links for Accessibility, Microphone)
4. Done page with "Start Daemon" button

**Step 3: Show wizard conditionally in App.swift**

```swift
var body: some Scene {
    MenuBarExtra("Claude Voice", systemImage: "waveform") {
        if appState.needsSetup {
            Button("Set Up Claude Voice...") {
                appState.showSetupWizard = true
            }
        } else {
            MenuBarView(appState: appState)
        }
    }

    Window("Claude Voice Setup", id: "setup") {
        SetupWizardView(appState: appState)
    }

    Settings {
        SettingsView(appState: appState)
    }
}
```

**Step 4: Test with `~/.claude-voice/` removed (use a temp directory for safety)**

**Step 5: Commit**

```bash
git add app/
git commit -m "feat: add first-run setup wizard"
```

---

## Task 12: Sparkle Auto-Update

Integrate Sparkle framework for checking and installing updates.

**Files:**
- Modify: `app/Claude Voice/Package.swift` (add Sparkle dependency)
- Modify: `app/Claude Voice/Claude Voice/App.swift`
- Modify: `app/Claude Voice/Claude Voice/Views/MenuBarView.swift`
- Create: `app/Claude Voice/Claude Voice/Resources/Info.plist` (Sparkle feed URL)

**Step 1: Add Sparkle dependency**

In `Package.swift`:
```swift
.package(url: "https://github.com/sparkle-project/Sparkle", from: "2.0.0"),
```

**Step 2: Add SUUpdater to App**

```swift
import Sparkle

@main
struct ClaudeVoiceApp: App {
    private let updaterController: SPUStandardUpdaterController

    init() {
        updaterController = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )
    }
    // ...
}
```

**Step 3: Add "Check for Updates" to menu**

```swift
Button("Check for Updates...") {
    updaterController.checkForUpdates(nil)
}
```

**Step 4: Create placeholder appcast.xml**

Create `app/appcast.xml` as a template for GitHub Releases.

**Step 5: Build, verify "Check for Updates" menu item appears**

**Step 6: Commit**

```bash
git add app/
git commit -m "feat: add Sparkle auto-update support"
```

---

## Task 13: DMG Build Script

Create a script that builds the app, signs it, and creates a DMG.

**Files:**
- Create: `app/build-dmg.sh`

**Step 1: Create build script**

```bash
#!/bin/bash
set -e

cd "$(dirname "$0")/Claude Voice"

# Build release
swift build -c release

# Create app bundle structure
APP_DIR="build/Claude Voice.app"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

cp .build/release/Claude\ Voice "$APP_DIR/Contents/MacOS/"
# Create Info.plist with bundle ID, version, etc.

# Copy daemon files into Resources for first-run setup
cp -r ../../daemon "$APP_DIR/Contents/Resources/"
cp -r ../../hooks "$APP_DIR/Contents/Resources/"
cp ../../install.sh "$APP_DIR/Contents/Resources/"
cp ../../config.yaml.example "$APP_DIR/Contents/Resources/"
cp ../../claude-voice-daemon "$APP_DIR/Contents/Resources/"

# Create DMG
hdiutil create -volname "Claude Voice" \
    -srcfolder build/ \
    -ov -format UDZO \
    "build/Claude-Voice.dmg"

echo "DMG created: build/Claude-Voice.dmg"
```

**Step 2: Test build**

```bash
chmod +x app/build-dmg.sh && ./app/build-dmg.sh
```

Expected: `app/Claude Voice/build/Claude-Voice.dmg` exists and mounts correctly.

**Step 3: Commit**

```bash
git add app/build-dmg.sh
git commit -m "feat: add DMG build script"
```

---

## Task 14: End-to-End Verification

Verify both install paths work and the full flow functions.

**Steps:**

1. **Path A (developer):** Run `./install.sh` — verify it works identically to before
2. **Path B (app):** Run the SwiftUI app — verify menu bar icon, settings window, daemon control all work
3. **Settings round-trip:** Change a setting in the UI → verify `config.yaml` updates → verify daemon picks up the change
4. **Mode toggle:** Toggle mode in menu bar → verify daemon switches mode
5. **Voice toggle:** Toggle voice → verify daemon responds
6. **Daemon lifecycle:** Start/stop daemon from menu bar → verify PID file and process state
7. **Control socket:** Verify `.control.sock` and `.tts.sock` both work independently
8. **Existing CLI:** Verify `cv start`, `cv stop`, `cvf`, `cvs` still work alongside the app

**Commit:**

```bash
git commit -m "docs: complete native macOS app implementation"
```
