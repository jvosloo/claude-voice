"""Unit tests for permission-request.py hook — extract_tool_detail()."""

import importlib
import os
import sys

# Import the hook script as a module (it uses polyglot bash/python shebang)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "hooks"))

# Import using importlib since filename has hyphens
_spec = importlib.util.spec_from_file_location(
    "permission_request",
    os.path.join(os.path.dirname(__file__), "..", "..", "hooks", "permission-request.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
extract_tool_detail = _mod.extract_tool_detail
MAX_DETAIL_LENGTH = _mod.MAX_DETAIL_LENGTH


class TestExtractToolDetail:
    """Test extract_tool_detail with various tool types."""

    def test_bash_command(self):
        result = extract_tool_detail({
            "tool_name": "Bash",
            "tool_input": {"command": "cat /etc/hosts | head -3"},
        })
        assert result == "Bash: cat /etc/hosts | head -3"

    def test_read_file_path(self):
        result = extract_tool_detail({
            "tool_name": "Read",
            "tool_input": {"file_path": "/Users/me/project/main.py"},
        })
        assert result == "Read: /Users/me/project/main.py"

    def test_write_file_path(self):
        result = extract_tool_detail({
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/output.txt", "content": "hello"},
        })
        assert result == "Write: /tmp/output.txt"

    def test_edit_file_path(self):
        result = extract_tool_detail({
            "tool_name": "Edit",
            "tool_input": {"file_path": "/src/app.py", "old_string": "a", "new_string": "b"},
        })
        assert result == "Edit: /src/app.py"

    def test_grep_pattern(self):
        result = extract_tool_detail({
            "tool_name": "Grep",
            "tool_input": {"pattern": "def main", "path": "/src"},
        })
        assert result == "Grep: def main"

    def test_glob_pattern(self):
        result = extract_tool_detail({
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py"},
        })
        assert result == "Glob: **/*.py"

    def test_unknown_tool_uses_str(self):
        result = extract_tool_detail({
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://example.com"},
        })
        assert result.startswith("WebFetch: ")
        assert "example.com" in result

    def test_no_tool_name(self):
        result = extract_tool_detail({
            "tool_input": {"command": "ls -la"},
        })
        # No tool_name → just the detail string
        assert "command" in result
        assert "ls -la" in result

    def test_empty_input(self):
        result = extract_tool_detail({})
        assert result == "{}"

    def test_non_dict_tool_input(self):
        result = extract_tool_detail({
            "tool_name": "Bash",
            "tool_input": "raw string input",
        })
        assert result == "Bash: raw string input"

    def test_long_command_truncated(self):
        long_cmd = "x" * 300
        result = extract_tool_detail({
            "tool_name": "Bash",
            "tool_input": {"command": long_cmd},
        })
        assert len(result) <= len("Bash: ") + MAX_DETAIL_LENGTH + len("…")
        assert result.endswith("…")

    def test_missing_expected_key_falls_back(self):
        """Bash tool_input without 'command' key falls back to str(tool_input)."""
        result = extract_tool_detail({
            "tool_name": "Bash",
            "tool_input": {"something_else": "value"},
        })
        assert result.startswith("Bash: ")
        assert "something_else" in result
