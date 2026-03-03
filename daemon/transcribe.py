"""Transcription functionality for Claude Voice daemon (Whisper + Parakeet backends)."""

import os
import re
import time
import threading
import numpy as np
from typing import Optional


FILLER_WORDS = [
    "you know", "I mean",  # multi-word first (greedy match)
    "um", "uh", "ah", "er",
]

# Pre-compiled pattern: match fillers as whole words, case-insensitive
_FILLER_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(f) for f in FILLER_WORDS) + r')\b,?\s*',
    re.IGNORECASE,
)


def strip_filler_words(text: str) -> str:
    """Remove filler words (um, uh, like, you know, etc.) from text."""
    if not text:
        return text
    text = _FILLER_RE.sub('', text)
    # Clean up extra whitespace and fix leading/trailing
    text = re.sub(r'\s{2,}', ' ', text).strip()
    # Fix orphaned capitalization: if first char is now lowercase after
    # stripping a filler from the start, capitalize it
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def apply_word_replacements(text: str, replacements: dict) -> str:
    """Apply word replacements to transcribed text.

    Uses whole-word matching (word boundaries) and case-insensitive matching.
    Multi-word phrases are supported.
    """
    if not replacements or not text:
        return text
    for wrong, correct in replacements.items():
        text = re.sub(r'\b' + re.escape(wrong) + r'\b', correct, text, flags=re.IGNORECASE)
    return text

