"""Tests for hot-reload config in daemon/main.py (VoiceDaemon.reload_config)."""

import sys
from copy import deepcopy
from unittest.mock import patch, MagicMock, call

# Mock external libraries that need system resources at import time.
sys.modules.setdefault('sounddevice', MagicMock())
sys.modules.setdefault('pynput', MagicMock())
sys.modules.setdefault('pynput.keyboard', MagicMock())

from daemon.config import (
    Config, InputConfig, TranscriptionConfig, SpeechConfig,
    AudioConfig, OverlayConfig, AfkConfig, AfkTelegramConfig,
)
from daemon.main import VoiceDaemon


def _default_config(**overrides) -> Config:
    """Build a default Config, merging section-level overrides."""
    sections = {
        "input": InputConfig(),
        "transcription": TranscriptionConfig(),
        "speech": SpeechConfig(),
        "audio": AudioConfig(),
        "overlay": OverlayConfig(enabled=False),
        "afk": AfkConfig(),
    }
    for key, val in overrides.items():
        sections[key] = val
    return Config(**sections)


def _make_daemon(config=None) -> VoiceDaemon:
    """Create a VoiceDaemon with mocked components."""
    with patch.object(VoiceDaemon, '__init__', lambda self: None):
        d = VoiceDaemon()
    d.config = config or _default_config()
    d.keyboard = MagicMock()
    d.keyboard.typing_delay = d.config.input.typing_delay
    d.keyboard.auto_submit = d.config.input.auto_submit
    d.recorder = MagicMock()
    d.recorder.sample_rate = d.config.audio.sample_rate
    d.recorder.device = d.config.audio.input_device
    d.transcriber = MagicMock()
    d.transcriber.model_name = d.config.transcription.model
    d.transcriber.backend = d.config.transcription.backend
    d.transcriber.device = d.config.transcription.device
    d.transcriber._model = "loaded_model"
    d.hotkey_listener = MagicMock()
    d.cleaner = None
    d.afk = MagicMock()
    d.afk.active = False
    d.afk.is_configured = False
    d._languages = [d.config.transcription.language]
    if d.config.transcription.extra_languages:
        d._languages += d.config.transcription.extra_languages
    return d


class TestReloadConfigNoChanges:

    def test_no_changes_leaves_components_untouched(self):
        cfg = _default_config()
        d = _make_daemon(cfg)
        old_listener = d.hotkey_listener
        old_transcriber_model = d.transcriber._model

        with patch("daemon.main.load_config", return_value=deepcopy(cfg)):
            d.reload_config()

        assert d.hotkey_listener is old_listener
        d.hotkey_listener.stop.assert_not_called()
        assert d.transcriber._model == old_transcriber_model
        assert d.cleaner is None

    def test_no_changes_prints_summary(self, capsys):
        cfg = _default_config()
        d = _make_daemon(cfg)

        with patch("daemon.main.load_config", return_value=deepcopy(cfg)):
            d.reload_config()

        assert "no components changed" in capsys.readouterr().out


class TestReloadKeyboard:

    def test_typing_delay_updated(self):
        d = _make_daemon()
        new_cfg = _default_config(input=InputConfig(typing_delay=0.01))

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.keyboard.typing_delay == 0.01

    def test_auto_submit_updated(self):
        d = _make_daemon()
        new_cfg = _default_config(input=InputConfig(auto_submit=True))

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.keyboard.auto_submit is True

    def test_unchanged_keyboard_not_touched(self):
        cfg = _default_config()
        d = _make_daemon(cfg)
        original_delay = d.keyboard.typing_delay

        with patch("daemon.main.load_config", return_value=deepcopy(cfg)):
            d.reload_config()

        assert d.keyboard.typing_delay == original_delay


class TestReloadAudio:

    def test_sample_rate_updated(self):
        d = _make_daemon()
        new_cfg = _default_config(audio=AudioConfig(sample_rate=44100))

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.recorder.sample_rate == 44100

    def test_input_device_updated(self):
        d = _make_daemon()
        new_cfg = _default_config(audio=AudioConfig(input_device=3))

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.recorder.device == 3


