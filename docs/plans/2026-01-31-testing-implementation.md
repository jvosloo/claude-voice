# Testing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a pytest test suite covering pure logic and mock-boundary tests for the claude-voice daemon and hooks.

**Architecture:** Three-phase approach — (1) set up pytest infrastructure, (2) write pure logic unit tests that need no code changes, (3) write mock-boundary integration tests. Tier 3 refactoring (dedup, DI, extractions) is deferred to a follow-up plan.

**Tech Stack:** pytest, unittest.mock, Python 3.12+

---

### Task 1: Set Up pytest Infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/conftest.py`
- Modify: `requirements.txt`

**Step 1: Add pytest to requirements**

Add to the end of `requirements.txt`:

```
# Testing
pytest>=7.0.0
```

**Step 2: Create test directories and conftest**

Create `tests/__init__.py` (empty).
Create `tests/unit/__init__.py` (empty).
Create `tests/integration/__init__.py` (empty).

Create `tests/conftest.py`:

```python
"""Shared test fixtures for claude-voice tests."""

import os
import sys

import pytest

# Add project root to path so `daemon` and `hooks` are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def sample_config_dict():
    """Minimal valid config dict matching config.yaml.example structure."""
    return {
        "input": {"hotkey": "right_alt"},
        "transcription": {"model": "large-v3", "language": "en"},
        "speech": {"enabled": True, "mode": "notify", "voice": "af_heart"},
        "audio": {"sample_rate": 16000},
        "overlay": {"enabled": False},
        "afk": {},
    }


@pytest.fixture
def tmp_config_file(tmp_path, sample_config_dict):
    """Write a temporary config YAML file and return its path."""
    import yaml
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(sample_config_dict))
    return str(config_path)
```

**Step 3: Install pytest into venv and verify it runs**

Run: `~/.claude-voice/venv/bin/pip install pytest`
Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v --co`
Expected: "no tests ran" (collected 0 items)

**Step 4: Commit**

```bash
git add tests/ requirements.txt
git commit -m "test: add pytest infrastructure and test directories"
```

---

### Task 2: Unit Tests — Text Processing (speak-response.py)

**Files:**
- Create: `tests/unit/test_text_processing.py`

**Step 1: Write the tests**

```python
"""Tests for text processing functions in hooks/speak-response.py."""

import json
import os
import sys
import tempfile

# The hook script uses a bash/python polyglot shebang, so we can't import
# it directly as a module. Instead, we exec the relevant functions.
# Load the module by reading and executing just the function definitions.
import importlib.util


def _load_speak_response():
    """Load speak-response.py as a module, skipping its __main__ block."""
    hook_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "hooks", "speak-response.py"
    )
    hook_path = os.path.normpath(hook_path)
    spec = importlib.util.spec_from_file_location("speak_response", hook_path)
    mod = importlib.util.module_from_spec(spec)
    # Prevent the module from running main() on import
    mod.__name__ = "speak_response"
    spec.loader.exec_module(mod)
    return mod


_mod = _load_speak_response()
clean_text_for_speech = _mod.clean_text_for_speech
extract_last_assistant_message = _mod.extract_last_assistant_message


# --- clean_text_for_speech ---

class TestCleanTextForSpeech:

    def test_removes_fenced_code_blocks(self):
        text = "Before\n```python\nprint('hi')\n```\nAfter"
        result = clean_text_for_speech(text, {})
        assert "print" not in result
        assert "Before" in result
        assert "After" in result

    def test_removes_inline_code(self):
        text = "Use the `foo()` function"
        result = clean_text_for_speech(text, {})
        assert "`" not in result
        assert "foo()" not in result
        assert "Use the" in result

    def test_preserves_code_when_skip_disabled(self):
        text = "Use `foo()` here"
        result = clean_text_for_speech(text, {"skip_code_blocks": False})
        assert "`foo()`" in result

    def test_removes_bold_markdown(self):
        text = "This is **important** text"
        result = clean_text_for_speech(text, {})
        assert "**" not in result
        assert "important" in result

    def test_removes_italic_markdown(self):
        text = "This is *emphasized* text"
        result = clean_text_for_speech(text, {})
        assert result == "This is emphasized text"

    def test_removes_headers(self):
        text = "## Section Title\nContent here"
        result = clean_text_for_speech(text, {})
        assert "##" not in result
        assert "Section Title" in result

    def test_removes_list_markers(self):
        text = "Items:\n- First\n- Second\n* Third"
        result = clean_text_for_speech(text, {})
        assert "- " not in result
        assert "* " not in result
        assert "First" in result

    def test_removes_links_keeps_text(self):
        text = "See [the docs](https://example.com) for details"
        result = clean_text_for_speech(text, {})
        assert "the docs" in result
        assert "https://example.com" not in result
        assert "[" not in result

    def test_normalises_whitespace(self):
        text = "Line one\n\n\n\n\nLine two"
        result = clean_text_for_speech(text, {})
        assert "\n\n\n" not in result
        assert "Line one" in result
        assert "Line two" in result

    def test_truncates_at_max_chars(self):
        text = "A" * 200
        result = clean_text_for_speech(text, {"max_chars": 50})
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")

    def test_no_truncation_when_under_max(self):
        text = "Short text"
        result = clean_text_for_speech(text, {"max_chars": 100})
        assert result == "Short text"

    def test_empty_string(self):
        result = clean_text_for_speech("", {})
        assert result == ""

    def test_only_code_blocks(self):
        text = "```\nall code\n```"
        result = clean_text_for_speech(text, {})
        # Should have placeholder but no actual code
        assert "all code" not in result


# --- extract_last_assistant_message ---

