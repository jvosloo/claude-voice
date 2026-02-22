"""OpenAI cloud speech-to-text transcription backend."""

import io
import os
import wave

import numpy as np


class OpenAITranscriber:
    """Transcribes audio using OpenAI's transcription API."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o-transcribe"):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model

    def transcribe(self, audio: np.ndarray, language: str = "af",
                   sample_rate: int = 16000) -> str:
        """Transcribe audio using OpenAI's transcription API.

        Args:
            audio: Audio data as float32 numpy array normalized to [-1, 1]
            language: Language code (e.g. "af", "en")
            sample_rate: Audio sample rate in Hz

        Returns:
            Transcribed text string, or "" on error
        """
        if len(audio) == 0:
            return ""

        if not self._api_key:
            print("OpenAI STT: no API key configured (set speech.openai_api_key or OPENAI_API_KEY env var)")
            return ""

        import requests

        # Encode audio as WAV in memory
        pcm = (audio * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        wav_bytes = buf.getvalue()

        try:
            response = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": self._model, "language": language},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("text", "").strip()

        except requests.Timeout:
            print("OpenAI STT error: request timed out (30s)")
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            detail = ""
            if e.response is not None:
                try:
                    body = e.response.json()
                    detail = body.get("error", {}).get("message", e.response.text)
                except Exception:
                    detail = e.response.text
            print(f"OpenAI STT error: HTTP {status}: {detail}")
        except requests.ConnectionError:
            print("OpenAI STT error: cannot reach api.openai.com")
        except Exception as e:
            print(f"OpenAI STT error: {type(e).__name__}: {e}")

        return ""