class TestReloadHotkey:

    def test_hotkey_change_rebuilds_listener(self):
        d = _make_daemon()
        old_listener = d.hotkey_listener
        new_cfg = _default_config(input=InputConfig(hotkey="left_alt"))

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.HotkeyListener") as MockHL:
            MockHL.return_value = MagicMock()
            d.reload_config()

        old_listener.stop.assert_called_once()
        MockHL.assert_called_once()
        MockHL.return_value.start.assert_called_once()
        assert d.hotkey_listener is MockHL.return_value

    def test_language_hotkey_change_rebuilds_listener(self):
        d = _make_daemon()
        old_listener = d.hotkey_listener
        new_cfg = _default_config(input=InputConfig(language_hotkey="right_cmd"))

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.HotkeyListener") as MockHL:
            MockHL.return_value = MagicMock()
            d.reload_config()

        old_listener.stop.assert_called_once()
        MockHL.assert_called_once()

    def test_extra_languages_change_rebuilds_listener(self):
        d = _make_daemon()
        new_cfg = _default_config(
            transcription=TranscriptionConfig(extra_languages=["af", "de"]),
        )

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.HotkeyListener") as MockHL:
            MockHL.return_value = MagicMock()
            d.reload_config()

        assert d._languages == ["en", "af", "de"]
        MockHL.assert_called_once()

    def test_afk_hotkey_change_rebuilds_listener(self):
        d = _make_daemon()
        new_cfg = _default_config(afk=AfkConfig(hotkey="left_alt+b"))

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.HotkeyListener") as MockHL:
            MockHL.return_value = MagicMock()
            d.reload_config()

        MockHL.assert_called_once()

    def test_unchanged_hotkey_not_rebuilt(self):
        cfg = _default_config()
        d = _make_daemon(cfg)
        old_listener = d.hotkey_listener

        with patch("daemon.main.load_config", return_value=deepcopy(cfg)):
            d.reload_config()

        old_listener.stop.assert_not_called()
        assert d.hotkey_listener is old_listener

    def test_rebuilt_listener_receives_correct_callbacks(self):
        d = _make_daemon()
        new_cfg = _default_config(input=InputConfig(hotkey="left_alt"))

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.HotkeyListener") as MockHL:
            MockHL.return_value = MagicMock()
            d.reload_config()

        kwargs = MockHL.call_args
        assert kwargs[1]["on_press"] == d._on_hotkey_press
        assert kwargs[1]["on_release"] == d._on_hotkey_release
        assert kwargs[1]["on_language_change"] == d._on_language_change
        assert kwargs[1]["on_combo"] == d._toggle_afk

    def test_speech_hotkey_change_rebuilds_listener(self):
        d = _make_daemon()
        old_listener = d.hotkey_listener
        new_cfg = _default_config(speech=SpeechConfig(hotkey="right_alt+v"))

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.HotkeyListener") as MockHL:
            MockHL.return_value = MagicMock()
            d.reload_config()

        old_listener.stop.assert_called_once()
        MockHL.assert_called_once()
        MockHL.return_value.start.assert_called_once()

    def test_speech_hotkey_passed_to_listener(self):
        d = _make_daemon()
        new_cfg = _default_config(speech=SpeechConfig(hotkey="right_alt+v"))

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.HotkeyListener") as MockHL:
            MockHL.return_value = MagicMock()
            d.reload_config()

        kwargs = MockHL.call_args[1]
        assert kwargs["combo_hotkey_2"] == "right_alt+v"
        assert kwargs["on_combo_2"] == d._toggle_voice

    def test_speech_hotkey_none_does_not_trigger_rebuild(self):
        """When speech.hotkey stays at default, no rebuild needed."""
        cfg = _default_config()
        d = _make_daemon(cfg)
        old_listener = d.hotkey_listener

        with patch("daemon.main.load_config", return_value=deepcopy(cfg)):
            d.reload_config()

        old_listener.stop.assert_not_called()
        assert d.hotkey_listener is old_listener


