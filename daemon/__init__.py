"""Claude Voice daemon package."""

import subprocess


def kill_playback_proc(proc: subprocess.Popen | None) -> bool:
    """Kill a playback subprocess if running. Returns True if it was active."""
    if proc is not None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return True
    return False
