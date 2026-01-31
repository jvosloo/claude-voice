# Native macOS App Design

## Goal

Package claude-voice as a native macOS app while preserving the existing developer install path.

## Two Install Paths

**Path A (developer):** `git clone` + `./install.sh` — unchanged, works as today.

**Path B (user):** Download DMG → drag `Claude Voice.app` to `/Applications` → first-launch wizard sets up `~/.claude-voice/`.

Both paths produce the same result: a fully configured `~/.claude-voice/` directory with daemon, venv, models, and hooks.

## Architecture

Two-process design. The SwiftUI app is an optional companion to the Python daemon — it adds UI chrome but the daemon remains fully self-contained.

```
┌─────────────────────┐         ┌──────────────────────────┐
│   Claude Voice.app  │         │   Python Daemon           │
│   (SwiftUI)         │◄──────►│   (~/.claude-voice/)      │
│                     │ control │                            │
│  • Menu bar icon    │ socket  │  • Voice recording         │
│  • Settings window  │         │  • Whisper transcription   │
│  • Daemon lifecycle │         │  • Kokoro TTS              │
│  • Setup wizard     │         │  • PyObjC overlay          │
│  • Auto-updater     │         │  • Claude Code hooks       │
└─────────────────────┘         └──────────────────────────┘
                                         ▲
                                         │ .tts.sock (unchanged)
                                         │
                                ┌────────┴─────────┐
                                │  Claude Code      │
                                │  hooks             │
                                └──────────────────┘
```

## SwiftUI App Components

### Menu Bar Icon

Static monochrome icon (waveform glyph). Click opens dropdown:

- Current mode indicator (Notify / Narrate / AFK)
- Toggle voice on/off
- Switch mode (Notify / Narrate)
- Toggle AFK mode
- Separator
- Open Settings...
- Check for Updates...
- Quit

No animated state — the PyObjC overlay and macOS's orange microphone indicator already communicate recording state.

### Settings Window

Reads/writes `~/.claude-voice/config.yaml` directly. Signals daemon to reload via control socket.

**Tabs:**

| Tab | Settings |
|-----|----------|
| Input | Hotkey picker, language hotkey, auto-submit, min audio length, typing delay, transcription cleanup toggle + model |
| Transcription | Whisper model picker, language, extra languages, backend (mlx/faster-whisper) |
| Voice | Enable/disable, mode picker, voice browser (54 Kokoro voices with preview), speed slider, language code |
| Overlay | Enable/disable, style picker (dark/frosted/colored), color pickers |
| AFK | Telegram bot token, chat ID, hotkey, voice commands |
| Advanced | Audio device selector, sample rate |

### Daemon Lifecycle Management

- Start/stop daemon from menu bar or settings
- Launch at login via `SMAppService` (macOS login items API)
- Monitor daemon health (check PID file + process existence)
- Restart daemon if it crashes

### First-Run Setup Wizard (DMG path)

On first launch, if `~/.claude-voice/` doesn't exist:

1. Welcome screen explaining what will be set up
2. Progress view: create directories, install Python packages, download models
3. Permission requests: Accessibility, Microphone
4. Option to install Claude Code hooks
5. Done — daemon starts automatically

Internally runs the same setup logic as `install.sh` via shell commands.

### Auto-Update (Sparkle)

- Sparkle framework checks `appcast.xml` hosted on GitHub Releases
- On update available: native dialog with changelog, download, replace, relaunch
- Checks on launch + periodically
- Updates both the Swift app and Python daemon files in `~/.claude-voice/`

## Communication Protocol

### Sockets

| Socket | Purpose | Protocol |
|--------|---------|----------|
| `~/.claude-voice/.tts.sock` | Hook → daemon TTS requests | Existing line-based (unchanged) |
| `~/.claude-voice/.control.sock` | Swift app ↔ daemon | New JSON protocol |

### Control Protocol

**Commands (Swift → Daemon):**

```json
{"cmd": "status"}
{"cmd": "set_mode", "mode": "narrate"}
{"cmd": "voice_on"}
{"cmd": "voice_off"}
{"cmd": "reload_config"}
{"cmd": "stop"}
```

**Events (Daemon → Swift, persistent connection):**

```json
{"event": "status", "recording": false, "mode": "notify", "voice": true, "language": "en"}
{"event": "recording_start"}
{"event": "recording_stop"}
{"event": "transcription", "text": "hello world"}
{"event": "mode_changed", "mode": "narrate"}
```

Daemon distinguishes connection types: short-lived command connections get a JSON response and close; a persistent event connection receives streaming updates.

## Distribution

**DMG contents:** `Claude Voice.app` (~50MB, no bundled Python or models).

**Build process:**
1. `xcodebuild` compiles SwiftUI app
2. Code sign with Developer ID
3. Notarize with Apple
4. `hdiutil` creates DMG

**GitHub Releases:** Each release has:
- DMG download
- Sparkle `appcast.xml` entry
- Source code (for Path A users)

## Two-Repo Structure (Open Core Model)

The Python daemon is open source. The SwiftUI app is proprietary (sold separately).

**Public repo: `claude-voice`** (existing, MIT license)
```
claude-voice/
  daemon/                       # Python daemon (+ new control.py)
  hooks/                        # Claude Code hooks
  install.sh                    # Developer install path
  ...
```

**Private repo: `claude-voice-app`** (new, proprietary)
```
claude-voice-app/
  Package.swift                 # SPM project
  Claude Voice/
    App.swift                   # @main, MenuBarExtra
    Views/
      MenuBarView.swift         # Dropdown menu
      SettingsView.swift        # Preferences window
      SetupWizardView.swift     # First-run setup
    Services/
      DaemonManager.swift       # Start/stop/monitor daemon
      ControlSocket.swift       # Unix socket client
      ConfigManager.swift       # Read/write config.yaml
      Installer.swift           # First-run setup logic
    Models/
      AppState.swift            # Observable state
      Config.swift              # Config.yaml model
    Resources/
      Assets.xcassets           # Menu bar icon
  build-dmg.sh                  # Build + bundle script
  appcast.xml                   # Sparkle update feed template
```

The private repo has NO dependency on the public repo at compile time. They communicate only via:
- The control socket protocol (`~/.claude-voice/.control.sock`)
- The config file format (`~/.claude-voice/config.yaml`)

The DMG build script clones the public repo to bundle daemon files into the app's Resources for first-run setup.

## Daemon-Side Changes (Public Repo)

Minimal changes to the Python daemon:

1. **New `daemon/control.py`**: control socket server module
2. **Updates to `daemon/main.py`**: start control server, add helper methods for mode/voice/config
3. **No other changes** — all existing functionality stays as-is

## What Stays Unchanged

- All Python daemon modules
- PyObjC overlay window
- Claude Code hooks and `.tts.sock` protocol
- `install.sh` and `uninstall.sh`
- `config.yaml` format
- CLI commands (`cv start`, `cvf`, etc.)
- Terminal-based workflow

## Verification

- Path A: `./install.sh` works identically to today
- Path B: DMG install → first-run wizard → daemon running → menu bar icon visible
- Settings changes in UI reflect in `config.yaml` and take effect in daemon
- Menu bar mode toggles work
- Auto-update finds new release from test appcast
- Both paths can coexist (install via script, then also install the app)