class TestToggleVoice:

    def test_toggle_voice_disables_when_enabled(self):
        d = _make_daemon()
        d.control_server = MagicMock()
        with patch.object(d, 'get_voice_enabled', return_value=True), \
             patch.object(d, 'set_voice_enabled') as mock_set:
            d._toggle_voice()
        mock_set.assert_called_once_with(False)

    def test_toggle_voice_enables_when_disabled(self):
        d = _make_daemon()
        d.control_server = MagicMock()
        with patch.object(d, 'get_voice_enabled', return_value=False), \
             patch.object(d, 'set_voice_enabled') as mock_set:
            d._toggle_voice()
        mock_set.assert_called_once_with(True)

    def test_toggle_voice_emits_event(self):
        d = _make_daemon()
        d.control_server = MagicMock()
        with patch.object(d, 'get_voice_enabled', return_value=True), \
             patch.object(d, 'set_voice_enabled'):
            d._toggle_voice()
        d.control_server.emit.assert_called_once_with(
            {"event": "voice_changed", "enabled": False}
        )

    def test_toggle_voice_on_plays_ascending_cue(self):
        d = _make_daemon()
        d.control_server = MagicMock()
        with patch.object(d, 'get_voice_enabled', return_value=False), \
             patch.object(d, 'set_voice_enabled'), \
             patch("daemon.main._play_cue") as mock_cue:
            d._toggle_voice()
        from daemon.main import CUE_ASCENDING
        mock_cue.assert_called_once_with(CUE_ASCENDING)

    def test_toggle_voice_off_plays_descending_cue(self):
        d = _make_daemon()
        d.control_server = MagicMock()
        with patch.object(d, 'get_voice_enabled', return_value=True), \
             patch.object(d, 'set_voice_enabled'), \
             patch("daemon.main._play_cue") as mock_cue:
            d._toggle_voice()
        from daemon.main import CUE_DESCENDING
        mock_cue.assert_called_once_with(CUE_DESCENDING)

    def test_toggle_voice_on_shows_overlay_flash(self):
        d = _make_daemon()
        d.control_server = MagicMock()
        with patch.object(d, 'get_voice_enabled', return_value=False), \
             patch.object(d, 'set_voice_enabled'), \
             patch("daemon.main._play_cue"), \
             patch("daemon.overlay.show_flash") as mock_flash:
            d._toggle_voice()
        mock_flash.assert_called_once_with("VOICE ON")

    def test_toggle_voice_off_shows_overlay_flash(self):
        d = _make_daemon()
        d.control_server = MagicMock()
        with patch.object(d, 'get_voice_enabled', return_value=True), \
             patch.object(d, 'set_voice_enabled'), \
             patch("daemon.main._play_cue"), \
             patch("daemon.overlay.show_flash") as mock_flash:
            d._toggle_voice()
        mock_flash.assert_called_once_with("VOICE OFF")


class TestReloadTranscriber:

    def test_model_change_resets_model(self):
        d = _make_daemon()
        new_cfg = _default_config(
            transcription=TranscriptionConfig(model="tiny.en"),
        )

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.transcriber._model is None
        assert d.transcriber.model_name == "tiny.en"

    def test_backend_change_resets_model(self):
        d = _make_daemon()
        new_cfg = _default_config(
            transcription=TranscriptionConfig(backend="faster-whisper"),
        )

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.transcriber._model is None
        assert d.transcriber.backend == "faster-whisper"

    def test_device_only_change_keeps_model(self):
        d = _make_daemon()
        new_cfg = _default_config(
            transcription=TranscriptionConfig(device="cuda"),
        )

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.transcriber._model == "loaded_model"
        assert d.transcriber.device == "cuda"

    def test_unchanged_transcriber_not_touched(self):
        cfg = _default_config()
        d = _make_daemon(cfg)

        with patch("daemon.main.load_config", return_value=deepcopy(cfg)):
            d.reload_config()

        assert d.transcriber._model == "loaded_model"


class TestReloadCleaner:

    def test_enable_cleanup_creates_cleaner(self):
        d = _make_daemon()
        assert d.cleaner is None
        new_cfg = _default_config(
            input=InputConfig(transcription_cleanup=True, cleanup_model="qwen2.5:1.5b"),
        )

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.TranscriptionCleaner") as MockTC:
            MockTC.return_value = MagicMock()
            d.reload_config()

        MockTC.assert_called_once_with(model_name="qwen2.5:1.5b", debug=False)
        assert d.cleaner is MockTC.return_value

    def test_disable_cleanup_removes_cleaner(self):
        old_cfg = _default_config(
            input=InputConfig(transcription_cleanup=True, cleanup_model="qwen2.5:1.5b"),
        )
        d = _make_daemon(old_cfg)
        d.cleaner = MagicMock()  # was enabled
        new_cfg = _default_config(input=InputConfig(transcription_cleanup=False))

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.cleaner is None

    def test_change_cleanup_model_recreates(self):
        old_cfg = _default_config(
            input=InputConfig(transcription_cleanup=True, cleanup_model="qwen2.5:1.5b"),
        )
        d = _make_daemon(old_cfg)
        d.cleaner = MagicMock()
        new_cfg = _default_config(
            input=InputConfig(transcription_cleanup=True, cleanup_model="llama3:8b"),
        )

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.TranscriptionCleaner") as MockTC:
            MockTC.return_value = MagicMock()
            d.reload_config()

        MockTC.assert_called_once_with(model_name="llama3:8b", debug=False)

    def test_unchanged_cleanup_not_recreated(self):
        old_cfg = _default_config(
            input=InputConfig(transcription_cleanup=True, cleanup_model="qwen2.5:1.5b"),
        )
        d = _make_daemon(old_cfg)
        original_cleaner = MagicMock()
        d.cleaner = original_cleaner

        with patch("daemon.main.load_config", return_value=deepcopy(old_cfg)):
            d.reload_config()

        assert d.cleaner is original_cleaner


