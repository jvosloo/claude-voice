"""Tests for configuration loading in daemon/config.py."""

from daemon.config import (
    AfkConfig, AfkTelegramConfig, Config, InputConfig, TranscriptionConfig,
    SpeechConfig, AudioConfig, OverlayConfig, load_config,
    DEFAULT_NOTIFY_PHRASES,
)
from unittest.mock import patch, mock_open


class TestAfkConfigPostInit:

    def test_none_telegram_gets_default(self):
        cfg = AfkConfig()
        assert isinstance(cfg.telegram, AfkTelegramConfig)
        assert cfg.telegram.bot_token == ""

    def test_dict_telegram_converted(self):
        cfg = AfkConfig(telegram={"bot_token": "abc", "chat_id": "123"})
        assert isinstance(cfg.telegram, AfkTelegramConfig)
        assert cfg.telegram.bot_token == "abc"
        assert cfg.telegram.chat_id == "123"

    def test_already_instantiated_telegram(self):
        t = AfkTelegramConfig(bot_token="tok", chat_id="id")
        cfg = AfkConfig(telegram=t)
        assert cfg.telegram is t

    def test_default_voice_commands(self):
        cfg = AfkConfig()
        assert "going afk" in cfg.voice_commands_activate
        assert "i'm back" in cfg.voice_commands_deactivate

    def test_custom_voice_commands(self):
        cfg = AfkConfig(
            voice_commands_activate=["bye"],
            voice_commands_deactivate=["hello"],
        )
        assert cfg.voice_commands_activate == ["bye"]
        assert cfg.voice_commands_deactivate == ["hello"]


class TestLoadConfig:

    def test_missing_file_returns_defaults(self):
        with patch("daemon.config.os.path.exists", return_value=False):
            cfg = load_config()
        assert isinstance(cfg, Config)
        assert cfg.input.hotkey == "right_alt"
        assert cfg.speech.mode == "notify"

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
