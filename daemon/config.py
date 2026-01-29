"""Configuration loader for Claude Voice daemon."""

import os
import yaml
from dataclasses import dataclass
from typing import Optional

CONFIG_PATH = os.path.expanduser("~/.claude-voice/config.yaml")

@dataclass
class InputConfig:
    hotkey: str = "right_alt"
    auto_submit: bool = False
    min_audio_length: float = 0.5
    typing_delay: float = 0.01
    transcription_cleanup: bool = False
    cleanup_model: str = "qwen2.5:1.5b"
    debug: bool = False

@dataclass
class TranscriptionConfig:
    model: str = "base.en"
    language: str = "en"
    device: str = "cpu"
    backend: str = "faster-whisper"  # "faster-whisper" or "mlx"

@dataclass
class SpeechConfig:
    enabled: bool = True
    voice: str = "en_GB-alan-medium"
    speed: float = 1.0
    max_chars: Optional[int] = None
    skip_code_blocks: bool = True
    skip_tool_results: bool = True

@dataclass
class AudioConfig:
    input_device: Optional[int] = None
    sample_rate: int = 16000

@dataclass
class Config:
    input: InputConfig
    transcription: TranscriptionConfig
    speech: SpeechConfig
    audio: AudioConfig

def load_config() -> Config:
    """Load configuration from YAML file, with defaults for missing values."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    return Config(
        input=InputConfig(**data.get('input', {})),
        transcription=TranscriptionConfig(**data.get('transcription', {})),
        speech=SpeechConfig(**data.get('speech', {})),
        audio=AudioConfig(**data.get('audio', {})),
    )
