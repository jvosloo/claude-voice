"""Google Cloud Speech-to-Text transcription backend."""

import numpy as np
from typing import Optional


# Language code mapping: short code -> Google BCP-47 code
LANGUAGE_MAP = {
    "af": "af-ZA",
    "en": "en-US",
    "de": "de-DE",
    "nl": "nl-NL",
    "fr": "fr-FR",
    "es": "es-ES",
    "pt": "pt-BR",
    "it": "it-IT",
    "ja": "ja-JP",
    "zh": "zh-CN",
}


class GoogleCloudTranscriber:
    """Transcribes audio using Google Cloud Speech-to-Text API."""

    def __init__(self, credentials_path: str):
        self._credentials_path = credentials_path
        self._client = None
        self._speech = None  # cached google.cloud.speech module

    def _ensure_client(self):
        """Lazy-load the Google Cloud Speech client and speech module."""
        if self._client is None:
            import os
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.expanduser(
                self._credentials_path
            )
            from google.cloud import speech
            self._speech = speech
            self._client = speech.SpeechClient()
        return self._client

    def transcribe(self, audio: np.ndarray, language: str = "af",
                   sample_rate: int = 16000) -> str:
        """Transcribe audio using Google Cloud Speech-to-Text.

        Args:
            audio: Audio data as float32 numpy array normalized to [-1, 1]
            language: Language code (e.g. "af", "en")
            sample_rate: Audio sample rate in Hz

        Returns:
            Transcribed text string
        """
        if len(audio) == 0:
            return ""

        client = self._ensure_client()
        speech = self._speech

        # Convert float32 [-1, 1] to int16 PCM bytes
        pcm = (audio * 32767).astype(np.int16).tobytes()

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=LANGUAGE_MAP.get(language, f"{language}-ZA"),
        )

        audio_content = speech.RecognitionAudio(content=pcm)

        response = client.recognize(config=config, audio=audio_content)

        parts = []
        for result in response.results:
            if result.alternatives:
                parts.append(result.alternatives[0].transcript)

        return " ".join(parts).strip()
