# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

```bash
# ALWAYS deploy after code changes
./deploy.sh

# Run all tests
~/.claude-voice/venv/bin/python -m pytest tests/ -v

# Restart daemon (after deploying code changes)
~/.claude-voice/claude-voice-daemon restart

# Reload config only (no restart needed)
~/.claude-voice/claude-voice-daemon reload
```

## Project Overview

Claude Voice is a macOS daemon providing push-to-talk voice input and bidirectional voice output for Claude Code. It transcribes speech via Whisper, types it into the focused app, and speaks Claude's responses via Kokoro TTS. An AFK mode enables remote interaction through Telegram.

**Platform:** macOS only (Apple Silicon recommended). Uses `afplay` for audio playback, PyObjC for the overlay UI.

## Commands

```bash
# Run all tests (uses the project's virtualenv)
~/.claude-voice/venv/bin/python -m pytest tests/ -v

# Run a single test file
~/.claude-voice/venv/bin/python -m pytest tests/unit/test_config.py -v

# Run a single test by name
~/.claude-voice/venv/bin/python -m pytest tests/unit/test_config.py -k "test_name" -v

# Unit tests only
~/.claude-voice/venv/bin/python -m pytest tests/unit/ -v

# Integration tests only
~/.claude-voice/venv/bin/python -m pytest tests/integration/ -v

# Coverage report
~/.claude-voice/venv/bin/python -m pytest tests/ --cov=daemon --cov=hooks --cov-report=term-missing
```

There is no linter or formatter configured. No build step — pure Python with a virtualenv at `~/.claude-voice/venv/`.

## Architecture

### Two-Process Model

The system has two sides that communicate via Unix sockets:

1. **Daemon** (`daemon/`) — long-running background process handling audio I/O, transcription, TTS, overlay UI, and AFK mode
2. **Hooks** (`hooks/`) — short-lived scripts executed by Claude Code on events (response complete, permission needed, user input requested)

Communication flows:
- **Hooks → Daemon:** hooks send TTS/notify requests to the daemon via `~/.claude-voice/.tts.sock`
- **CLI → Daemon:** the `claude-voice-daemon` shell wrapper sends control commands via `~/.claude-voice/.control.sock`

### Daemon Internals (`daemon/`)

`main.py` contains `VoiceDaemon`, the main orchestrator. It wires together:

- **HotkeyListener** (`hotkey.py`) — push-to-talk via pynput, language cycling, AFK combo hotkey, speech toggle combo hotkey
- **AudioRecorder** (`audio.py`) — records via sounddevice, opens/closes stream per recording to control the macOS mic indicator
- **Transcriber** (`transcribe.py`) — Whisper STT with two backends: MLX (Apple Silicon) and faster-whisper (CPU). Also contains `apply_word_replacements()` for post-transcription corrections
- **KeyboardSimulator** (`keyboard.py`) — types transcribed text into the focused app via pynput
- **TranscriptionCleaner** (`cleanup.py`) — optional LLM-based transcription cleanup via Ollama
- **TTSEngine** (`tts.py`) — Kokoro neural TTS via mlx-audio
- **Overlay** (`overlay.py`) — floating macOS window (PyObjC/Cocoa/Quartz) with animated waveform, transcription dots, state indicators. Runs on the Cocoa NSRunLoop on the main thread
- **ControlServer** (`control.py`) — Unix socket server for JSON command/response protocol
- **AfkManager** (`afk.py`) — Telegram bot integration with pending request tracking and Stop hook follow-up routing
- **RequestQueue** (`request_queue.py`) — FIFO queue for AFK permission/input requests with session tracking
- **RequestRouter** (`request_router.py`) — routes Telegram button presses and text messages to the correct queued request
- **SessionPresenter** (`session_presenter.py`) — formats AFK request messages and inline buttons for Telegram
- **TelegramClient** (`telegram.py`) — HTTP wrapper for the Telegram Bot API with long-polling
- **NotifySystem** (`notify.py`) — short audio phrase playback for status events (permission, done)

### Threading Model

- **Main thread:** Cocoa NSRunLoop for overlay animations
- **Background threads:** TTS socket server, control server, hotkey listener, Telegram long-polling
- Audio chunks and events use threading locks for safe cross-thread access

