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

## Project Structure

```
claude-voice/
  app/                          # NEW — SwiftUI Xcode project
    Claude Voice.xcodeproj
    Claude Voice/
      App.swift                 # @main, MenuBarExtra
      MenuBarView.swift         # Dropdown menu
      SettingsView.swift        # Preferences window
      SetupWizardView.swift     # First-run setup
      DaemonManager.swift       # Start/stop/monitor daemon
      ControlSocket.swift       # Unix socket client
      ConfigManager.swift       # Read/write config.yaml
      Models/
        AppState.swift          # Observable state
        Config.swift            # Config.yaml model
      Resources/
        Assets.xcassets         # Menu bar icon
    Sparkle/                    # Auto-update framework
  daemon/                       # UNCHANGED — Python daemon
  hooks/                        # UNCHANGED — Claude Code hooks
  install.sh                    # UNCHANGED — developer install
  ...
```

## Daemon-Side Changes

Minimal changes to the Python daemon:

1. **New control socket server** in `main.py`: listen on `.control.sock`, handle JSON commands, emit events
2. **Config reload command**: re-read `config.yaml` without restart
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