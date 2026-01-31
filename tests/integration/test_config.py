"""Integration tests for config loading with real file I/O."""

import os
import yaml
import pytest
from daemon.config import load_config, CONFIG_PATH
from unittest.mock import patch


class TestLoadConfigWithFiles:

    def test_full_config_roundtrip(self, tmp_path):
        """Write a full config to disk and load it."""
        config_data = {
            "input": {
                "hotkey": "f18",
                "auto_submit": True,
                "min_audio_length": 1.0,
            },
            "transcription": {
                "model": "small.en",
                "language": "en",
                "backend": "faster-whisper",
            },
            "speech": {
                "enabled": False,
                "mode": "narrate",
                "voice": "bf_emma",
                "speed": 1.2,
            },
            "audio": {"sample_rate": 44100},
            "overlay": {"enabled": False, "style": "frosted"},
            "afk": {
                "telegram": {"bot_token": "tok", "chat_id": "123"},
                "hotkey": "left_alt+a",
            },
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        with patch("daemon.config.CONFIG_PATH", str(config_path)):
            cfg = load_config()

        assert cfg.input.hotkey == "f18"
        assert cfg.input.auto_submit is True
        assert cfg.transcription.backend == "faster-whisper"
        assert cfg.speech.voice == "bf_emma"
        assert cfg.speech.speed == 1.2
        assert cfg.audio.sample_rate == 44100
        assert cfg.overlay.style == "frosted"
        assert cfg.afk.telegram.bot_token == "tok"

    def test_empty_file(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")

        with patch("daemon.config.CONFIG_PATH", str(config_path)):
            cfg = load_config()

        # All defaults
        assert cfg.input.hotkey == "right_alt"
        assert cfg.speech.mode == "notify"

    def test_unknown_keys_raise(self, tmp_path):
        """Unknown keys in a section cause TypeError from dataclass init."""
        config_data = {"input": {"hotkey": "f18", "unknown_key": True}}
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        with patch("daemon.config.CONFIG_PATH", str(config_path)):
            with pytest.raises(TypeError):
                load_config()
