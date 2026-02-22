"""Tests for daemon/transcribe_google.py — Google Cloud STT backend."""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from daemon.transcribe_google import GoogleCloudTranscriber


def _make_mock_speech():
    """Create a mock google.cloud.speech module with real-enough types."""
    speech = MagicMock()

    # RecognitionConfig: store kwargs as attributes
    class FakeRecognitionConfig:
        class AudioEncoding:
            LINEAR16 = 1
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    # RecognitionAudio: store kwargs as attributes
    class FakeRecognitionAudio:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    speech.RecognitionConfig = FakeRecognitionConfig
    speech.RecognitionAudio = FakeRecognitionAudio
    return speech


class TestGoogleCloudTranscriber:

    def test_transcribe_returns_text(self):
        """Basic transcription returns recognized text."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_alternative = MagicMock()
        mock_alternative.transcript = "hallo wêreld"
        mock_result.alternatives = [mock_alternative]
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            t._speech = _make_mock_speech()
            result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        assert result == "hallo wêreld"

    def test_transcribe_empty_audio_returns_empty(self):
        """Empty audio returns empty string without calling API."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")
        result = t.transcribe(np.array([], dtype=np.float32), language="af")
        assert result == ""

    def test_transcribe_no_results_returns_empty(self):
        """API returning no results gives empty string."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            t._speech = _make_mock_speech()
            result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        assert result == ""

    def test_language_code_mapping(self):
        """Language codes are mapped to Google format (e.g., af -> af-ZA)."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            t._speech = _make_mock_speech()
            t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        call_args = mock_client.recognize.call_args
        config = call_args[1]["config"] if "config" in call_args[1] else call_args[0][0]
        assert config.language_code == "af-ZA"

    def test_audio_converted_to_pcm_16bit(self):
        """Float32 audio is converted to LINEAR16 PCM bytes for the API."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_client.recognize.return_value = mock_response

        audio = np.array([0.5, -0.5, 0.0], dtype=np.float32)

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            t._speech = _make_mock_speech()
            t.transcribe(audio, language="af")

        call_args = mock_client.recognize.call_args
        audio_arg = call_args[1]["audio"] if "audio" in call_args[1] else call_args[0][1]
        # Audio content should be bytes (LINEAR16)
        assert isinstance(audio_arg.content, bytes)
        # 3 samples * 2 bytes per sample (int16) = 6 bytes
        assert len(audio_arg.content) == 6

    def test_client_lazy_loaded(self):
        """Client is not created until first transcribe call."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")
        assert t._client is None

    def test_multiple_results_concatenated(self):
        """Multiple recognition results are joined with spaces."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        result1 = MagicMock()
        alt1 = MagicMock()
        alt1.transcript = "hallo"
        result1.alternatives = [alt1]
        result2 = MagicMock()
        alt2 = MagicMock()
        alt2.transcript = "wêreld"
        result2.alternatives = [alt2]
        mock_response = MagicMock()
        mock_response.results = [result1, result2]
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            t._speech = _make_mock_speech()
            result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        assert result == "hallo wêreld"