class TestExtractLastAssistantMessage:

    def _write_jsonl(self, tmp_path, entries):
        """Write JSONL entries to a temp file, return path."""
        path = tmp_path / "transcript.jsonl"
        with open(path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        return str(path)

    def test_single_assistant_message(self, tmp_path):
        entries = [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Hello world"}
            ]}}
        ]
        path = self._write_jsonl(tmp_path, entries)
        result = extract_last_assistant_message(path)
        assert result == "Hello world"

    def test_returns_last_assistant_message(self, tmp_path):
        entries = [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "First response"}
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Second response"}
            ]}},
        ]
        path = self._write_jsonl(tmp_path, entries)
        result = extract_last_assistant_message(path)
        assert result == "Second response"

    def test_skips_tool_use_blocks(self, tmp_path):
        entries = [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Let me check"},
                {"type": "tool_use", "name": "read_file"},
                {"type": "text", "text": "Tool output summary"},
            ]}}
        ]
        path = self._write_jsonl(tmp_path, entries)
        result = extract_last_assistant_message(path)
        assert result == "Let me check"

    def test_includes_tool_results_when_not_skipped(self, tmp_path):
        entries = [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Let me check"},
                {"type": "tool_use", "name": "read_file"},
                {"type": "text", "text": "Tool output summary"},
            ]}}
        ]
        path = self._write_jsonl(tmp_path, entries)
        result = extract_last_assistant_message(path, skip_tool_results=False)
        assert "Let me check" in result
        assert "Tool output summary" in result

    def test_missing_file_returns_empty(self):
        result = extract_last_assistant_message("/nonexistent/path.jsonl")
        assert result == ""

    def test_empty_file(self, tmp_path):
        path = tmp_path / "transcript.jsonl"
        path.write_text("")
        result = extract_last_assistant_message(str(path))
        assert result == ""

    def test_malformed_json_lines_skipped(self, tmp_path):
        path = tmp_path / "transcript.jsonl"
        path.write_text(
            'not valid json\n'
            + json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Valid message"}
            ]}}) + '\n'
        )
        result = extract_last_assistant_message(str(path))
        assert result == "Valid message"

    def test_string_content_blocks(self, tmp_path):
        """Content blocks can be plain strings, not just dicts."""
        entries = [
            {"type": "assistant", "message": {"content": [
                "Plain string content"
            ]}}
        ]
        path = self._write_jsonl(tmp_path, entries)
        result = extract_last_assistant_message(path)
        assert result == "Plain string content"

    def test_ignores_non_assistant_entries(self, tmp_path):
        entries = [
            {"type": "human", "message": {"content": [
                {"type": "text", "text": "User message"}
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Assistant reply"}
            ]}},
        ]
        path = self._write_jsonl(tmp_path, entries)
        result = extract_last_assistant_message(path)
        assert result == "Assistant reply"
```

**Step 2: Run tests to verify they pass**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_text_processing.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/unit/test_text_processing.py
git commit -m "test: add unit tests for text processing (clean_text, extract_message)"
```

---

### Task 3: Unit Tests — Telegram Formatting (afk.py)

**Files:**
- Create: `tests/unit/test_telegram_formatting.py`

**Step 1: Write the tests**

```python
"""Tests for Telegram formatting functions in daemon/afk.py."""

from daemon.afk import _escape_html, _markdown_to_telegram_html


class TestEscapeHtml:

    def test_escapes_ampersand(self):
        assert _escape_html("A & B") == "A &amp; B"

    def test_escapes_angle_brackets(self):
        assert _escape_html("<script>") == "&lt;script&gt;"

    def test_all_special_chars(self):
        assert _escape_html("a & b < c > d") == "a &amp; b &lt; c &gt; d"

    def test_empty_string(self):
        assert _escape_html("") == ""

    def test_no_special_chars(self):
        assert _escape_html("plain text") == "plain text"


class TestMarkdownToTelegramHtml:

    def test_fenced_code_block_with_language(self):
        md = "```python\nprint('hi')\n```"
        result = _markdown_to_telegram_html(md)
        assert '<pre><code class="language-python">' in result
        assert "print(&#x27;hi&#x27;)" in result or "print('hi')" in result

    def test_fenced_code_block_without_language(self):
        md = "```\nsome code\n```"
        result = _markdown_to_telegram_html(md)
        assert "<pre>" in result
        assert "some code" in result

    def test_inline_code(self):
        md = "Use `foo()` here"
        result = _markdown_to_telegram_html(md)
        assert "<code>" in result
        assert "foo()" in result

    def test_bold(self):
        md = "This is **bold** text"
        result = _markdown_to_telegram_html(md)
        assert "<b>bold</b>" in result

    def test_italic(self):
        md = "This is *italic* text"
        result = _markdown_to_telegram_html(md)
        assert "<i>italic</i>" in result

    def test_escapes_html_in_code_blocks(self):
        md = "```\na < b && c > d\n```"
        result = _markdown_to_telegram_html(md)
        assert "&lt;" in result
        assert "&amp;" in result

    def test_empty_string(self):
        result = _markdown_to_telegram_html("")
        assert result == ""

    def test_plain_text_with_html_chars(self):
        md = "Use x < 10 & y > 5"
        result = _markdown_to_telegram_html(md)
        assert "&amp;" in result
        assert "&lt;" in result

    def test_mixed_content(self):
        md = "**Bold** and `code` and *italic*"
        result = _markdown_to_telegram_html(md)
        assert "<b>Bold</b>" in result
        assert "<code>code</code>" in result
        assert "<i>italic</i>" in result
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_telegram_formatting.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/unit/test_telegram_formatting.py
git commit -m "test: add unit tests for Telegram formatting (escape_html, markdown_to_html)"
```

---

### Task 4: Unit Tests — Telegram Keyboards (telegram.py)

**Files:**
- Create: `tests/unit/test_telegram_keyboards.py`

**Step 1: Write the tests**

