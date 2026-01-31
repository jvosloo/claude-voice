"""Shared test fixtures for claude-voice tests."""

import os
import sys

import pytest

# Add project root to path so `daemon` and `hooks` are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def sample_config_dict():
    """Minimal valid config dict matching config.yaml.example structure."""
    return {
        "input": {"hotkey": "right_alt"},
        "transcription": {"model": "large-v3", "language": "en"},
        "speech": {"enabled": True, "mode": "notify", "voice": "af_heart"},
        "audio": {"sample_rate": 16000},
        "overlay": {"enabled": False},
        "afk": {},
    }


@pytest.fixture
def tmp_config_file(tmp_path, sample_config_dict):
    """Write a temporary config YAML file and return its path."""
    import yaml
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(sample_config_dict))
    return str(config_path)
