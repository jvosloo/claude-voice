"""Tests for notify phrase regeneration with OpenAI backend."""

import os
import pytest
import requests as requests_lib
from unittest.mock import patch, MagicMock

from daemon.notify import _regen_openai


class TestRegenOpenai:

    def test_missing_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="No OpenAI API key"):
                _regen_openai({"done": "Over to you"}, "alloy", 1.0, "", "tts-1")

    def test_env_var_fallback_for_api_key(self, tmp_path):
        mock_response = MagicMock()
        mock_response.content = b"fake-wav"
        mock_response.ok = True

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env"}), \
             patch.object(requests_lib, "post", return_value=mock_response) as mock_post, \
             patch("daemon.notify._CACHE_DIR", str(tmp_path)):
            _regen_openai({"done": "test"}, "alloy", 1.0, "", "tts-1")

        assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer sk-env"

    def test_explicit_key_used_over_env(self, tmp_path):
        mock_response = MagicMock()
        mock_response.content = b"fake-wav"
        mock_response.ok = True

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env"}), \
             patch.object(requests_lib, "post", return_value=mock_response) as mock_post, \
             patch("daemon.notify._CACHE_DIR", str(tmp_path)):
            _regen_openai({"done": "test"}, "alloy", 1.0, "sk-explicit", "tts-1")

        assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer sk-explicit"

    def test_writes_wav_file_atomically(self, tmp_path):
        mock_response = MagicMock()
        mock_response.content = b"RIFF-fake-wav-data"
        mock_response.ok = True

        with patch.object(requests_lib, "post", return_value=mock_response), \
             patch("daemon.notify._CACHE_DIR", str(tmp_path)):
            _regen_openai({"done": "test"}, "alloy", 1.0, "sk-test", "tts-1")

        out_path = tmp_path / "done.wav"
        assert out_path.exists()
        assert out_path.read_bytes() == b"RIFF-fake-wav-data"

    def test_api_params_correct(self, tmp_path):
        mock_response = MagicMock()
        mock_response.content = b"wav"
        mock_response.ok = True

        with patch.object(requests_lib, "post", return_value=mock_response) as mock_post, \
             patch("daemon.notify._CACHE_DIR", str(tmp_path)):
            _regen_openai({"done": "Over to you"}, "nova", 1.5, "sk-test", "tts-1-hd")

        body = mock_post.call_args[1]["json"]
        assert body["model"] == "tts-1-hd"
        assert body["voice"] == "nova"
        assert body["speed"] == 1.5
        assert body["input"] == "Over to you"
        assert body["response_format"] == "wav"

    def test_http_error_propagates_with_detail(self):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": {"message": "You exceeded your current quota", "type": "insufficient_quota"}
        }

        with patch.object(requests_lib, "post", return_value=mock_response), \
             pytest.raises(RuntimeError, match="You exceeded your current quota"):
            _regen_openai({"done": "test"}, "alloy", 1.0, "sk-test", "tts-1")

    def test_multiple_phrases_all_generated(self, tmp_path):
        mock_response = MagicMock()
        mock_response.content = b"wav-data"
        mock_response.ok = True

        phrases = {"done": "Over to you", "permission": "Permission needed", "question": "Choose"}

        with patch.object(requests_lib, "post", return_value=mock_response) as mock_post, \
             patch("daemon.notify._CACHE_DIR", str(tmp_path)):
            _regen_openai(phrases, "alloy", 1.0, "sk-test", "tts-1")

        assert mock_post.call_count == 3
        for cat in phrases:
            assert (tmp_path / f"{cat}.wav").exists()