```python
"""Tests for keyboard builders in daemon/telegram.py."""

from daemon.telegram import make_options_keyboard, make_permission_keyboard


class TestMakeOptionsKeyboard:

    def test_single_option(self):
        opts = [{"label": "Yes", "description": "Accept"}]
        kb = make_options_keyboard(opts)
        assert len(kb["inline_keyboard"]) == 1
        assert kb["inline_keyboard"][0][0]["text"] == "Yes"
        assert kb["inline_keyboard"][0][0]["callback_data"] == "opt:Yes"

    def test_multiple_options(self):
        opts = [
            {"label": "A", "description": "First"},
            {"label": "B", "description": "Second"},
            {"label": "C", "description": "Third"},
        ]
        kb = make_options_keyboard(opts)
        assert len(kb["inline_keyboard"]) == 3
        labels = [row[0]["text"] for row in kb["inline_keyboard"]]
        assert labels == ["A", "B", "C"]

    def test_empty_options(self):
        kb = make_options_keyboard([])
        assert kb["inline_keyboard"] == []

    def test_special_chars_in_label(self):
        opts = [{"label": "Yes & No", "description": "mixed"}]
        kb = make_options_keyboard(opts)
        assert kb["inline_keyboard"][0][0]["text"] == "Yes & No"
        assert kb["inline_keyboard"][0][0]["callback_data"] == "opt:Yes & No"

    def test_missing_label_key(self):
        opts = [{"description": "no label"}]
        kb = make_options_keyboard(opts)
        assert kb["inline_keyboard"][0][0]["text"] == "?"


class TestMakePermissionKeyboard:

    def test_has_three_rows(self):
        kb = make_permission_keyboard()
        assert len(kb["inline_keyboard"]) == 3

    def test_button_labels(self):
        kb = make_permission_keyboard()
        labels = [row[0]["text"] for row in kb["inline_keyboard"]]
        assert "Yes" in labels[0]
        assert "Always" in labels[1].lower() or "always" in labels[1]
        assert "No" in labels[2]

    def test_callback_data(self):
        kb = make_permission_keyboard()
        data = [row[0]["callback_data"] for row in kb["inline_keyboard"]]
        assert data == ["yes", "always", "no"]
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_telegram_keyboards.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/unit/test_telegram_keyboards.py
git commit -m "test: add unit tests for Telegram keyboard builders"
```

---

### Task 5: Unit Tests — Voice Commands (main.py)

**Files:**
- Create: `tests/unit/test_voice_commands.py`

**Step 1: Write the tests**

These tests need a VoiceDaemon-like object with the right attributes but without constructing the real daemon (which loads ML models). We'll build a minimal stub.

```python
"""Tests for voice command recognition in daemon/main.py."""

import os
import sys
from unittest.mock import patch, MagicMock

# We need to mock heavy imports before importing main
# main.py imports sounddevice at module level
sys.modules['sounddevice'] = MagicMock()
sys.modules['daemon.audio'] = MagicMock()
sys.modules['daemon.transcribe'] = MagicMock()
sys.modules['daemon.keyboard'] = MagicMock()
sys.modules['daemon.hotkey'] = MagicMock()
sys.modules['daemon.tts'] = MagicMock()
sys.modules['daemon.overlay'] = MagicMock()
sys.modules['pynput'] = MagicMock()
sys.modules['pynput.keyboard'] = MagicMock()

from daemon.main import VoiceDaemon, _read_mode, _write_mode, SILENT_FLAG, MODE_FILE


class TestHandleVoiceCommand:
    """Test _handle_voice_command method for all known voice commands."""

    @staticmethod
    def _make_daemon():
        """Create a VoiceDaemon with mocked dependencies."""
        with patch.object(VoiceDaemon, '__init__', lambda self: None):
            d = VoiceDaemon()
            # Set up minimal attributes needed by _handle_voice_command
            d.config = MagicMock()
            d.config.afk.voice_commands_activate = ["going afk", "away from keyboard"]
            d.config.afk.voice_commands_deactivate = ["back at keyboard", "i'm back"]
            d.afk = MagicMock()
            return d

    def test_stop_speaking(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", str(tmp_path / ".silent")):
            assert d._handle_voice_command("stop speaking") is True

    def test_stop_talking(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", str(tmp_path / ".silent")):
            assert d._handle_voice_command("stop talking") is True

    def test_start_speaking(self, tmp_path):
        d = self._make_daemon()
        silent = tmp_path / ".silent"
        silent.touch()
        with patch("daemon.main.SILENT_FLAG", str(silent)):
            assert d._handle_voice_command("start speaking") is True
            assert not silent.exists()

    def test_start_talking(self, tmp_path):
        d = self._make_daemon()
        silent = tmp_path / ".silent"
        silent.touch()
        with patch("daemon.main.SILENT_FLAG", str(silent)):
            assert d._handle_voice_command("start talking") is True

    def test_switch_to_narrate(self, tmp_path):
        d = self._make_daemon()
        mode_file = tmp_path / ".mode"
        with patch("daemon.main.MODE_FILE", str(mode_file)):
            with patch("daemon.main._write_mode") as mock_write:
                assert d._handle_voice_command("switch to narrate mode") is True
                mock_write.assert_called_once_with("narrate")

    def test_switch_to_notify(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main._write_mode") as mock_write:
            assert d._handle_voice_command("switch to notify mode") is True
            mock_write.assert_called_once_with("notify")

    def test_switch_to_narration_mode(self, tmp_path):
        d = self._make_daemon()
        with patch("daemon.main._write_mode") as mock_write:
            assert d._handle_voice_command("switch to narration mode") is True
            mock_write.assert_called_once_with("narrate")

    def test_afk_activate_command(self):
        d = self._make_daemon()
        assert d._handle_voice_command("going afk") is True

    def test_afk_deactivate_command(self):
        d = self._make_daemon()
        assert d._handle_voice_command("i'm back") is True

    def test_unrecognised_text_returns_false(self):
        d = self._make_daemon()
        assert d._handle_voice_command("I was speaking about code") is False

    def test_strips_trailing_period(self):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", "/tmp/test_silent"):
            assert d._handle_voice_command("stop speaking.") is True

    def test_case_insensitive(self):
        d = self._make_daemon()
        with patch("daemon.main.SILENT_FLAG", "/tmp/test_silent"):
            assert d._handle_voice_command("Stop Speaking") is True

    def test_empty_string_returns_false(self):
        d = self._make_daemon()
        assert d._handle_voice_command("") is False
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_voice_commands.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/unit/test_voice_commands.py
git commit -m "test: add unit tests for voice command recognition"
```

