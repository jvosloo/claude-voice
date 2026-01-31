# Testing Strategy Design

## Overview

Add a layered test suite to claude-voice using pytest. The strategy prioritises value-per-effort: start with pure logic tests that need no mocking, then add mock-boundary tests for state machines and error paths, then make small refactoring changes to unlock testability for currently-untestable code.

Hardware-coupled code (audio recording, keyboard simulation, overlay rendering, ML model calls) is explicitly excluded — manual testing is the right tool for those.

## Framework and Structure

**Framework:** pytest with `unittest.mock`

```
tests/
├── conftest.py                  # Shared fixtures (mock config, temp dirs)
├── unit/                        # Pure logic, no or minimal mocks
│   ├── test_config.py
│   ├── test_text_processing.py
│   ├── test_voice_commands.py
│   ├── test_telegram_keyboards.py
│   ├── test_hotkey_logic.py
│   └── test_audio_utils.py
├── integration/                 # Mocked I/O boundaries
│   ├── test_telegram_client.py
│   ├── test_cleanup.py
│   ├── test_control_server.py
│   ├── test_afk_state.py
│   └── test_hooks.py
└── conftest.py
```

## Tier 1: Pure Logic Unit Tests (~15 test cases)

Tests that exercise existing functions with zero code changes. Highest value starting point — covers the trickiest logic (text parsing, regex chains, state decisions).

### Text Processing (speak-response.py)

**`clean_text_for_speech()`** — 8 regex operations in sequence (strip code blocks, inline code, markdown, links, whitespace). Order-dependent.
- Markdown-heavy input with nested formatting
- Empty string
- `max_chars` truncation at word boundary
- Input with only code blocks (should return empty or minimal text)
- Excess whitespace normalisation

**`extract_last_assistant_message()`** — JSONL parsing that skips tool_use blocks and extracts the final assistant turn.
- Multi-turn transcript with tool results mixed in
- Transcript with only tool_use blocks (should return empty)
- Empty file
- Malformed JSON lines (should skip gracefully)
- Single assistant message

### Telegram Formatting (afk.py / notify.py)

**`_markdown_to_telegram_html()`** — 11 regex replacements converting markdown to Telegram HTML.
- Fenced code blocks (triple backticks)
- Nested bold/italic
- HTML-unsafe characters (& < >) in input
- Mixed markdown and plain text
- Empty string

**`_escape_html()`** — ampersand, angle bracket escaping.
- All special characters
- Already-escaped input (should not double-escape)
- Empty string

**`make_options_keyboard()` / `make_permission_keyboard()`** — pure data structure builders.
- Empty options list
- Single option
- Multiple options with special characters

### Voice Command Recognition (main.py)

**`_handle_voice_command()`** — string matching for voice commands.
- All documented commands: "stop speaking", "stop talking", "start speaking", "start talking"
- Mode switch commands: "switch to narrate mode", "switch to notify mode"
- AFK toggle commands
- Near-misses that should NOT trigger (e.g. "I was speaking about")
- Case sensitivity behaviour

### Hotkey Logic (hotkey.py)

**`_cycle_language()`** — language index wrap-around.
- Single language (should stay on index 0)
- Multiple languages, cycling through and wrapping

### Audio Utilities (audio.py)

**`get_duration()`** — `len(audio) / sample_rate`.
- Normal audio array
- Zero-length array
- Different sample rates

## Tier 2: Mock-Boundary Tests (~25-30 test cases)

Tests that exercise real logic but mock I/O edges (HTTP, files, sockets, subprocesses). Covers state machines and error paths where bugs hide.

### Config Loading (config.py)

Mock `open()` and `yaml.safe_load()`.
- Valid config with all fields
- Missing config file returns defaults
- Malformed YAML raises or returns defaults
- Missing keys fall back gracefully
- `AfkConfig.__post_init__` dict-to-dataclass conversion with None, dict, and pre-instantiated values

### Telegram Client (telegram.py)

Mock `requests.get/post`.
- `send_message()` success response and failure response
- `verify()` success, timeout, connection error
- `_handle_update()` accepts correct chat_id, rejects wrong chat_id
- `_poll_loop()` exponential backoff on consecutive errors
- `answer_callback()` success path
- `delete_message()` success and failure

