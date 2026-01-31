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
        assert "always" in labels[1].lower()
        assert "No" in labels[2]

    def test_callback_data(self):
        kb = make_permission_keyboard()
        data = [row[0]["callback_data"] for row in kb["inline_keyboard"]]
        assert data == ["yes", "always", "no"]
