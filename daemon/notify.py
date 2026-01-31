"""Notify mode: classify Claude responses and play status phrases."""

import os
import subprocess

# Categories
PERMISSION = "permission"
DONE = "done"


def classify(text: str) -> str:
    """Classify a Claude response."""
    return DONE


# Phrase playback

_DEFAULT_PHRASES_DIR = os.path.join(os.path.dirname(__file__), "notify_phrases")
_CACHE_DIR = os.path.expanduser("~/.claude-voice/notify_cache")
_CACHE_META = os.path.join(_CACHE_DIR, "meta.yaml")

_playback_proc = None


def _get_phrase_path(category: str, config_phrases: dict | None) -> str:
    """Get the wav file path for a category, respecting custom overrides."""
    from daemon.config import DEFAULT_NOTIFY_PHRASES

    custom_text = None
    if config_phrases and category in config_phrases:
        default_text = DEFAULT_NOTIFY_PHRASES[category]
        if config_phrases[category] != default_text:
            custom_text = config_phrases[category]

    if custom_text:
        # Use cached custom file
        cached = os.path.join(_CACHE_DIR, f"{category}.wav")
        if os.path.exists(cached):
            return cached
        # Fallback to default if cache missing (will be regenerated on next startup)
        return os.path.join(_DEFAULT_PHRASES_DIR, f"{category}.wav")

    return os.path.join(_DEFAULT_PHRASES_DIR, f"{category}.wav")


def play_phrase(category: str, config_phrases: dict | None = None) -> None:
    """Play the notification phrase for a category."""
    global _playback_proc
    path = _get_phrase_path(category, config_phrases)

    if not os.path.exists(path):
        print(f"Notify: missing phrase file {path}")
        return

    try:
        _playback_proc = subprocess.Popen(["afplay", path])
        _playback_proc.wait()
        _playback_proc = None
    except Exception as e:
        print(f"Notify playback error: {e}")


def stop_playback() -> bool:
    """Stop current notification playback. Returns True if was playing."""
    global _playback_proc
    from daemon import kill_playback_proc
    was_active = kill_playback_proc(_playback_proc)
    _playback_proc = None
    return was_active


def regenerate_custom_phrases(
    config_phrases: dict | None,
    voice: str = "af_heart",
    speed: float = 1.0,
    lang_code: str = "a",
    interactive: bool = False,
) -> None:
    """Regenerate custom notification phrases with Kokoro TTS.

    Only regenerates phrases whose text differs from the defaults.
    Checks voice change and prompts/auto-regenerates as needed.
    """
    import yaml
    from daemon.config import DEFAULT_NOTIFY_PHRASES

    if not config_phrases:
        return

    # Determine which phrases are custom
    custom = {}
    for cat, text in config_phrases.items():
        if cat in DEFAULT_NOTIFY_PHRASES and text != DEFAULT_NOTIFY_PHRASES[cat]:
            custom[cat] = text

    if not custom:
        # All match defaults — clean up any stale cache
        if os.path.exists(_CACHE_DIR):
            import shutil
            shutil.rmtree(_CACHE_DIR)
        return

    # Check if voice has changed
    os.makedirs(_CACHE_DIR, exist_ok=True)
    prev_voice = None
    if os.path.exists(_CACHE_META):
        with open(_CACHE_META) as f:
            meta = yaml.safe_load(f) or {}
            prev_voice = meta.get("voice")

    voice_changed = prev_voice is not None and prev_voice != voice

    # Check which phrases need regeneration
    needs_regen = {}
    for cat, text in custom.items():
        cached = os.path.join(_CACHE_DIR, f"{cat}.wav")
        if not os.path.exists(cached) or voice_changed:
            needs_regen[cat] = text

    if not needs_regen:
        return

    # If voice changed, ask user in interactive mode
    if voice_changed and interactive:
        answer = input(
            f'Voice changed to "{voice}". Regenerate notify phrases? [Y/n] '
        ).strip().lower()
        if answer in ("n", "no"):
            # Update meta so we don't ask again
            with open(_CACHE_META, "w") as f:
                yaml.dump({"voice": voice}, f)
            return

    # Generate with Kokoro
    print("Generating custom notification phrases...")
    try:
        import numpy as np
        import soundfile as sf
        from mlx_audio.tts import load
        import mlx.core as mx

        model = load("mlx-community/Kokoro-82M-bf16")

        for cat, text in needs_regen.items():
            chunks = []
            for result in model.generate(text, voice=voice, speed=speed, lang_code=lang_code):
                chunks.append(result.audio)
            audio = mx.concatenate(chunks)
            audio_np = np.array(audio, dtype=np.float32)
            out_path = os.path.join(_CACHE_DIR, f"{cat}.wav")
            sf.write(out_path, audio_np, 24000)
            print(f'  Generated: {cat} -> "{text}"')

        # Update meta
        with open(_CACHE_META, "w") as f:
            yaml.dump({"voice": voice}, f)

        print("Custom notification phrases ready.")
    except Exception as e:
        print(f"Failed to generate custom phrases: {e}")
        print("Using default phrases as fallback.")

    # Clean up cached files for phrases that are back to default
    for cat in DEFAULT_NOTIFY_PHRASES:
        if cat not in custom:
            cached = os.path.join(_CACHE_DIR, f"{cat}.wav")
            if os.path.exists(cached):
                os.remove(cached)