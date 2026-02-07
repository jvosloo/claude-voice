"""Tests for TTS engine factory and OpenAI engine in daemon/tts.py."""

import subprocess
import requests as requests_lib
from unittest.mock import patch, MagicMock

from daemon.tts import (
    KokoroTTSEngine,
    OpenAITTSEngine,
    TTSEngine,
    create_tts_engine,
)


class TestCreateTTSEngine:

    def test_default_returns_kokoro(self):
        engine = create_tts_engine()
        assert isinstance(engine, KokoroTTSEngine)

    def test_kokoro_explicit(self):
        engine = create_tts_engine("kokoro")
        assert isinstance(engine, KokoroTTSEngine)

    def test_openai_returns_openai_engine(self):
        engine = create_tts_engine("openai", api_key="sk-test", model="tts-1-hd")
        assert isinstance(engine, OpenAITTSEngine)
        assert engine._api_key == "sk-test"
        assert engine._model == "tts-1-hd"

    def test_openai_default_model(self):
        engine = create_tts_engine("openai", api_key="sk-test")
        assert engine._model == "tts-1"

    def test_unknown_engine_warns_and_falls_back_to_kokoro(self, capsys):
        engine = create_tts_engine("unknown")
        assert isinstance(engine, KokoroTTSEngine)
        output = capsys.readouterr().out
        assert "WARNING" in output
        assert "unknown" in output
        assert "kokoro, openai" in output


class TestTTSEngineAlias:

    def test_alias_is_kokoro(self):
        assert TTSEngine is KokoroTTSEngine


class TestOpenAITTSEngine:

    def test_ensure_model_is_noop(self):
        engine = OpenAITTSEngine(api_key="sk-test")
        engine._ensure_model()  # Should not raise

    def test_speak_empty_text_returns_immediately(self):
        engine = OpenAITTSEngine(api_key="sk-test")
        # Should not make any API calls
        with patch("daemon.tts.subprocess.Popen") as mock_popen:
            engine.speak("")
            mock_popen.assert_not_called()

    def test_speak_no_api_key_prints_error(self, capsys):
        with patch.dict("os.environ", {}, clear=True):
            engine = OpenAITTSEngine(api_key="")
            engine.speak("Hello")
        output = capsys.readouterr().out
        assert "no API key configured" in output

    def test_speak_calls_openai_api(self):
        engine = OpenAITTSEngine(api_key="sk-test123", model="tts-1-hd")

        mock_response = MagicMock()
        mock_response.content = b"fake-wav-data"
        mock_response.raise_for_status = MagicMock()

        mock_proc = MagicMock()
        mock_proc.wait = MagicMock()

        with patch.object(requests_lib, "post", return_value=mock_response) as mock_post, \
             patch("subprocess.Popen", return_value=mock_proc), \
             patch("os.unlink"):
            engine.speak("Hello world", voice="nova", speed=1.2)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "https://api.openai.com/v1/audio/speech"
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer sk-test123"
        body = call_kwargs[1]["json"]
        assert body["model"] == "tts-1-hd"
        assert body["input"] == "Hello world"
        assert body["voice"] == "nova"
        assert body["speed"] == 1.2
        assert body["response_format"] == "wav"

    def test_speak_auth_error_prints_specific_message(self, capsys):
        engine = OpenAITTSEngine(api_key="sk-bad")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}
        }
        error = requests_lib.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = error

        with patch.object(requests_lib, "post", return_value=mock_response):
            engine.speak("Hello")

        output = capsys.readouterr().out
        assert "invalid API key" in output
        assert "401" in output
        assert "Incorrect API key provided" in output

    def test_speak_quota_exceeded_prints_detail(self, capsys):
        engine = OpenAITTSEngine(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": {"message": "You exceeded your current quota", "type": "insufficient_quota"}
        }
        error = requests_lib.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = error

        with patch.object(requests_lib, "post", return_value=mock_response):
            engine.speak("Hello")

        output = capsys.readouterr().out
        assert "rejected" in output
        assert "429" in output
        assert "You exceeded your current quota" in output

    def test_speak_timeout_prints_specific_message(self, capsys):
        engine = OpenAITTSEngine(api_key="sk-test")

        with patch.object(requests_lib, "post", side_effect=requests_lib.Timeout("timed out")):
            engine.speak("Hello")

        output = capsys.readouterr().out
        assert "timed out" in output

    def test_speak_connection_error_prints_specific_message(self, capsys):
        engine = OpenAITTSEngine(api_key="sk-test")

        with patch.object(requests_lib, "post", side_effect=requests_lib.ConnectionError("no route")):
            engine.speak("Hello")

        output = capsys.readouterr().out
        assert "cannot reach" in output

    def test_speak_env_var_fallback(self):
        mock_response = MagicMock()
        mock_response.content = b"fake-wav-data"
        mock_response.raise_for_status = MagicMock()

        mock_proc = MagicMock()
        mock_proc.wait = MagicMock()

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-from-env"}), \
             patch.object(requests_lib, "post", return_value=mock_response) as mock_post, \
             patch("subprocess.Popen", return_value=mock_proc), \
             patch("os.unlink"):
            # Recreate engine to pick up env var
            engine = OpenAITTSEngine(api_key="")
            engine.speak("Test")

        assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer sk-from-env"

    def test_explicit_api_key_overrides_env_var(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env"}):
            engine = OpenAITTSEngine(api_key="sk-explicit")
        assert engine._api_key == "sk-explicit"

    def test_speak_cleans_up_temp_file_on_failure(self, capsys):
        engine = OpenAITTSEngine(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.content = b"fake-wav-data"
        mock_response.raise_for_status = MagicMock()

        with patch.object(requests_lib, "post", return_value=mock_response), \
             patch("subprocess.Popen", side_effect=OSError("afplay not found")), \
             patch("os.unlink") as mock_unlink:
            engine.speak("Hello")

        # Temp file should still be cleaned up via finally block
        mock_unlink.assert_called_once()

    def test_stop_playback_kills_proc(self):
        engine = OpenAITTSEngine(api_key="sk-test")
        mock_proc = MagicMock(spec=subprocess.Popen)
        engine._playback_proc = mock_proc

        with patch("daemon.kill_playback_proc", return_value=True) as mock_kill:
            result = engine.stop_playback()

        mock_kill.assert_called_once_with(mock_proc)
        assert result is True
        assert engine._playback_proc is None

    def test_stop_playback_no_proc(self):
        engine = OpenAITTSEngine(api_key="sk-test")

        with patch("daemon.kill_playback_proc", return_value=False) as mock_kill:
            result = engine.stop_playback()

        mock_kill.assert_called_once_with(None)
        assert result is False