---

### Task 6: Unit Tests — Config, Hotkey Logic, Audio Utils

**Files:**
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_hotkey_logic.py`
- Create: `tests/unit/test_audio_utils.py`

**Step 1: Write config tests**

```python
"""Tests for configuration loading in daemon/config.py."""

from daemon.config import (
    AfkConfig, AfkTelegramConfig, Config, InputConfig, TranscriptionConfig,
    SpeechConfig, AudioConfig, OverlayConfig, load_config,
)
from unittest.mock import patch, mock_open


class TestAfkConfigPostInit:

    def test_none_telegram_gets_default(self):
        cfg = AfkConfig()
        assert isinstance(cfg.telegram, AfkTelegramConfig)
        assert cfg.telegram.bot_token == ""

    def test_dict_telegram_converted(self):
        cfg = AfkConfig(telegram={"bot_token": "abc", "chat_id": "123"})
        assert isinstance(cfg.telegram, AfkTelegramConfig)
        assert cfg.telegram.bot_token == "abc"
        assert cfg.telegram.chat_id == "123"

    def test_already_instantiated_telegram(self):
        t = AfkTelegramConfig(bot_token="tok", chat_id="id")
        cfg = AfkConfig(telegram=t)
        assert cfg.telegram is t

    def test_default_voice_commands(self):
        cfg = AfkConfig()
        assert "going afk" in cfg.voice_commands_activate
        assert "i'm back" in cfg.voice_commands_deactivate

    def test_custom_voice_commands(self):
        cfg = AfkConfig(
            voice_commands_activate=["bye"],
            voice_commands_deactivate=["hello"],
        )
        assert cfg.voice_commands_activate == ["bye"]
        assert cfg.voice_commands_deactivate == ["hello"]


class TestLoadConfig:

    def test_missing_file_returns_defaults(self):
        with patch("daemon.config.os.path.exists", return_value=False):
            cfg = load_config()
        assert isinstance(cfg, Config)
        assert cfg.input.hotkey == "right_alt"
        assert cfg.speech.mode == "notify"

    def test_valid_yaml_parsed(self):
        yaml_content = """
input:
  hotkey: "f19"
speech:
  mode: "narrate"
  voice: "bf_emma"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.input.hotkey == "f19"
        assert cfg.speech.mode == "narrate"
        assert cfg.speech.voice == "bf_emma"

    def test_empty_yaml_returns_defaults(self):
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="")):
                cfg = load_config()
        assert cfg.input.hotkey == "right_alt"

    def test_strips_removed_notify_model_key(self):
        yaml_content = """