### Hooks (`hooks/`)

Installed to `~/.claude/hooks/` by the installer. Each hook is a standalone script:

- `speak-response.py` — Stop hook: reads the Claude JSONL transcript, extracts the last assistant message, cleans it (strips code blocks, markdown, tool results), sends to daemon for TTS. In AFK mode, blocks waiting for a Telegram follow-up message and returns a "block" decision to continue Claude with the user's instruction
- `permission-request.py` — PermissionRequest hook: intercepts permission requests before the dialog. In AFK mode, sends tool details (e.g. "Bash: `cat /etc/hosts`") to Telegram and returns programmatic allow/deny. In non-AFK mode, returns "ask" to show the normal dialog
- `notify-permission.py` — Notification hook: plays "permission needed" audio cue when the permission dialog appears. No-op in AFK mode (PermissionRequest hook handles it)
- `handle-ask-user.py` — PreToolUse hook (matcher: AskUserQuestion): in AFK mode, blocks until Telegram response arrives, then returns deny-with-answer so Claude reads the answer from the reason
- `_common.py` — shared paths, utilities, and permission rule storage (TTS_SOCK_PATH, SILENT_FLAG, MODE_FILE, permission rules)

### Configuration

YAML-based at `~/.claude-voice/config.yaml` (see `config.yaml.example` for all options). Loaded via dataclasses in `config.py` with defaults for all fields. Config hot-reloads without daemon restart — the control server handles `reload_config` and updates components in-place.

### State Files (all in `~/.claude-voice/`)

- `.silent` — flag file disabling voice output
- `.mode` — current TTS mode string (`notify`/`narrate`/`afk`)
- `daemon.pid` — daemon process ID
- `permission_rules.json` — stored "always allow" permission rules from AFK mode

Temporary state (in `/tmp/claude-voice/`):
- `.ask_user_active` — flag for AFK user input in progress
- `sessions/<session>/response_stop` — response file for Stop hook blocking in AFK mode

### Debug Logs (in `/tmp/claude-voice/logs/`)

- `permission_hook.log` — permission hook debug trace (both hooks write here)
- `permission_hook_input.json` — last raw hook input JSON (useful for verifying schema)

## Testing Conventions

- Tests use `pytest` with `unittest.mock` for patching external dependencies (sounddevice, pynput, socket, etc.)
- Shared fixtures in `tests/conftest.py`: `sample_config_dict` and `tmp_config_file`
- Test classes grouped by component (e.g., `TestAfkConfigPostInit`, `TestHotkeyReload`)
- Unit tests (`tests/unit/`) have no external dependencies; integration tests (`tests/integration/`) may need mocked sockets/files
- The project root is added to `sys.path` in conftest.py so `daemon` and `hooks` are directly importable
- Hook scripts with hyphens in filenames (e.g., `permission-request.py`) must be imported via `importlib.util.spec_from_file_location` in tests — see `test_permission_hook.py` for the pattern

## Key Patterns

- **Lazy model loading:** Whisper and Kokoro models load on first use with spinner feedback, not at daemon startup
- **PortAudio retry:** AudioRecorder has retry logic with backoff for macOS AUHAL error -50
- **Hooks fail silently:** if the daemon isn't running, hooks exit gracefully rather than erroring
- **Config backward compat:** `load_config()` strips removed keys (e.g., `notify_model`) so old configs don't crash
- **Voice commands:** transcribed text is checked for command phrases ("stop speaking", "switch to narrate mode", etc.) before being typed
- **Word replacements:** `transcription.word_replacements` applies deterministic regex-based corrections after Whisper, before LLM cleanup. Case-insensitive whole-word matching via `\b` boundaries. Applied passively from config on each transcription — no special reload logic needed
- **Speech toggle hotkey:** `speech.hotkey` (default `left_alt+v`) toggles voice on/off via a second combo hotkey slot in `HotkeyListener`. Plays audio cues, flashes overlay, and broadcasts `voice_changed` events
- **AFK permission flow:** Two hooks handle permissions: `permission-request.py` (PermissionRequest) fires *before* the dialog and returns programmatic allow/deny/ask; `notify-permission.py` (Notification) fires *after* the dialog appears for audio cues only. In AFK mode, PermissionRequest handles everything so the dialog never appears and Notification never fires
- **AFK follow-up flow:** The Stop hook (`speak-response.py`) blocks in AFK mode after sending context to Telegram. When the user sends a follow-up message, the daemon writes it to a response file and the hook returns a "block" decision with the message as the reason. This lets Claude continue working with the user's instruction without any terminal injection. The `/back` command writes a `__back__` sentinel to unblock all waiting hooks

