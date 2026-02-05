"""Notify mode: classify Claude responses and play status phrases."""

import os
import subprocess
import threading

# Categories
PERMISSION = "permission"
DONE = "done"
QUESTION = "question"


def classify(text: str) -> str:
    """Classify a Claude response."""
    return DONE


# Phrase playback

_DEFAULT_PHRASES_DIR = os.path.join(os.path.dirname(__file__), "notify_phrases")
_CACHE_DIR = os.path.expanduser("~/.claude-voice/notify_cache")
_CACHE_META = os.path.join(_CACHE_DIR, "meta.yaml")

_playback_proc = None
_playback_lock = threading.Lock()


def _get_phrase_path(category: str, config_phrases: dict | None) -> str:
    """Get the wav file path for a category, preferring cached (voice-matched) versions."""
    # Always prefer cached version (regenerated to match current voice)
    cached = os.path.join(_CACHE_DIR, f"{category}.wav")
    if os.path.exists(cached):
        return cached

    # Fallback to shipped default
    return os.path.join(_DEFAULT_PHRASES_DIR, f"{category}.wav")


def play_phrase(category: str, config_phrases: dict | None = None) -> None:
    """Play the notification phrase for a category."""
    global _playback_proc
    path = _get_phrase_path(category, config_phrases)

    if not os.path.exists(path):
        print(f"Notify: missing phrase file {path}")
        return

    try:
        proc = subprocess.Popen(["afplay", path])
        with _playback_lock:
            _playback_proc = proc
        proc.wait()
        with _playback_lock:
            _playback_proc = None
    except Exception as e:
        print(f"Notify playback error: {e}")


def stop_playback() -> bool:
    """Stop current notification playback. Returns True if was playing."""
    global _playback_proc
    from daemon import kill_playback_proc
    with _playback_lock:
        proc = _playback_proc
        _playback_proc = None
    return kill_playback_proc(proc)


def regenerate_custom_phrases(
    config_phrases: dict | None,
    voice: str = "af_heart",
    speed: float = 1.0,
    lang_code: str = "a",
    interactive: bool = False,
) -> None:
    """Regenerate notification phrases with Kokoro TTS.

    Regenerates all phrases (defaults + custom overrides) when the voice,
    speed, or lang_code changes. Custom phrase text changes also trigger
    regeneration for those phrases.
    """
    import yaml
    from daemon.config import DEFAULT_NOTIFY_PHRASES, NOTIFY_PHRASES_BY_LANG

    # Build the full phrase map: translated defaults for lang_code, then custom overrides
    all_phrases = dict(DEFAULT_NOTIFY_PHRASES)
    if lang_code in NOTIFY_PHRASES_BY_LANG:
        all_phrases.update(NOTIFY_PHRASES_BY_LANG[lang_code])
    if config_phrases:
        all_phrases.update(config_phrases)

    # Check cached voice/speed/lang_code
    os.makedirs(_CACHE_DIR, exist_ok=True)
    prev_meta = {}
    if os.path.exists(_CACHE_META):
        with open(_CACHE_META) as f:
            prev_meta = yaml.safe_load(f) or {}

    voice_key = f"{voice}/{speed}/{lang_code}"
    prev_voice_key = "{}/{}/{}".format(
        prev_meta.get("voice", ""),
        prev_meta.get("speed", ""),
        prev_meta.get("lang_code", ""),
    )
    voice_changed = prev_voice_key != voice_key

    # Determine which phrases need regeneration
    prev_phrases = prev_meta.get("phrases", {})
    needs_regen = {}
    for cat, text in all_phrases.items():
        cached = os.path.join(_CACHE_DIR, f"{cat}.wav")
        text_changed = prev_phrases.get(cat) != text
        if not os.path.exists(cached) or voice_changed or text_changed:
            needs_regen[cat] = text

    if not needs_regen:
        return

    # If voice changed, ask user in interactive mode
    if voice_changed and interactive:
        answer = input(
            f'Voice changed to "{voice}". Regenerate notify phrases? [Y/n] (default: Y) '
        ).strip().lower()
        if answer in ("n", "no"):
            # Update meta so we don't ask again
            with open(_CACHE_META, "w") as f:
                yaml.dump({"voice": voice, "speed": speed, "lang_code": lang_code, "phrases": dict(all_phrases)}, f)
            return

    # Generate with Kokoro
    print("Generating notification phrases...")
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
            from daemon.tts import SAMPLE_RATE
            sf.write(out_path, audio_np, SAMPLE_RATE)
            print(f'  Generated: {cat} -> "{text}"')

        # Update meta
        with open(_CACHE_META, "w") as f:
            yaml.dump({"voice": voice, "speed": speed, "lang_code": lang_code, "phrases": dict(all_phrases)}, f)

        print("Notification phrases ready.")
    except Exception as e:
        print(f"Failed to generate phrases: {e}")
        print("Using default phrases as fallback.")