class TestReloadOverlay:

    def test_style_change_reinits_overlay(self):
        old_cfg = _default_config(overlay=OverlayConfig(enabled=True))
        d = _make_daemon(old_cfg)
        new_cfg = _default_config(
            overlay=OverlayConfig(enabled=True, style="frosted"),
        )

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.overlay.update_style") as mock_update:
            d.reload_config()

        mock_update.assert_called_once_with(style="frosted")

    def test_overlay_disabled_skips_reinit(self):
        old_cfg = _default_config(overlay=OverlayConfig(enabled=False))
        d = _make_daemon(old_cfg)
        new_cfg = _default_config(
            overlay=OverlayConfig(enabled=False, style="frosted"),
        )

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.overlay.update_style") as mock_update:
            d.reload_config()

        mock_update.assert_not_called()

    def test_unchanged_overlay_not_reinited(self):
        old_cfg = _default_config(overlay=OverlayConfig(enabled=True))
        d = _make_daemon(old_cfg)

        with patch("daemon.main.load_config", return_value=deepcopy(old_cfg)), \
             patch("daemon.overlay.update_style") as mock_update:
            d.reload_config()

        mock_update.assert_not_called()


class TestReloadAfk:

    def test_telegram_credentials_change_rebuilds_afk(self):
        old_cfg = _default_config(
            afk=AfkConfig(telegram=AfkTelegramConfig(bot_token="old", chat_id="123")),
        )
        d = _make_daemon(old_cfg)
        old_afk = d.afk
        new_cfg = _default_config(
            afk=AfkConfig(telegram=AfkTelegramConfig(bot_token="new", chat_id="123")),
        )

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.AfkManager") as MockAM:
            new_afk = MagicMock()
            new_afk.is_configured = True
            MockAM.return_value = new_afk
            d.reload_config()

        old_afk.stop_listening.assert_called_once()
        MockAM.assert_called_once_with(new_cfg)
        new_afk.start_listening.assert_called_once()
        assert d.afk is new_afk

    def test_afk_preserves_active_state(self):
        old_cfg = _default_config(
            afk=AfkConfig(telegram=AfkTelegramConfig(bot_token="old", chat_id="123")),
        )
        d = _make_daemon(old_cfg)
        d.afk.active = True
        new_cfg = _default_config(
            afk=AfkConfig(telegram=AfkTelegramConfig(bot_token="new", chat_id="123")),
        )

        with patch("daemon.main.load_config", return_value=new_cfg), \
             patch("daemon.main.AfkManager") as MockAM:
            new_afk = MagicMock()
            new_afk.is_configured = True
            MockAM.return_value = new_afk
            d.reload_config()

        new_afk.activate.assert_called_once()

    def test_unchanged_afk_not_rebuilt(self):
        cfg = _default_config(
            afk=AfkConfig(telegram=AfkTelegramConfig(bot_token="tok", chat_id="123")),
        )
        d = _make_daemon(cfg)
        old_afk = d.afk

        with patch("daemon.main.load_config", return_value=deepcopy(cfg)):
            d.reload_config()

        old_afk.stop_listening.assert_not_called()
        assert d.afk is old_afk


class TestReloadConfigStoresNew:

    def test_config_replaced_after_reload(self):
        d = _make_daemon()
        new_cfg = _default_config(input=InputConfig(typing_delay=0.05))

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        assert d.config is new_cfg

    def test_summary_lists_changed_components(self, capsys):
        d = _make_daemon()
        new_cfg = _default_config(
            input=InputConfig(typing_delay=0.01, auto_submit=True),
            audio=AudioConfig(sample_rate=44100),
        )

        with patch("daemon.main.load_config", return_value=new_cfg):
            d.reload_config()

        out = capsys.readouterr().out
        assert "keyboard(typing_delay)" in out
        assert "keyboard(auto_submit)" in out
        assert "audio(sample_rate)" in out
