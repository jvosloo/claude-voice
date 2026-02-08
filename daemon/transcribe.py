"""Whisper transcription functionality for Claude Voice daemon."""

import os
import re
import numpy as np
from typing import Optional


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

    def __init__(self, model_name: str = "base.en", device: str = "cpu", backend: str = "faster-whisper"):
        self.model_name = model_name
        self.device = device
        self.backend = backend
        self._model = None
        self._model_dir = os.path.expanduser("~/.claude-voice/models/whisper")

    def _ensure_model(self):
        """Lazy-load the Whisper model."""
        if self._model is None:
            from daemon.spinner import Spinner
            if self.backend == "mlx":
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

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, language: str = "en") -> str:
        """Transcribe audio to text.

        Args:
            audio: Audio data as float32 numpy array
            sample_rate: Sample rate (must be 16000 for Whisper)
            language: Language code for transcription (e.g. "en", "af", "de")

        Returns:
            Transcribed text string
        """
        if len(audio) == 0:
            return ""

        self._ensure_model()

        # Whisper expects float32 audio normalized to [-1, 1]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        if self.backend == "mlx":
            return self._transcribe_mlx(audio, language=language)
        else:
            return self._transcribe_faster_whisper(audio, language=language)

    def _transcribe_mlx(self, audio: np.ndarray, language: str = "en") -> str:
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

        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=mlx_model,
            language=language,
        )

        return result.get("text", "").strip()

    def _transcribe_faster_whisper(self, audio: np.ndarray, language: str = "en") -> str:
        """Transcribe using faster-whisper."""
        segments, info = self._model.transcribe(
            audio,
            language=language,
            vad_filter=True,
        )

        text_parts = [segment.text.strip() for segment in segments]
        return " ".join(text_parts).strip()