speech:
  notify_model: "old_model"
  mode: "notify"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.speech.mode == "notify"

    def test_partial_config_fills_defaults(self):
        yaml_content = """
input:
  auto_submit: true
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.input.auto_submit is True
        assert cfg.input.hotkey == "right_alt"  # default
        assert cfg.speech.mode == "notify"  # default
```

**Step 2: Write hotkey logic tests**

```python
"""Tests for hotkey cycling logic in daemon/hotkey.py."""

from unittest.mock import MagicMock
import sys

# Mock pynput so we don't need system keyboard access
sys.modules.setdefault('pynput', MagicMock())
sys.modules.setdefault('pynput.keyboard', MagicMock())

from daemon.hotkey import HotkeyListener


class TestCycleLanguage:

    def _make_listener(self, languages):
        """Create a HotkeyListener with mocked callbacks."""
        return HotkeyListener(
            hotkey="right_alt",
            on_press=lambda: None,
            on_release=lambda: None,
            languages=languages,
        )

    def test_single_language_stays_on_index_zero(self):
        hl = self._make_listener(["en"])
        assert hl.active_language == "en"
        hl._cycle_language()
        assert hl.active_language == "en"

    def test_cycles_through_languages(self):
        hl = self._make_listener(["en", "af", "de"])
        assert hl.active_language == "en"
        hl._cycle_language()
        assert hl.active_language == "af"
        hl._cycle_language()
        assert hl.active_language == "de"

    def test_wraps_around(self):
        hl = self._make_listener(["en", "af"])
        hl._cycle_language()  # -> af
        hl._cycle_language()  # -> en (wrap)
        assert hl.active_language == "en"

    def test_calls_on_language_change(self):
        callback = MagicMock()
        hl = HotkeyListener(
            hotkey="right_alt",
            on_press=lambda: None,
            on_release=lambda: None,
            languages=["en", "af"],
            on_language_change=callback,
        )
        hl._cycle_language()
        callback.assert_called_once_with("af")
```

**Step 3: Write audio utils tests**

```python
"""Tests for audio utility functions in daemon/audio.py."""

import numpy as np
from unittest.mock import MagicMock
import sys

# Mock sounddevice (requires PortAudio system library)
sys.modules.setdefault('sounddevice', MagicMock())

from daemon.audio import AudioRecorder


class TestGetDuration:

    def test_normal_audio(self):
        recorder = AudioRecorder(sample_rate=16000)
        audio = np.zeros(16000, dtype=np.float32)  # 1 second
        assert recorder.get_duration(audio) == 1.0

    def test_half_second(self):
        recorder = AudioRecorder(sample_rate=16000)
        audio = np.zeros(8000, dtype=np.float32)
        assert recorder.get_duration(audio) == 0.5

    def test_zero_length(self):
        recorder = AudioRecorder(sample_rate=16000)
        audio = np.array([], dtype=np.float32)
        assert recorder.get_duration(audio) == 0.0

    def test_different_sample_rate(self):
        recorder = AudioRecorder(sample_rate=44100)
        audio = np.zeros(44100, dtype=np.float32)
        assert recorder.get_duration(audio) == 1.0
```

**Step 4: Run all unit tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add tests/unit/test_config.py tests/unit/test_hotkey_logic.py tests/unit/test_audio_utils.py
git commit -m "test: add unit tests for config, hotkey cycling, and audio duration"
```

---

### Task 7: Integration Tests — Config Loading (config.py)

**Files:**
- Create: `tests/integration/test_config.py`

**Step 1: Write the tests**

These tests use real YAML parsing with temp files (not mocked `open()`).

```python
"""Integration tests for config loading with real file I/O."""

import os
import yaml
import pytest
from daemon.config import load_config, CONFIG_PATH
from unittest.mock import patch


class TestLoadConfigWithFiles:

    def test_full_config_roundtrip(self, tmp_path):
        """Write a full config to disk and load it."""
        config_data = {
            "input": {
                "hotkey": "f18",
                "auto_submit": True,
                "min_audio_length": 1.0,
            },
            "transcription": {
                "model": "small.en",
                "language": "en",
                "backend": "faster-whisper",
            },
            "speech": {
                "enabled": False,
                "mode": "narrate",
                "voice": "bf_emma",
                "speed": 1.2,
            },
            "audio": {"sample_rate": 44100},
            "overlay": {"enabled": False, "style": "frosted"},
            "afk": {
                "telegram": {"bot_token": "tok", "chat_id": "123"},
                "hotkey": "left_alt+a",
            },
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        with patch("daemon.config.CONFIG_PATH", str(config_path)):
            cfg = load_config()

        assert cfg.input.hotkey == "f18"
        assert cfg.input.auto_submit is True
        assert cfg.transcription.backend == "faster-whisper"
        assert cfg.speech.voice == "bf_emma"
        assert cfg.speech.speed == 1.2
        assert cfg.audio.sample_rate == 44100
        assert cfg.overlay.style == "frosted"
        assert cfg.afk.telegram.bot_token == "tok"

    def test_empty_file(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")

        with patch("daemon.config.CONFIG_PATH", str(config_path)):
            cfg = load_config()

        # All defaults
        assert cfg.input.hotkey == "right_alt"
        assert cfg.speech.mode == "notify"

    def test_unknown_keys_raise(self, tmp_path):
        """Unknown keys in a section cause TypeError from dataclass init."""
        config_data = {"input": {"hotkey": "f18", "unknown_key": True}}
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        with patch("daemon.config.CONFIG_PATH", str(config_path)):
            with pytest.raises(TypeError):
                load_config()
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/test_config.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_config.py
git commit -m "test: add integration tests for config loading with real YAML files"
```

---

### Task 8: Integration Tests — Cleanup Pipeline (cleanup.py)

**Files:**
- Create: `tests/integration/test_cleanup.py`

**Step 1: Write the tests**

```python
"""Integration tests for transcription cleanup (daemon/cleanup.py)."""

import subprocess
from unittest.mock import patch, MagicMock

from daemon.cleanup import TranscriptionCleaner


class TestCleanupPostProcessing:
    """Test the output post-processing in cleanup() — the pure logic part."""

    def _run_cleanup(self, stdout: str) -> str:
        """Run cleanup with mocked subprocess returning given stdout."""
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = stdout

        with patch("daemon.cleanup.subprocess.run", return_value=mock_result):
            return cleaner.cleanup("input text")

    def test_strips_output_prefix(self):
        result = self._run_cleanup("Output: Hello world")
        assert result == "Hello world"

    def test_strips_output_prefix_case_insensitive(self):
        result = self._run_cleanup("output: Hello world")
        assert result == "Hello world"

    def test_strips_double_quotes(self):
        result = self._run_cleanup('"Hello world"')
        assert result == "Hello world"

    def test_strips_single_quotes(self):
        result = self._run_cleanup("'Hello world'")
        assert result == "Hello world"

    def test_passthrough_normal_text(self):
        result = self._run_cleanup("Hello world")
        assert result == "Hello world"

    def test_empty_response_returns_original(self):
        result = self._run_cleanup("")
        assert result == "input text"

    def test_whitespace_only_returns_original(self):
        result = self._run_cleanup("   \n  ")
        assert result == "input text"


class TestCleanupGracefulDegradation:
    """Test that cleanup() returns original text on any failure."""

    def test_returns_original_on_nonzero_exit(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("daemon.cleanup.subprocess.run", return_value=mock_result):
            assert cleaner.cleanup("original") == "original"

    def test_returns_original_on_timeout(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        with patch("daemon.cleanup.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ollama", 10)):
            assert cleaner.cleanup("original") == "original"

    def test_returns_original_on_exception(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True

        with patch("daemon.cleanup.subprocess.run",
                   side_effect=OSError("command not found")):
            assert cleaner.cleanup("original") == "original"

    def test_skips_when_not_ready(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = False
        assert cleaner.cleanup("original") == "original"

    def test_skips_empty_input(self):
        cleaner = TranscriptionCleaner()
        cleaner._ready = True
        assert cleaner.cleanup("") == ""


class TestEnsureReady:
    """Test ensure_ready() checks with mocked subprocess."""

    def test_ollama_not_installed(self):
        cleaner = TranscriptionCleaner()
        with patch("daemon.cleanup.subprocess.run",
                   side_effect=FileNotFoundError()):
            assert cleaner.ensure_ready() is False

    def test_model_available(self):
        cleaner = TranscriptionCleaner(model_name="qwen2.5:1.5b")

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if cmd[1] == "--version":
                result.stdout = "ollama 0.1.0"
            elif cmd[1] == "list":
                result.stdout = "qwen2.5:1.5b   abc123   1.0 GB"
            return result

        with patch("daemon.cleanup.subprocess.run", side_effect=fake_run):
            assert cleaner.ensure_ready() is True
            assert cleaner._ready is True

    def test_model_missing_triggers_pull(self):
        cleaner = TranscriptionCleaner(model_name="qwen2.5:1.5b")
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.returncode = 0
            if cmd[1] == "--version":
                result.stdout = "ollama 0.1.0"
            elif cmd[1] == "list":
                result.stdout = ""  # model not found
            elif cmd[1] == "pull":
                result.stdout = "success"
            return result

        with patch("daemon.cleanup.subprocess.run", side_effect=fake_run):
            assert cleaner.ensure_ready() is True
        assert call_count == 3  # version + list + pull

    def test_version_check_timeout(self):
        cleaner = TranscriptionCleaner()
        with patch("daemon.cleanup.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ollama", 5)):
            assert cleaner.ensure_ready() is False
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/test_cleanup.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_cleanup.py
git commit -m "test: add integration tests for transcription cleanup pipeline"
```

---

### Task 9: Integration Tests — Control Server (control.py)

**Files:**
- Create: `tests/integration/test_control_server.py`

**Step 1: Write the tests**

```python
"""Integration tests for control server command handling (daemon/control.py)."""

from unittest.mock import MagicMock, patch

from daemon.control import ControlServer


def _make_server():
    """Create a ControlServer with a mocked daemon."""
    daemon = MagicMock()
    daemon.get_mode.return_value = "notify"
    daemon.get_voice_enabled.return_value = True
    daemon.recorder.is_recording = False
    server = ControlServer(daemon)
    return server, daemon


class TestHandleCommand:

    def test_status(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "status"})
        assert resp["daemon"] is True
        assert resp["mode"] == "notify"
        assert resp["voice"] is True
        assert resp["recording"] is False

    def test_set_mode(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "set_mode", "mode": "narrate"})
        assert resp == {"ok": True}
        daemon.set_mode.assert_called_once_with("narrate")

    def test_set_mode_defaults_to_notify(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "set_mode"})
        daemon.set_mode.assert_called_once_with("notify")

    def test_voice_on(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "voice_on"})
        assert resp == {"ok": True}
        daemon.set_voice_enabled.assert_called_once_with(True)

    def test_voice_off(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "voice_off"})
        assert resp == {"ok": True}
        daemon.set_voice_enabled.assert_called_once_with(False)

    def test_reload_config(self):
        server, daemon = _make_server()
        resp = server._handle_command({"cmd": "reload_config"})
        assert resp == {"ok": True}
        daemon.reload_config.assert_called_once()

    def test_stop_triggers_shutdown(self):
        server, daemon = _make_server()
        with patch("daemon.control.threading.Thread") as mock_thread:
            resp = server._handle_command({"cmd": "stop"})
        assert resp == {"ok": True}
        mock_thread.assert_called_once()

    def test_subscribe(self):
        server, _ = _make_server()
        resp = server._handle_command({"cmd": "subscribe"})
        assert resp == {"subscribed": True}

    def test_unknown_command(self):
        server, _ = _make_server()
        resp = server._handle_command({"cmd": "invalid"})
        assert "error" in resp
        assert "unknown" in resp["error"]

    def test_missing_cmd_key(self):
        server, _ = _make_server()
        resp = server._handle_command({})
        assert "error" in resp


class TestEmit:

    def test_sends_to_subscribed_connections(self):
        server, _ = _make_server()
        conn = MagicMock()
        server._event_connections.append(conn)

        server.emit({"event": "test"})
        conn.sendall.assert_called_once()
        sent_data = conn.sendall.call_args[0][0]
        assert b"test" in sent_data

    def test_removes_dead_connections(self):
        server, _ = _make_server()
        dead = MagicMock()
        dead.sendall.side_effect = BrokenPipeError()
        alive = MagicMock()

        server._event_connections = [dead, alive]
        server.emit({"event": "test"})

        assert dead not in server._event_connections
        assert alive in server._event_connections
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/test_control_server.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_control_server.py
git commit -m "test: add integration tests for control server command handling"
```

---

### Task 10: Integration Tests — Telegram Client (telegram.py)

**Files:**
- Create: `tests/integration/test_telegram_client.py`

**Step 1: Write the tests**

```python
"""Integration tests for Telegram client (daemon/telegram.py)."""

from unittest.mock import patch, MagicMock

from daemon.telegram import TelegramClient


def _make_client():
    return TelegramClient(bot_token="test_token", chat_id="12345")


class TestVerify:

    def test_success(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}

        with patch("daemon.telegram.requests.get", return_value=mock_resp) as mock_get:
            assert client.verify() is True
        mock_get.assert_called_once()

    def test_failure_status_code(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.get", return_value=mock_resp):
            assert client.verify() is False

    def test_connection_error(self):
        client = _make_client()
        with patch("daemon.telegram.requests.get",
                   side_effect=ConnectionError()):
            assert client.verify() is False


class TestSendMessage:

    def test_success_returns_message_id(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"message_id": 42},
        }

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.send_message("Hello") == 42

    def test_failure_returns_none(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.send_message("Hello") is None

    def test_includes_reply_markup(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"message_id": 1},
        }

        markup = {"inline_keyboard": [[{"text": "Yes", "callback_data": "y"}]]}
        with patch("daemon.telegram.requests.post", return_value=mock_resp) as mock_post:
            client.send_message("Choose", reply_markup=markup)

        payload = mock_post.call_args[1]["json"]
        assert "reply_markup" in payload

    def test_exception_returns_none(self):
        client = _make_client()
        with patch("daemon.telegram.requests.post",
                   side_effect=ConnectionError()):
            assert client.send_message("Hello") is None


class TestDeleteMessage:

    def test_success(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.delete_message(42) is True

    def test_failure(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.delete_message(42) is False

    def test_exception(self):
        client = _make_client()
        with patch("daemon.telegram.requests.post",
                   side_effect=ConnectionError()):
            assert client.delete_message(42) is False


class TestHandleUpdate:

    def test_routes_callback_to_handler(self):
        client = _make_client()
        handler = MagicMock()
        client._callback_handler = handler

        update = {
            "callback_query": {
                "id": "cb1",
                "data": "yes",
                "message": {
                    "message_id": 10,
                    "chat": {"id": 12345},
                },
            }
        }
        client._handle_update(update)
        handler.assert_called_once_with("cb1", "yes", 10)

    def test_routes_message_to_handler(self):
        client = _make_client()
        handler = MagicMock()
        client._message_handler = handler

        update = {
            "message": {
                "text": "hello",
                "chat": {"id": 12345},
            }
        }
        client._handle_update(update)
        handler.assert_called_once_with("hello")

    def test_ignores_wrong_chat_id_callback(self):
        client = _make_client()
        handler = MagicMock()
        client._callback_handler = handler

        update = {
            "callback_query": {
                "id": "cb1",
                "data": "yes",
                "message": {
                    "message_id": 10,
                    "chat": {"id": 99999},  # wrong
                },
            }
        }
        client._handle_update(update)
        handler.assert_not_called()

    def test_ignores_wrong_chat_id_message(self):
        client = _make_client()
        handler = MagicMock()
        client._message_handler = handler

        update = {
            "message": {
                "text": "hello",
                "chat": {"id": 99999},  # wrong
            }
        }
        client._handle_update(update)
        handler.assert_not_called()

    def test_ignores_empty_message_text(self):
        client = _make_client()
        handler = MagicMock()
        client._message_handler = handler

        update = {
            "message": {
                "text": "",
                "chat": {"id": 12345},
            }
        }
        client._handle_update(update)
        handler.assert_not_called()
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/test_telegram_client.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_telegram_client.py
git commit -m "test: add integration tests for Telegram client"
```

---

### Task 11: Integration Tests — AFK State Machine (afk.py)

**Files:**
- Create: `tests/integration/test_afk_state.py`

**Step 1: Write the tests**

```python
"""Integration tests for AFK state machine (daemon/afk.py)."""

import threading
from unittest.mock import MagicMock, patch

from daemon.afk import AfkManager, PendingRequest, TELEGRAM_MAX_CHARS
from daemon.config import AfkConfig, AfkTelegramConfig, Config, InputConfig, TranscriptionConfig, SpeechConfig, AudioConfig, OverlayConfig


def _make_config(bot_token="tok", chat_id="123"):
    return Config(
        input=InputConfig(),
        transcription=TranscriptionConfig(),
        speech=SpeechConfig(),
        audio=AudioConfig(),
        overlay=OverlayConfig(),
        afk=AfkConfig(
            telegram=AfkTelegramConfig(bot_token=bot_token, chat_id=chat_id),
        ),
    )


def _make_active_manager():
    """Create an AfkManager in active state with mocked Telegram client."""
    cfg = _make_config()
    mgr = AfkManager(cfg)
    mgr._client = MagicMock()
    mgr._client.send_message.return_value = 100  # message ID
    mgr.active = True
    return mgr


class TestAfkManagerState:

    def test_is_configured_with_credentials(self):
        mgr = AfkManager(_make_config())
        assert mgr.is_configured is True

    def test_not_configured_without_credentials(self):
        mgr = AfkManager(_make_config(bot_token="", chat_id=""))
        assert mgr.is_configured is False

    def test_activate_sets_active(self):
        mgr = AfkManager(_make_config())
        mgr._client = MagicMock()
        mgr._client.send_message.return_value = 1

        with patch("daemon.afk.os.makedirs"):
            assert mgr.activate() is True
        assert mgr.active is True

    def test_activate_fails_without_client(self):
        mgr = AfkManager(_make_config())
        assert mgr.activate() is False
        assert mgr.active is False

    def test_deactivate_clears_state(self):
        mgr = _make_active_manager()
        mgr._pending[1] = MagicMock()
        mgr._sent_message_ids = [1, 2, 3]

        mgr.deactivate()

        assert mgr.active is False
        assert len(mgr._pending) == 0
        assert len(mgr._sent_message_ids) == 1  # deactivate sends one message

    def test_deactivate_noop_when_inactive(self):
        mgr = AfkManager(_make_config())
        mgr.deactivate()  # should not raise
        assert mgr.active is False


class TestHandleHookRequest:

    def test_returns_no_wait_when_inactive(self):
        mgr = AfkManager(_make_config())
        resp = mgr.handle_hook_request({"type": "permission"})
        assert resp == {"wait": False}

    def test_context_type_no_wait(self):
        mgr = _make_active_manager()
        resp = mgr.handle_hook_request({
            "session": "test-session",
            "type": "context",
            "context": "Some context",
        })
        assert resp == {"wait": False}

    def test_permission_returns_wait_with_path(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            resp = mgr.handle_hook_request({
                "session": "test-session",
                "type": "permission",
                "prompt": "Run command?",
            })
        assert resp["wait"] is True
        assert "response" in resp["response_path"]

    def test_permission_registers_pending(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            mgr.handle_hook_request({
                "session": "test-session",
                "type": "permission",
                "prompt": "Allow?",
            })
        assert len(mgr._pending) == 1

    def test_ask_user_question_with_options(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            resp = mgr.handle_hook_request({
                "session": "test",
                "type": "ask_user_question",
                "questions": [
                    {
                        "question": "Which approach?",
                        "options": [
                            {"label": "A", "description": "First"},
                            {"label": "B", "description": "Second"},
                        ],
                    }
                ],
            })
        assert resp["wait"] is True

    def test_input_type(self):
        mgr = _make_active_manager()
        with patch("daemon.afk.os.makedirs"):
            resp = mgr.handle_hook_request({
                "session": "test",
                "type": "input",
                "prompt": "Enter name:",
            })
        assert resp["wait"] is True

    def test_context_truncation(self):
        mgr = _make_active_manager()
        long_context = "Line\n" * 2000  # well over TELEGRAM_MAX_CHARS
        resp = mgr.handle_hook_request({
            "session": "test",
            "type": "context",
            "context": long_context,
        })
        # The message sent to Telegram should be truncated
        call_args = mgr._client.send_message.call_args[0][0]
        assert len(call_args) <= TELEGRAM_MAX_CHARS + 500  # header overhead


class TestHandleCallback:

    def test_writes_response_for_pending(self):
        mgr = _make_active_manager()
        pending = PendingRequest("test", "permission", "Allow?", 100,
                                 response_path="/tmp/test_resp")

        mgr._pending[100] = pending

        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_callback("cb1", "yes", 100)

        mock_write.assert_called_once_with("/tmp/test_resp", "yes")
        assert 100 not in mgr._pending

    def test_ignores_unknown_message_id(self):
        mgr = _make_active_manager()
        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_callback("cb1", "yes", 999)
        mock_write.assert_not_called()


class TestHandleMessage:

    def test_afk_command(self):
        mgr = _make_active_manager()
        toggle = MagicMock()
        mgr._on_toggle = toggle
        mgr._handle_message("/afk")
        toggle.assert_called_once()

    def test_back_command_deactivates(self):
        mgr = _make_active_manager()
        toggle = MagicMock()
        mgr._on_toggle = toggle
        mgr._handle_message("/back")
        toggle.assert_called_once()

    def test_status_command(self):
        mgr = _make_active_manager()
        with patch.object(mgr, "handle_status_request") as mock_status:
            mgr._handle_message("/status")
        mock_status.assert_called_once()

    def test_text_routes_to_pending_ask_user(self):
        mgr = _make_active_manager()
        pending = PendingRequest("test", "ask_user_question", "Q?", 100,
                                 response_path="/tmp/resp")
        mgr._pending[100] = pending

        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_message("my answer")

        mock_write.assert_called_once_with("/tmp/resp", "my answer")

    def test_text_routes_to_pending_input_when_no_ask(self):
        mgr = _make_active_manager()
        pending = PendingRequest("test", "input", "Name?", 100,
                                 response_path="/tmp/resp")
        mgr._pending[100] = pending

        with patch.object(mgr, "_write_response") as mock_write:
            mgr._handle_message("Johan")

        mock_write.assert_called_once_with("/tmp/resp", "Johan")

    def test_text_types_into_terminal_when_no_pending(self):
        mgr = _make_active_manager()
        with patch.object(mgr, "_type_into_terminal") as mock_type:
            mgr._handle_message("some text")
        mock_type.assert_called_once_with("some text")

    def test_not_afk_rejects_non_commands(self):
        mgr = AfkManager(_make_config())
        mgr._client = MagicMock()
        mgr._client.send_message.return_value = 1
        mgr.active = False

        mgr._handle_message("hello")
        # Should send "Not in AFK mode" message
        mgr._client.send_message.assert_called_once()
        assert "Not in AFK" in mgr._client.send_message.call_args[0][0]
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/test_afk_state.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_afk_state.py
git commit -m "test: add integration tests for AFK state machine"
```

---

### Task 12: Integration Tests — Hook Utilities (_common.py)

**Files:**
- Create: `tests/integration/test_hooks.py`

**Step 1: Write the tests**

```python
"""Integration tests for hook utilities (hooks/_common.py)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "hooks"))

