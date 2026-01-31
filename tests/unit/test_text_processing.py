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
