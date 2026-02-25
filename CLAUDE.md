# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

```bash
# ALWAYS deploy after code changes
./deploy.sh

# Restart daemon (after deploying code changes)
~/.claude-voice/claude-voice-daemon restart

# Reload config only (no restart needed)
~/.claude-voice/claude-voice-daemon reload
```

## Project Overview

Claude Voice is a macOS daemon providing push-to-talk voice input and bidirectional voice output for Claude Code. It transcribes speech via Whisper, types it into the focused app, and speaks Claude's responses via Kokoro TTS.

**Platform:** macOS only (Apple Silicon recommended). Uses `afplay` for audio playback, PyObjC for the overlay UI.

## Commands

```bash
# Run all tests
~/.claude-voice/venv/bin/python -m pytest tests/ -v

# Run a single test
~/.claude-voice/venv/bin/python -m pytest tests/unit/test_config.py -k "test_name" -v

# Coverage
~/.claude-voice/venv/bin/python -m pytest tests/ --cov=daemon --cov=hooks --cov-report=term-missing
```

No linter or formatter. No build step — pure Python with a virtualenv at `~/.claude-voice/venv/`.

## Architecture

### Two-Process Model

1. **Daemon** (`daemon/`) — long-running background process. Entry point: `main.py` → `VoiceDaemon`
2. **Hooks** (`hooks/`) — short-lived scripts executed by Claude Code on events

Communication via Unix sockets:
- **Hooks → Daemon:** TTS/notify requests via `~/.claude-voice/.tts.sock`
- **CLI → Daemon:** control commands via `~/.claude-voice/.control.sock`

### Threading Model

- **Main thread:** Cocoa NSRunLoop for overlay — all NSWindow/NSView operations must happen here
- **Background threads:** TTS socket server, control server, hotkey listener
- Threading locks protect shared state (audio chunks, events)

### Hooks (`hooks/`)

Installed to `~/.claude/hooks/` by the installer. Hook-to-event mapping:

| Script | Claude Code Event | Role |
|--------|------------------|------|
| `speak-response.py` | Stop | Sends response text to daemon for TTS |
| `permission-request.py` | PermissionRequest | Checks stored permission rules; returns allow or ask |
| `notify-permission.py` | Notification (`permission_prompt`) | Plays "permission needed" audio cue |
| `handle-ask-user.py` | PreToolUse (`AskUserQuestion`) | Plays "question" phrase + sets flag |
| `_common.py` | — | Shared paths, utilities, `get_session()` |

### Configuration

YAML at `~/.claude-voice/config.yaml` (see `config.yaml.example`). Hot-reloads without daemon restart via `reload_config` control command.

### State Files (all in `~/.claude-voice/`)

- `.silent` — flag file disabling voice output
- `daemon.pid` — daemon process ID
- `permission_rules.json` — stored "always allow" permission rules

Temporary state (in `/tmp/claude-voice/`):
- `.ask_user_active` — flag for AskUserQuestion in progress (suppresses "permission needed" phrase)

### Debug Logs (in `/tmp/claude-voice/logs/`)

- `permission_hook.log` — permission hook debug trace
- `permission_hook_input.json` — last raw hook input JSON
- `stop_hook.log` — Stop hook debug trace
- `ask-user-debug.log` — AskUserQuestion hook debug trace
- `hook_errors.log` — general hook error log (all hooks)

## Testing Conventions

- Tests use `pytest` with `unittest.mock`. Unit tests (`tests/unit/`) have no external dependencies; integration tests (`tests/integration/`) may need mocked sockets/files
- Hook scripts with hyphens in filenames (e.g., `permission-request.py`) must be imported via `importlib.util.spec_from_file_location` — see `test_permission_hook.py`

## Key Patterns

- **Hooks fail silently:** if the daemon isn't running, hooks exit gracefully rather than erroring
- **Permission flow:** Two hooks handle permissions: `permission-request.py` (PermissionRequest) fires *before* the dialog to check stored rules; `notify-permission.py` (Notification) fires *after* to play the audio cue
- **PortAudio retry:** AudioRecorder has retry logic with backoff for macOS AUHAL error -50

## Settings App Coordination

A separate macOS SwiftUI menu bar app (repo: `~/IdeaProjects/claude-voice-app`) controls this daemon. Cross-boundary changes are coordinated via `~/.claude-voice/dev/coordination.md`.

- **Read it** before changing the socket API or config.yaml schema
- **Write to it** under `## From Daemon App` when you need the settings app to implement something
- The settings app agent writes under `## From Settings App`

## Control Socket API

Commands sent as JSON over `~/.claude-voice/.control.sock`:

| Command         | JSON                                      | Response                                                      |
|-----------------|-------------------------------------------|---------------------------------------------------------------|
| status          | `{"cmd": "status"}`                       | `{"daemon": true, "mode": "notify", "voice": true, "recording": false, "ready": true}` |
| set_mode        | `{"cmd": "set_mode", "mode": "notify"}`   | `{"ok": true}`                                                |
| voice_on        | `{"cmd": "voice_on"}`                     | `{"ok": true}`                                                |
| voice_off       | `{"cmd": "voice_off"}`                    | `{"ok": true}`                                                |
| reload_config   | `{"cmd": "reload_config"}`                | `{"ok": true}`                                                |
| speak           | `{"cmd": "speak"}`                        | `{"ok": true}` — plays "Over to you" phrase                   |
| preview_overlay | `{"cmd": "preview_overlay"}`              | `{"ok": true}` — shows recording 1.5s, transcribing 1s, hide |
| stop            | `{"cmd": "stop"}`                         | `{"ok": true}` — graceful shutdown                            |
| subscribe       | `{"cmd": "subscribe"}`                    | streams newline-delimited JSON events                         |

Status response fields: `daemon` (always true), `mode` (notify/narrate), `voice` (output enabled), `recording` (mic active), `ready` (fully initialized).

## Deployment

The daemon runs from `~/.claude-voice/`, not this repo. Run `./deploy.sh` after every code change — it copies daemon and hook files to the installation and advises if a restart is needed.

## Gotchas

- **Don't commit without being asked:** Only commit when the user explicitly requests it.
- **Deploy after every code change:** ALWAYS run `./deploy.sh` after editing daemon or hooks files. This is not optional.
- **Overlay must use main thread:** Use `performSelectorOnMainThread_withObject_waitUntilDone_` for thread-safe dispatch. `NSWindowBelow` = -1, `NSWindowAbove` = 1 (not 0 or 2).
- **PyYAML scientific notation:** `safe_load` parses `5e-1` as string, not float. Use decimal form (`0.5`, `0.0`, `1.0`).
- **Notify phrases are cached .wav files:** When voice/speed/lang_code changes, `regenerate_custom_phrases` must be called. `reload_config` handles this automatically.
- **Check crash reports:** macOS crash logs at `~/Library/Logs/DiagnosticReports/python3.13-*.ips` — useful when ObjC exceptions kill the process without a Python traceback.
- **settings.json hooks must be surgical:** install.sh and uninstall.sh identify claude-voice hooks by command path, not category name. Other tools may share hook categories. Always filter by `is_cv_hook()` — never overwrite or delete an entire category.
- **No osascript/AppleScript:** The project doesn't use Terminal.app or System Events automation.
