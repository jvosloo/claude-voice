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
