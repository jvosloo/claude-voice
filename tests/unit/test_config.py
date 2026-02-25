"""Tests for configuration loading in daemon/config.py."""

from daemon.config import (
    Config, InputConfig, TranscriptionConfig,
    SpeechConfig, AudioConfig, OverlayConfig, load_config,
    DEFAULT_NOTIFY_PHRASES,
)
from unittest.mock import patch, mock_open


class TestLoadConfig:

    def test_missing_file_returns_defaults(self):
        with patch("daemon.config.os.path.exists", return_value=False):
            cfg = load_config()
        assert isinstance(cfg, Config)
        assert cfg.input.hotkey == "right_alt"
        assert cfg.speech.mode == "notify"
        assert cfg.speech.engine == "kokoro"
        assert cfg.speech.openai_api_key == ""
        assert cfg.speech.openai_model == "tts-1"

    def test_valid_yaml_parsed(self):
        yaml_content = """
input:
  hotkey: "f19"
speech:
  mode: "narrate"
  voice: "bf_emma"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.input.hotkey == "f19"
        assert cfg.speech.mode == "narrate"
        assert cfg.speech.voice == "bf_emma"

    def test_empty_yaml_returns_defaults(self):
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="")):
                cfg = load_config()
        assert cfg.input.hotkey == "right_alt"

    def test_strips_removed_notify_model_key(self):
        yaml_content = """
speech:
  notify_model: "old_model"
  mode: "notify"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.speech.mode == "notify"

    def test_openai_engine_yaml_parsed(self):
        yaml_content = """
speech:
  engine: "openai"
  openai_api_key: "sk-yaml-key"
  openai_model: "tts-1-hd"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.speech.engine == "openai"
        assert cfg.speech.openai_api_key == "sk-yaml-key"
        assert cfg.speech.openai_model == "tts-1-hd"

    def test_partial_config_fills_defaults(self):
        yaml_content = """
input:
  auto_submit: true
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.input.auto_submit is True
        assert cfg.input.hotkey == "right_alt"  # default
        assert cfg.speech.mode == "notify"  # default


def test_default_notify_phrases_has_all_categories():
    assert "done" in DEFAULT_NOTIFY_PHRASES
    assert "permission" in DEFAULT_NOTIFY_PHRASES
    assert "question" in DEFAULT_NOTIFY_PHRASES


def test_done_phrase_text():
    assert DEFAULT_NOTIFY_PHRASES["done"] == "Over to you"


def test_question_phrase_text():
    assert DEFAULT_NOTIFY_PHRASES["question"] == "Please choose an option"


class TestLanguageBackends:

    def test_language_backends_default_empty(self):
        """No language_backends configured by default."""
        with patch("daemon.config.os.path.exists", return_value=False):
            cfg = load_config()
        assert cfg.transcription.language_backends == {}

    def test_language_backends_parsed_from_yaml(self):
        yaml_content = """
transcription:
  language_backends:
    af:
      backend: "google"
      google_credentials: "~/.claude-voice/google-creds.json"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.transcription.language_backends == {
            "af": {
                "backend": "google",
                "google_credentials": "~/.claude-voice/google-creds.json",
            }
        }

    def test_language_backends_ignored_when_absent(self):
        """Existing configs without language_backends still work."""
        yaml_content = """
transcription:
  model: "large-v3-turbo"
  language: "en"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.transcription.language_backends == {}