## Settings App Coordination

A separate macOS SwiftUI menu bar app (repo: `~/IdeaProjects/claude-voice-app`) controls this daemon. It is developed by a separate Claude Code session. Cross-boundary changes (new socket commands, config schema changes, etc.) are coordinated via `~/.claude-voice/dev/coordination.md`.

- **Read it** before making changes that affect the socket API or config.yaml schema
- **Write to it** under `## From Daemon App` when you need the settings app to implement something
- Mark items `[DONE]` when handled
- The settings app agent writes under `## From Settings App`

## Control Socket API

Commands sent as JSON over `~/.claude-voice/.control.sock`:

| Command         | JSON                                      | Response                                                      |
|-----------------|-------------------------------------------|---------------------------------------------------------------|
| status          | `{"cmd": "status"}`                       | `{"mode": "notify", "voice": true}`                           |
| set_mode        | `{"cmd": "set_mode", "mode": "notify"}`   | `{"ok": true}`                                                |
| voice_on        | `{"cmd": "voice_on"}`                     | `{"ok": true}`                                                |
| voice_off       | `{"cmd": "voice_off"}`                    | `{"ok": true}`                                                |
| reload_config   | `{"cmd": "reload_config"}`                | `{"ok": true}`                                                |
| speak           | `{"cmd": "speak"}`                        | `{"ok": true}` — plays "Ready for input" phrase               |
| preview_overlay | `{"cmd": "preview_overlay"}`              | `{"ok": true}` — shows recording 1.5s, transcribing 1s, hide |
| stop            | `{"cmd": "stop"}`                         | `{"ok": true}` — graceful shutdown                            |
| subscribe       | `{"cmd": "subscribe"}`                    | streams newline-delimited JSON events                         |

## Deployment

The local installation at `~/.claude-voice/` is separate from this repo. After making changes, deploy with:

```bash
./deploy.sh
```

The script will:
- Copy changed files from `daemon/` to `~/.claude-voice/daemon/`
- Copy changed files from `hooks/` to `~/.claude/hooks/`
- Show what changed (+ for new, * for updated)
- Check if the daemon is running
- Advise whether restart is needed

The daemon must be restarted to pick up code changes (or use `reload_config` for config-only changes).

Quick commands:
```bash
# Deploy all changes
./deploy.sh

# Restart daemon after deployment
~/.claude-voice/claude-voice-daemon restart

# Reload config only (no restart)
~/.claude-voice/claude-voice-daemon reload
```

## Gotchas

- **Don't commit without being asked:** Only commit when the user explicitly requests it.
- **Deploy after every code change:** ALWAYS run `./deploy.sh` after editing daemon or hooks files — the daemon runs from the local installation at `~/.claude-voice/`, not the repo. This is not optional.
- **Overlay must use main thread:** All NSWindow/NSView operations must happen on the main thread. Use `performSelectorOnMainThread_withObject_waitUntilDone_` for thread-safe dispatch from background threads. `NSWindowBelow` = -1, `NSWindowAbove` = 1 (not 0 or 2).
- **PyYAML scientific notation:** `safe_load` parses values like `5e-1` as strings, not floats. The settings app has a `fixScientificNotation()` workaround but values in config.yaml should use decimal form (`0.5`, `0.0`, `1.0`).
- **Notify phrases are cached .wav files:** When voice/speed/lang_code changes, `regenerate_custom_phrases` must be called to re-render them. The `reload_config` method handles this automatically.
- **Overlay colors are hardcoded:** Recording green (#34C759) and transcribing purple (#A855F7) are constants in `overlay.py`, not configurable. Only `style` (dark/frosted/colored) is user-facing.
- **Check crash reports:** macOS crash logs at `~/Library/Logs/DiagnosticReports/python3.13-*.ips` — useful when ObjC exceptions kill the process without a Python traceback.