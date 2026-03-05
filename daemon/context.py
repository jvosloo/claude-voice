"""Context-aware text insertion using macOS Accessibility APIs.

Reads text surrounding the cursor to adjust capitalization, spacing,
and punctuation so dictated text fits naturally at the insertion point.
"""

import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class InsertionContext:
    """Snapshot of text surrounding the cursor at insertion time."""
    text_before: str  # ~50 chars before cursor
    text_after: str   # ~10 chars after cursor
    bundle_id: str    # App bundle identifier
    is_password: bool # AXSecureTextField


def get_insertion_context() -> Optional[InsertionContext]:
    """Read text around the cursor via macOS Accessibility APIs.

    Returns None if any AX call fails — caller should fall back to
    simple text + space insertion.
    """
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide,
            AXUIElementCopyAttributeValue,
            AXUIElementCopyParameterizedAttributeValue,
            kAXFocusedUIElementAttribute,
            kAXSelectedTextRangeAttribute,
            kAXStringForRangeParameterizedAttribute,
            kAXRoleAttribute,
            kAXSubroleAttribute,
        )
        from ApplicationServices import AXValueCreate, AXValueGetValue
        from AppKit import NSWorkspace
        import CoreFoundation
    except ImportError:
        return None

    try:
        # Get focused UI element
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None
        )
        if err != 0 or focused is None:
            return None

        # Check for password field
        _, subrole = AXUIElementCopyAttributeValue(
            focused, kAXSubroleAttribute, None
        )
        is_password = subrole == "AXSecureTextField"

        # Get app bundle ID
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        bundle_id = app.bundleIdentifier() if app else ""

        # Password fields get passthrough (no context reading)
        if is_password:
            return InsertionContext(
                text_before="",
                text_after="",
                bundle_id=bundle_id or "",
                is_password=True,
            )

        # Get cursor position (selected text range)
        err, range_value = AXUIElementCopyAttributeValue(
            focused, kAXSelectedTextRangeAttribute, None
        )
        if err != 0 or range_value is None:
            return None

        # Extract CFRange as (location, length) tuple
        range_tuple = AXValueGetValue(range_value, CoreFoundation.kAXValueTypeCFRange, None)
        if range_tuple is None:
            return None
        cursor_pos, _ = range_tuple

        # Read text before cursor (up to 50 chars)
        before_start = max(0, cursor_pos - 50)
        before_len = cursor_pos - before_start
        if before_len > 0:
            before_range = AXValueCreate(
                CoreFoundation.kAXValueTypeCFRange,
                (before_start, before_len),
            )
            err, text_before = AXUIElementCopyParameterizedAttributeValue(
                focused, kAXStringForRangeParameterizedAttribute,
                before_range, None,
            )
            if err != 0:
                text_before = ""
        else:
            text_before = ""

        # Read text after cursor (up to 10 chars)
        after_range = AXValueCreate(
            CoreFoundation.kAXValueTypeCFRange,
            (cursor_pos, 10),
        )
        err, text_after = AXUIElementCopyParameterizedAttributeValue(
            focused, kAXStringForRangeParameterizedAttribute,
            after_range, None,
        )
        if err != 0:
            text_after = ""

        return InsertionContext(
            text_before=text_before or "",
            text_after=text_after or "",
            bundle_id=bundle_id or "",
            is_password=is_password,
        )

    except Exception:
        return None


def adjust_text_for_context(text: str, ctx: Optional[InsertionContext]) -> str:
    """Adjust transcribed text based on insertion context.

    If ctx is None (AX failure) or app is passthrough, returns text + " "
    (current behavior).
    """
    if not text:
        return text

    if ctx is None:
        return text + " "

    # Passthrough for password fields
    if ctx.is_password:
        return text + " "

    before = ctx.text_before
    after = ctx.text_after

    # --- Capitalization ---
    empty_or_after_sentence_end = (
        not before
        or re.search(r'[.!?]\s*$', before)
    )

    if empty_or_after_sentence_end:
        # Capitalize first letter
        text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
    elif re.search(r'\w$', before):
        # Mid-sentence after a word char → lowercase first letter
        text = text[0].lower() + text[1:] if len(text) > 1 else text.lower()

    # --- Trailing period ---
    # Strip trailing period when mid-sentence (not at end of field / before newline)
    if not empty_or_after_sentence_end and text.endswith('.'):
        text = text[:-1]

    # --- Leading space ---
    if not before or before[-1] in (' ', '\t', '\n'):
        # Already has whitespace or empty field — no leading space
        pass
    else:
        text = " " + text

    # --- Trailing space ---
    if after and after[0] in (' ', '.', ',', ';', ':', '!', '?', '\n'):
        # Already has space or punctuation after cursor — no trailing space
        pass
    else:
        text = text + " "

    return text