class Transcriber:
    """Transcribes audio using Whisper (faster-whisper or MLX backend)."""

    # Map simple model names to MLX HuggingFace repos
    MLX_MODELS = {
        "tiny.en": "mlx-community/whisper-tiny.en-mlx",
        "base.en": "mlx-community/whisper-base.en-mlx",
        "small.en": "mlx-community/whisper-small.en-mlx",
        "medium.en": "mlx-community/whisper-medium.en-mlx",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    }

    def __init__(self, model_name: str = "base.en", device: str = "cpu", backend: str = "faster-whisper",
                 language_backends: dict = None, openai_api_key: str = "",
                 idle_unload: int = 0):
        self.model_name = model_name
        self.device = device
        self.backend = backend
        self._model = None
        self._model_dir = os.path.expanduser("~/.claude-voice/models/whisper")
        self.language_backends = language_backends or {}
        self.openai_api_key = openai_api_key
        self._cloud_transcribers = {}
        self._last_used = time.time()
        self._idle_timer: threading.Timer | None = None
        self._idle_unload = idle_unload
        self._start_idle_timer()

    def _start_idle_timer(self):
        """Start the periodic idle-check timer."""
        self.stop_idle_timer()
        if self._idle_unload <= 0:
            return
        t = threading.Timer(60.0, self._check_idle)
        t.daemon = True
        t.start()
        self._idle_timer = t

    def stop_idle_timer(self):
        """Cancel the idle-check timer."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def set_idle_unload(self, minutes: int):
        """Update the idle unload timeout and restart the timer."""
        self._idle_unload = minutes
        self._start_idle_timer()

    def _check_idle(self):
        """Timer callback: unload model if idle too long, then reschedule."""
        if self._idle_unload > 0 and self._model is not None:
            idle_seconds = time.time() - self._last_used
            if idle_seconds >= self._idle_unload * 60:
                print(f"Transcription model idle for {idle_seconds/60:.0f}m, unloading from RAM")
                self._model = None
        self._start_idle_timer()

    def _ensure_model(self):
        """Lazy-load the Whisper model."""
        self._last_used = time.time()
        if self._model is None:
            from daemon.spinner import Spinner
            if self.backend == "parakeet":
                with Spinner(f"Loading Parakeet model: {self.model_name}"):
                    from parakeet_mlx import from_pretrained
                    self._model = from_pretrained(self.model_name)
            elif self.backend == "mlx":
                with Spinner(f"Loading MLX Whisper model: {self.model_name}"):
                    # Warm up MLX by doing a dummy transcription (triggers actual model load)
                    silent_audio = np.zeros(16000, dtype=np.float32)  # 1 second of silence
                    self._transcribe_mlx(silent_audio)
                    self._model = "mlx"
            else:
                from faster_whisper import WhisperModel
                with Spinner(f"Loading Whisper model: {self.model_name}"):
                    self._model = WhisperModel(
                        self.model_name,
                        device=self.device,
                        download_root=self._model_dir,
                    )
        return self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, language: str = "en",
                   initial_prompt: Optional[str] = None) -> str:
        """Transcribe audio to text.

        Args:
            audio: Audio data as float32 numpy array
            sample_rate: Sample rate (must be 16000 for Whisper)
            language: Language code for transcription (e.g. "en", "af", "de")
            initial_prompt: Optional text to condition the model on, biasing it
                toward recognizing specific vocabulary (e.g. "Claude, pytest, TypeScript")

        Returns:
            Transcribed text string
        """
        self._last_used = time.time()
        if len(audio) == 0:
            return ""

        # Check for per-language backend override
        if language in self.language_backends:
            return self._transcribe_cloud(audio, language=language, sample_rate=sample_rate)

        self._ensure_model()

        # Whisper expects float32 audio normalized to [-1, 1]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        if self.backend == "parakeet":
            return self._transcribe_parakeet(audio)

        if self.backend == "mlx":
            return self._transcribe_mlx(audio, language=language, initial_prompt=initial_prompt)
        else:
            return self._transcribe_faster_whisper(audio, language=language, initial_prompt=initial_prompt)

    def _transcribe_cloud(self, audio: np.ndarray, language: str,
                          sample_rate: int = 16000) -> str:
        """Route to cloud transcription backend for this language."""
        if language not in self._cloud_transcribers:
            config = self.language_backends[language]
            backend = config.get("backend")
            if backend == "openai":
                from daemon.transcribe_openai import OpenAITranscriber
                self._cloud_transcribers[language] = OpenAITranscriber(
                    api_key=self.openai_api_key,
                    model=config.get("model", "gpt-4o-transcribe"),
                )
            elif backend == "google":
                from daemon.transcribe_google import GoogleCloudTranscriber
                self._cloud_transcribers[language] = GoogleCloudTranscriber(
                    credentials_path=config["google_credentials"]
                )
            else:
                print(f"WARNING: Unknown cloud backend '{backend}' for language '{language}', "
                      f"falling back to local Whisper")
                del self.language_backends[language]
                return self.transcribe(audio, sample_rate=sample_rate, language=language)

        return self._cloud_transcribers[language].transcribe(
            audio, language=language, sample_rate=sample_rate
        )

    def _transcribe_parakeet(self, audio: np.ndarray) -> str:
        """Transcribe using Parakeet MLX.

        parakeet_mlx.transcribe() expects a file path, so we write
        a temporary WAV file from the numpy audio buffer.
        """
        import tempfile
        import wave

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
            with wave.open(f.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(16000)
                wf.writeframes((audio * 32767).astype(np.int16).tobytes())
            result = self._model.transcribe(f.name)
        return result.text.strip()

    def _transcribe_mlx(self, audio: np.ndarray, language: str = "en",
                        initial_prompt: Optional[str] = None) -> str:
        """Transcribe using MLX Whisper."""
        import mlx_whisper

        # Get MLX model repo name
        mlx_model = self.MLX_MODELS.get(self.model_name)
        if mlx_model is None:
            valid = ", ".join(self.MLX_MODELS.keys())
            print(f"WARNING: Unknown model '{self.model_name}', falling back to large-v3. "
                  f"Valid models: {valid}")
            self.model_name = "large-v3"
            mlx_model = self.MLX_MODELS["large-v3"]

        kwargs = dict(
            path_or_hf_repo=mlx_model,
            language=language,
            condition_on_previous_text=False,
        )
        if initial_prompt is not None:
            kwargs["initial_prompt"] = initial_prompt

        result = mlx_whisper.transcribe(audio, **kwargs)

        return result.get("text", "").strip()

    def _transcribe_faster_whisper(self, audio: np.ndarray, language: str = "en",
                                   initial_prompt: Optional[str] = None) -> str:
        """Transcribe using faster-whisper."""
        kwargs = dict(
            language=language,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        if initial_prompt is not None:
            kwargs["initial_prompt"] = initial_prompt

        segments, info = self._model.transcribe(audio, **kwargs)

        text_parts = [segment.text.strip() for segment in segments]
        return " ".join(text_parts).strip()
