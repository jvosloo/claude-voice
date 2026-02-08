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
    typing_delay: float = 0.0
    debug: bool = False

@dataclass
class TranscriptionConfig:
    model: str = "large-v3-turbo"
    language: str = "en"
    device: str = "cpu"
    backend: str = "mlx"  # "faster-whisper" or "mlx"
    extra_languages: list = field(default_factory=list)
    word_replacements: dict = field(default_factory=lambda: {"clawd": "Claude"})

DEFAULT_NOTIFY_PHRASES = {
    "permission": "Permission needed",
    "done": "Over to you",
    "question": "Please choose an option",
}

# Translated notify phrases per Kokoro lang_code.
# Only languages with working Kokoro TTS pipelines are included.
# a=American, b=British use English defaults (no entry needed).
# Many lang_codes (e, f, h, i, p) have upstream phonemizer bugs;
# j and z require extra pip packages (misaki[ja], misaki[zh]).
# Translations can be added here as Kokoro support improves.
NOTIFY_PHRASES_BY_LANG = {
}

@dataclass
class SpeechConfig:
    enabled: bool = True
    mode: str = "notify"                   # "notify" or "narrate"
    narrate_style: str = "brief"           # "brief", "conversational", or "bullets"
    summarize_model: str = "qwen2.5:3b"    # Ollama model for narrate summarization
    engine: str = "kokoro"                 # "kokoro" (local, free) or "openai" (cloud)
    openai_api_key: str = ""               # API key (or use OPENAI_API_KEY env var)
    openai_model: str = "tts-1"            # "tts-1" (fast) or "tts-1-hd" (higher quality)
    voice: str = "af_heart"
    speed: float = 1.0
    lang_code: str = "a"
    max_chars: Optional[int] = None
    skip_code_blocks: bool = True
    skip_tool_results: bool = True
    notify_phrases: Optional[dict] = None  # Custom phrase overrides
    hotkey: Optional[str] = "left_alt+v"   # Toggle voice on/off

@dataclass
class AudioConfig:
    input_device: Optional[int] = None
    sample_rate: int = 16000

@dataclass
class OverlayConfig:
    enabled: bool = True
    style: str = "dark"  # "dark", "frosted", or "colored"

@dataclass
class AfkTelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

@dataclass
class AfkConfig:
    telegram: AfkTelegramConfig = None
    hotkey: str = "left_alt+a"
    voice_commands_activate: list = None
    voice_commands_deactivate: list = None

    def __post_init__(self):
        if self.telegram is None:
            self.telegram = AfkTelegramConfig()
        elif isinstance(self.telegram, dict):
            self.telegram = AfkTelegramConfig(**self.telegram)
        if self.voice_commands_activate is None:
            self.voice_commands_activate = ["going afk", "away from keyboard"]
        if self.voice_commands_deactivate is None:
            self.voice_commands_deactivate = ["back at keyboard", "i'm back"]

@dataclass
class Config:
    input: InputConfig
    transcription: TranscriptionConfig
    speech: SpeechConfig
    audio: AudioConfig
    overlay: OverlayConfig
    afk: AfkConfig

def load_config() -> Config:
    """Load configuration from YAML file, with defaults for missing values."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    # Strip removed config keys for backward compatibility
    input_data = data.get('input', {})
    input_data.pop('transcription_cleanup', None)
    input_data.pop('cleanup_model', None)

    speech_data = data.get('speech', {})
    speech_data.pop('notify_model', None)

    return Config(
        input=InputConfig(**input_data),
        transcription=TranscriptionConfig(**data.get('transcription', {})),
        speech=SpeechConfig(**speech_data),
        audio=AudioConfig(**data.get('audio', {})),
        overlay=OverlayConfig(**data.get('overlay', {})),
        afk=AfkConfig(**data.get('afk', {})),
    )
