"""Background helper: waits for an AFK response file, then selects the option
or types a free-text answer via the 'Other' path."""

import json
import os
import sys
import time

AFK_RESPONSE_TIMEOUT = 600
ASK_USER_FLAG = os.path.expanduser("/tmp/claude-voice/.ask_user_active")
DEBUG_LOG = os.path.expanduser("/tmp/claude-voice/ask-user-debug.log")


def clear_flag() -> None:
    """Remove the ask_user_active flag."""
    try:
        os.remove(ASK_USER_FLAG)
    except FileNotFoundError:
        pass


def debug(msg: str) -> None:
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} [typer] {msg}\n")
    except Exception:
        pass


def wait_for_response(response_path: str) -> str | None:
    deadline = time.time() + AFK_RESPONSE_TIMEOUT
    while time.time() < deadline:
        if os.path.exists(response_path):
            try:
                with open(response_path) as f:
                    response = f.read().strip()
                os.remove(response_path)
                return response
            except Exception:
                pass
        time.sleep(1)
    return None


def select_option(index: int) -> None:
    """Navigate a TUI picker: press Down arrow `index` times, then Enter."""
    from pynput.keyboard import Controller, Key
    kb = Controller()
    time.sleep(0.5)  # Wait for the picker to render
    for _ in range(index):
        kb.press(Key.down)
        kb.release(Key.down)
        time.sleep(0.05)
    time.sleep(0.1)
    kb.press(Key.enter)
    kb.release(Key.enter)


def type_free_text(text: str, num_options: int) -> None:
    """Select 'Other' in the TUI picker, then type free-text answer.

    'Other' is the last item in the picker, after all options.
    """
    from pynput.keyboard import Controller, Key
    kb = Controller()
    time.sleep(0.5)  # Wait for the picker to render

    # Navigate to "Other" (after all options)
    for _ in range(num_options):
        kb.press(Key.down)
        kb.release(Key.down)
        time.sleep(0.05)
    time.sleep(0.1)
    kb.press(Key.enter)
    kb.release(Key.enter)

    # Wait for the text input to appear
    time.sleep(0.5)

    # Type the free-text answer
    for char in text:
        kb.type(char)
        time.sleep(0.01)
    time.sleep(0.1)
    kb.press(Key.enter)
    kb.release(Key.enter)


def main():
    if len(sys.argv) < 3:
        debug("Usage: _type_answer.py <response_path> <options_json>")
        return

    response_path = sys.argv[1]
    try:
        options = json.loads(sys.argv[2])
    except json.JSONDecodeError:
        debug("Failed to parse options JSON")
        clear_flag()
        return

    try:
        debug(f"Waiting for response at {response_path}")
        debug(f"Options: {[o.get('label') for o in options]}")

        answer = wait_for_response(response_path)
        if not answer:
            debug("Timed out waiting for response")
            return

        debug(f"Got answer: {answer}")

        # Handle skip — user tapped "Skip / Other" button, let them answer locally
        if answer in ("opt:__other__", "__other__"):
            debug("User chose Skip/Other button, not acting")
            return

        # Button press: "opt:<label>"
        if answer.startswith("opt:"):
            selected = answer[4:]
            for i, opt in enumerate(options):
                if opt.get("label") == selected:
                    debug(f"Selecting option {i}: {selected}")
                    select_option(i)
                    debug("Done selecting")
                    return
            debug(f"Could not find option matching '{selected}', skipping")
            return

        # Free-text reply from Telegram (no "opt:" prefix)
        debug(f"Free-text answer: {answer}")
        type_free_text(answer, len(options))
        debug("Done typing free-text")
    finally:
        clear_flag()


if __name__ == "__main__":
    main()