from unittest.mock import patch, MagicMock

from _common import read_mode, send_to_daemon, wait_for_response


class TestReadMode:

    def test_valid_mode(self, tmp_path):
        mode_file = tmp_path / ".mode"
        mode_file.write_text("narrate")
        with patch("_common.MODE_FILE", str(mode_file)):
            assert read_mode() == "narrate"

    def test_missing_file_returns_empty(self):
        with patch("_common.MODE_FILE", "/nonexistent/.mode"):
            assert read_mode() == ""

    def test_empty_file_returns_empty(self, tmp_path):
        mode_file = tmp_path / ".mode"
        mode_file.write_text("")
        with patch("_common.MODE_FILE", str(mode_file)):
            assert read_mode() == ""


class TestSendToDaemon:

    def test_connection_refused_returns_none(self):
        with patch("_common.TTS_SOCK_PATH", "/nonexistent/sock"):
            result = send_to_daemon({"cmd": "status"})
        assert result is None


class TestWaitForResponse:

    def test_returns_response_when_file_appears(self, tmp_path):
        resp_file = tmp_path / "response"
        resp_file.write_text("yes")

        result = wait_for_response(str(resp_file))
        assert result == "yes"
        assert not resp_file.exists()  # file removed after read

    def test_timeout_returns_none(self, tmp_path):
        with patch("_common.AFK_RESPONSE_TIMEOUT", 0.1):
            with patch("_common.time.sleep"):  # don't actually sleep
                result = wait_for_response(str(tmp_path / "never"))
        assert result is None
```

**Step 2: Run tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/test_hooks.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_hooks.py
git commit -m "test: add integration tests for hook utilities"
```

---

### Task 13: Full Test Suite Run and Final Commit

**Step 1: Run the entire test suite**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (should be ~40-45 tests)

**Step 2: Run with coverage if available**

Run: `~/.claude-voice/venv/bin/pip install pytest-cov`
Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v --cov=daemon --cov=hooks --cov-report=term-missing --tb=short`

Review coverage output to confirm the targeted functions are covered.

**Step 3: Commit any final adjustments**

If any tests needed adjustments during the run, commit those fixes:

```bash
git add -A tests/
git commit -m "test: finalize test suite, all tests passing"
```
