"""Tests for daemon/transcribe_openai.py — OpenAI cloud STT backend."""

import io
import wave
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from daemon.transcribe_openai import OpenAITranscriber


class TestOpenAITranscriberInit:

    def test_api_key_stored(self):
        t = OpenAITranscriber(api_key="sk-test-123")
        assert t._api_key == "sk-test-123"

    def test_default_model(self):
        t = OpenAITranscriber(api_key="sk-test")
        assert t._model == "gpt-4o-transcribe"

    def test_custom_model(self):
        t = OpenAITranscriber(api_key="sk-test", model="gpt-4o-mini-transcribe")
        assert t._model == "gpt-4o-mini-transcribe"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-from-env"})
    def test_api_key_from_env(self):
        t = OpenAITranscriber(api_key="")
        assert t._api_key == "sk-from-env"


class TestOpenAITranscriberTranscribe:

    def test_empty_audio_returns_empty(self):
        t = OpenAITranscriber(api_key="sk-test")
        result = t.transcribe(np.array([], dtype=np.float32), language="af")
        assert result == ""

    def test_no_api_key_returns_empty(self):
        t = OpenAITranscriber(api_key="")
        # Clear env var too
        with patch.dict("os.environ", {}, clear=True):
            t._api_key = ""
            result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")
        assert result == ""

    @patch("requests.post")
    def test_happy_path_returns_text(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"text": "hallo wêreld"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        t = OpenAITranscriber(api_key="sk-test")
        result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        assert result == "hallo wêreld"
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_sends_correct_auth_header(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "test"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        t = OpenAITranscriber(api_key="sk-my-key")
        t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer sk-my-key"

    @patch("requests.post")
    def test_sends_correct_form_data(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "test"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        t = OpenAITranscriber(api_key="sk-test", model="gpt-4o-mini-transcribe")
        t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        call_kwargs = mock_post.call_args
        data = call_kwargs[1]["data"]
        assert data["model"] == "gpt-4o-mini-transcribe"
        assert data["language"] == "af"

    @patch("requests.post")
    def test_sends_valid_wav_file(self, mock_post):
        """The uploaded file must be a valid WAV with correct sample rate."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "test"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        t = OpenAITranscriber(api_key="sk-test")
        audio = np.array([0.5, -0.5, 0.0], dtype=np.float32)
        t.transcribe(audio, language="en", sample_rate=16000)

        call_kwargs = mock_post.call_args
        files = call_kwargs[1]["files"]
        file_tuple = files["file"]
        assert file_tuple[0] == "audio.wav"  # filename
        wav_bytes = file_tuple[1]

        # Verify it's a valid WAV
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getframerate() == 16000
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2  # int16
            assert wf.getnframes() == 3


class TestOpenAITranscriberErrors:

    @patch("requests.post")
    def test_timeout_returns_empty(self, mock_post):
        import requests
        mock_post.side_effect = requests.Timeout()

        t = OpenAITranscriber(api_key="sk-test")
        result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")
        assert result == ""

    @patch("requests.post")
    def test_http_401_returns_empty(self, mock_post):
        import requests
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "invalid key"
        resp.json.return_value = {"error": {"message": "invalid key"}}
        mock_post.side_effect = requests.HTTPError(response=resp)

        t = OpenAITranscriber(api_key="sk-bad")
        result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")
        assert result == ""

    @patch("requests.post")
    def test_http_429_returns_empty(self, mock_post):
        import requests
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "rate limited"
        resp.json.return_value = {"error": {"message": "rate limited"}}
        mock_post.side_effect = requests.HTTPError(response=resp)

        t = OpenAITranscriber(api_key="sk-test")
        result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")
        assert result == ""

    @patch("requests.post")
    def test_connection_error_returns_empty(self, mock_post):
        import requests
        mock_post.side_effect = requests.ConnectionError()

        t = OpenAITranscriber(api_key="sk-test")
        result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")
        assert result == ""
