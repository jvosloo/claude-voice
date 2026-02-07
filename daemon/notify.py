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
    engine: str = "kokoro",
    openai_api_key: str = "",
    openai_model: str = "tts-1",
    interactive: bool = False,
) -> None:
    """Regenerate notification phrases with the configured TTS engine.

    Regenerates all phrases (defaults + custom overrides) when the voice,
    speed, lang_code, or engine changes. Custom phrase text changes also
    trigger regeneration for those phrases.
    """
    import yaml
    from daemon.config import DEFAULT_NOTIFY_PHRASES, NOTIFY_PHRASES_BY_LANG

    # Build the full phrase map: translated defaults for lang_code, then custom overrides
    all_phrases = dict(DEFAULT_NOTIFY_PHRASES)
    if lang_code in NOTIFY_PHRASES_BY_LANG:
        all_phrases.update(NOTIFY_PHRASES_BY_LANG[lang_code])
    if config_phrases:
        all_phrases.update(config_phrases)

    # Check cached voice/speed/lang_code/engine
    os.makedirs(_CACHE_DIR, exist_ok=True)
    prev_meta = {}
    if os.path.exists(_CACHE_META):
        with open(_CACHE_META) as f:
            prev_meta = yaml.safe_load(f) or {}

    voice_key = f"{engine}/{voice}/{speed}/{lang_code}"
    prev_voice_key = "{}/{}/{}/{}".format(
        prev_meta.get("engine", ""),
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

    meta = {"engine": engine, "voice": voice, "speed": speed, "lang_code": lang_code, "phrases": dict(all_phrases)}

    # If voice changed, ask user in interactive mode
    if voice_changed and interactive:
        answer = input(
            f'Voice changed to "{voice}". Regenerate notify phrases? [Y/n] (default: Y) '
        ).strip().lower()
        if answer in ("n", "no"):
            # Update meta so we don't ask again
            with open(_CACHE_META, "w") as f:
                yaml.dump(meta, f)
            return

    print("Generating notification phrases...")
    try:
        if engine == "openai":
            _regen_openai(needs_regen, voice, speed, openai_api_key, openai_model)
        else:
            _regen_kokoro(needs_regen, voice, speed, lang_code)

        # Update meta
        with open(_CACHE_META, "w") as f:
            yaml.dump(meta, f)

        print("Notification phrases ready.")
    except Exception as e:
        print(f"Failed to generate phrases: {e}")
        print("Using default phrases as fallback.")


def _regen_kokoro(needs_regen: dict, voice: str, speed: float, lang_code: str) -> None:
    """Generate phrases with local Kokoro TTS."""
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


def _regen_openai(needs_regen: dict, voice: str, speed: float, api_key: str, model: str) -> None:
    """Generate phrases with OpenAI TTS API."""
    import requests
    import tempfile

    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ValueError("No OpenAI API key configured")

    for cat, text in needs_regen.items():
        response = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "input": text,
                "voice": voice,
                "speed": speed,
                "response_format": "wav",
            },
            timeout=30,
        )
        if not response.ok:
            detail = ""
            try:
                body = response.json()
                detail = body.get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise RuntimeError(f"OpenAI TTS API error (HTTP {response.status_code}): {detail}")
        out_path = os.path.join(_CACHE_DIR, f"{cat}.wav")
        # Atomic write: temp file + rename (prevents play_phrase reading partial data)
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", dir=_CACHE_DIR)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(response.content)
            os.rename(tmp_path, out_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        print(f'  Generated: {cat} -> "{text}"')
