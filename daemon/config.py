"""Configuration loader for Claude Voice daemon."""

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional

CONFIG_PATH = os.path.expanduser("~/.claude-voice/config.yaml")

@dataclass
class InputConfig:
    hotkey: str = "right_alt"
    language_hotkey: Optional[str] = None
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
    extra_languages: list = field(default_factory=list)

DEFAULT_NOTIFY_PHRASES = {
    "permission": "Permission needed",
    "done": "Ready for input",
}

@dataclass
class SpeechConfig:
    enabled: bool = True
    mode: str = "notify"                   # "notify" or "narrate"
    voice: str = "af_heart"
    speed: float = 1.0
    lang_code: str = "a"
    max_chars: Optional[int] = None
    skip_code_blocks: bool = True
    skip_tool_results: bool = True
    notify_phrases: Optional[dict] = None  # Custom phrase overrides

@dataclass
class AudioConfig:
    input_device: Optional[int] = None
    sample_rate: int = 16000

@dataclass
class OverlayConfig:
    enabled: bool = True
    style: str = "dark"  # "dark", "frosted", or "colored"
    recording_color: str = "#34C759"
    transcribing_color: str = "#A855F7"

@dataclass
class Config:
    input: InputConfig
    transcription: TranscriptionConfig
    speech: SpeechConfig
    audio: AudioConfig
    overlay: OverlayConfig

def load_config() -> Config:
    """Load configuration from YAML file, with defaults for missing values."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    # Strip removed config keys for backward compatibility
    speech_data = data.get('speech', {})
    speech_data.pop('notify_model', None)

    return Config(
        input=InputConfig(**data.get('input', {})),
        transcription=TranscriptionConfig(**data.get('transcription', {})),
        speech=SpeechConfig(**speech_data),
        audio=AudioConfig(**data.get('audio', {})),
        overlay=OverlayConfig(**data.get('overlay', {})),
    )