### Cleanup Pipeline (cleanup.py)

Mock `subprocess.run()`.
- `ensure_ready()` — Ollama not installed, model available, model missing triggers pull, pull timeout
- `cleanup()` returns original text on any subprocess failure (graceful degradation)
- Output post-processing: strips "Output:" prefix, removes wrapping quotes

### Control Server (control.py)

Mock the daemon object passed to `_handle_command()`.
- "status" returns correct state dict
- "set_mode" with valid and invalid mode values
- "voice_on" / "voice_off" toggle correctly
- "reload_config" triggers config reload
- "stop" triggers shutdown
- "subscribe" registers connection
- Unknown command returns error response

### AFK State Machine (afk.py)

Mock `_send()` and file I/O.
- `activate()` / `deactivate()` state transitions
- `handle_hook_request()` routing: "permission", "ask_user_question", "input", "context" types
- Message truncation at character limit
- `_handle_message()` command routing: /status, /afk, /stop
- `_handle_callback()` button response processing

### Hook Utilities (_common.py)

Mock socket for `send_to_daemon()`.
- Successful round-trip (send command, receive response)
- Connection refused handling
- `wait_for_response()` — file appears before timeout, file doesn't appear (timeout)
- `read_mode()` — valid mode, invalid mode, missing file

## Tier 3: Targeted Refactoring

Four small code changes that unlock testability. No architectural overhaul — just moving existing code to where tests can reach it.

### 1. Deduplicate `_markdown_to_telegram_html()` and `_escape_html()`

These are duplicated identically in `afk.py` and `notify.py`. Extract to a shared `daemon/formatting.py`. One place to test, one place to fix.

**Files changed:** `daemon/formatting.py` (new), `daemon/afk.py`, `daemon/notify.py`

### 2. Dependency injection for VoiceDaemon

The constructor in `main.py` hard-creates all 6 heavy components. Change to optional parameters with defaults:

```python
def __init__(self, config, recorder=None, transcriber=None, keyboard=None,
             hotkey_listener=None, tts_engine=None, overlay=None):
    self.recorder = recorder or AudioRecorder(config)
    self.transcriber = transcriber or Transcriber(config)
    ...
```

Tests can pass lightweight fakes without loading ML models or requiring hardware.

**Files changed:** `daemon/main.py`

### 3. Extract `_read_mode()` / `_write_mode()` to shared module

These file-flag operations are used across daemon and hooks. Move to shared location (e.g., `hooks/_common.py` or a new `daemon/state.py`).

**Files changed:** `daemon/main.py`, target shared module

### 4. Extract transcript parsing from speak-response.py

`extract_last_assistant_message()` and `clean_text_for_speech()` are pure functions trapped in a hook script. Move to `daemon/text.py` so tests can import them directly.

**Files changed:** `daemon/text.py` (new), `hooks/speak-response.py`

## What NOT to Test

**Hardware I/O** — `audio.py` (mic), `keyboard.py` (pynput), `hotkey.py` (system listener). Thin OS wrappers; mocking them proves nothing about hardware.

**Overlay rendering** — `overlay.py` (571 lines of PyObjC). Visual output; verify with eyes.

**Spinner** — `spinner.py` (37 lines). Not worth the threading setup.

**Hook entry points** — The `main()` functions in hook scripts are glue code. Test the functions they call, not the glue.

**ML model calls** — `tts.py` and `transcribe.py` model invocations. Test the code *around* them (text cleaning, config selection), not the model calls.

## Summary

| Tier | Test Cases | Effort | Coverage |
|------|-----------|--------|----------|
| 1 — Pure logic | ~15 | Low | Text parsing, regex chains, voice commands, keyboards |
| 2 — Mock boundaries | ~25-30 | Medium | Config, Telegram, cleanup, control, AFK state, hooks |
| 3 — Refactoring | 4 changes | Medium | Dedup formatting, DI for daemon, extract shared utils |

**Total:** ~40-45 test cases covering the logic that matters, with a clear boundary around what's not worth automated testing.