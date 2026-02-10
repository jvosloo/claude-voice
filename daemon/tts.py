"""TTS engine backends: Kokoro (local) and OpenAI (cloud)."""

import logging
import os
import subprocess
import tempfile
import threading

# Suppress phonemizer "words count mismatch" warnings (harmless espeak quirk)
logging.getLogger("phonemizer").setLevel(logging.ERROR)

KOKORO_MODEL = "mlx-community/Kokoro-82M-bf16"
SAMPLE_RATE = 24000


class KokoroTTSEngine:
    """Kokoro text-to-speech engine. Lazy-loads model on first use."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._playback_proc = None

    def _ensure_model(self):
        """Load the Kokoro model if not already loaded."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            print("Loading Kokoro TTS model (first time may download ~360MB)...")
            from mlx_audio.tts import load
            self._model = load(KOKORO_MODEL)
            # Warm up: first generate creates the KokoroPipeline (which prints to stdout)
            for _ in self._model.generate(".", voice="af_heart", lang_code="a"):
                pass
            print("Kokoro TTS model loaded.")

    def speak(self, text: str, voice: str = "af_heart", speed: float = 1.0, lang_code: str = "a") -> None:
        """Generate speech and play it.

        Args:
            text: Text to speak.
            voice: Kokoro voice ID (e.g., af_heart, bm_daniel).
            speed: Playback speed multiplier.
            lang_code: Language code (a=American, b=British, j=Japanese, etc.).
        """
        if not text:
            return

        self._ensure_model()

        try:
            import soundfile as sf

            # Generate audio chunks and concatenate
            audio_chunks = []
            for result in self._model.generate(text, voice=voice, speed=speed, lang_code=lang_code):
                audio_chunks.append(result.audio)

            if not audio_chunks:
                return

            import numpy as np
            # mlx arrays need to be converted to numpy for soundfile
            import mlx.core as mx
            audio = mx.concatenate(audio_chunks)
            audio_np = np.array(audio, dtype=np.float32)

            # Write to temp WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name

            sf.write(tmp_path, audio_np, SAMPLE_RATE)

            try:
                # Play audio
                proc = subprocess.Popen(['afplay', tmp_path])
                with self._lock:
                    self._playback_proc = proc
                proc.wait()
                with self._lock:
                    self._playback_proc = None
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except Exception as e:
            print(f"TTS error: {e}")

    def stop_playback(self) -> bool:
        """Stop current audio playback. Returns True if playback was active."""
        from daemon import kill_playback_proc
        with self._lock:
            proc = self._playback_proc
            self._playback_proc = None
        return kill_playback_proc(proc)


# Backward-compat alias
TTSEngine = KokoroTTSEngine


class OpenAITTSEngine:
    """OpenAI cloud text-to-speech engine."""

    def __init__(self, api_key: str = "", model: str = "tts-1"):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._lock = threading.Lock()
        self._playback_proc = None
        self._error_active = False
        self._emit = None

    def set_emitter(self, fn):
        """Wire up the event callback for error reporting."""
        self._emit = fn

    def _report_error(self, message: str, code: str):
        """Emit an error event (deduplicated — only on first failure)."""
        if not self._error_active:
            self._error_active = True
            if self._emit:
                self._emit({"event": "error", "source": "openai_tts", "message": message, "code": code})

    def _clear_error(self):
        """Emit an error_cleared event (only if currently in error state)."""
        if self._error_active:
            self._error_active = False
            if self._emit:
                self._emit({"event": "error_cleared", "source": "openai_tts"})

    def _ensure_model(self):
        """No-op — no local model to load."""
        pass

    def speak(self, text: str, voice: str = "af_heart", speed: float = 1.0, lang_code: str = "a") -> None:
        """Generate speech via OpenAI API and play it.

        Args:
            text: Text to speak.
            voice: OpenAI voice ID (alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer).
            speed: Playback speed multiplier (0.25 to 4.0).
            lang_code: Ignored (OpenAI auto-detects language).
        """
        if not text:
            return

        if not self._api_key:
            print("OpenAI TTS: no API key configured (set speech.openai_api_key or OPENAI_API_KEY env var)")
            self._report_error("No OpenAI API key configured", "no_api_key")
            return

        tmp_path = None
        try:
            import requests

            response = requests.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                },
                json={
                    "model": self._model,
                    "input": text,
                    "voice": voice,
                    "speed": speed,
                    "response_format": "wav",
                },
                timeout=30,
            )
            response.raise_for_status()

            # Write to temp WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = tmp.name

            proc = subprocess.Popen(['afplay', tmp_path])
            with self._lock:
                self._playback_proc = proc
            proc.wait()
            with self._lock:
                self._playback_proc = None

            self._clear_error()

        except requests.Timeout:
            print("OpenAI TTS error: request timed out (30s)")
            self._report_error("Cannot reach OpenAI API", "network_error")
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            detail = ""
            if e.response is not None:
                try:
                    body = e.response.json()
                    detail = body.get("error", {}).get("message", e.response.text)
                except Exception:
                    detail = e.response.text
            if status == 401:
                print(f"OpenAI TTS error: invalid API key (HTTP 401): {detail}")
                self._report_error("Invalid OpenAI API key", "invalid_key")
            elif status == 429:
                print(f"OpenAI TTS error: rejected (HTTP 429): {detail}")
                body_text = e.response.text if e.response is not None else ""
                if "insufficient_quota" in body_text:
                    self._report_error("Insufficient credits \u2014 check OpenAI billing", "insufficient_quota")
                else:
                    self._report_error("OpenAI rate limited", "rate_limited")
            else:
                print(f"OpenAI TTS error: HTTP {status}: {detail}")
                self._report_error(f"OpenAI TTS error: HTTP {status}", "unknown")
        except requests.ConnectionError:
            print("OpenAI TTS error: cannot reach api.openai.com")
            self._report_error("Cannot reach OpenAI API", "network_error")
        except Exception as e:
            print(f"OpenAI TTS error: {type(e).__name__}: {e}")
            self._report_error(f"OpenAI TTS error: {e}", "unknown")
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def stop_playback(self) -> bool:
        """Stop current audio playback. Returns True if playback was active."""
        from daemon import kill_playback_proc
        with self._lock:
            proc = self._playback_proc
            self._playback_proc = None
        return kill_playback_proc(proc)


def create_tts_engine(engine: str = "kokoro", **kwargs):
    """Factory: create the appropriate TTS engine.

    Args:
        engine: "kokoro" or "openai"
        **kwargs: Passed to engine constructor (api_key, model for OpenAI)
    """
    if engine == "openai":
        return OpenAITTSEngine(
            api_key=kwargs.get("api_key", ""),
            model=kwargs.get("model", "tts-1"),
        )
    if engine != "kokoro":
        print(f"WARNING: Unknown TTS engine '{engine}', falling back to kokoro. "
              f"Valid engines: kokoro, openai")
    return KokoroTTSEngine()
