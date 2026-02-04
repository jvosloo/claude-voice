"""Main daemon for Claude Voice - ties all components together."""

import os
import sys

# Ensure print output is unbuffered (visible in log files when running in background)
sys.stdout.reconfigure(line_buffering=True)
import signal
import threading
import json
import numpy as np
import socket

# Suppress multiprocessing resource_tracker warnings on forced shutdown
# This happens when sounddevice's internal semaphores aren't cleaned up
# Must be done BEFORE importing sounddevice which uses multiprocessing
try:
    from multiprocessing import resource_tracker
    # Monkey-patch to prevent the warning on unclean exit
    def _noop_warn(*args, **kwargs):
        pass
    resource_tracker._resource_tracker._warn = _noop_warn
except (ImportError, AttributeError):
    pass

import sounddevice as sd

# Add parent directory to path for imports
sys.path.insert(0, os.path.expanduser("~/.claude-voice"))

from daemon.config import load_config
from daemon.control import ControlServer
from daemon.audio import AudioRecorder
from daemon.transcribe import Transcriber, apply_word_replacements
from daemon.keyboard import KeyboardSimulator
from daemon.hotkey import HotkeyListener
from daemon.cleanup import TranscriptionCleaner
from daemon.tts import TTSEngine
from daemon.notify import classify, play_phrase, stop_playback as stop_notify_playback
from daemon.afk import AfkManager

SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")
MODE_FILE = os.path.expanduser("~/.claude-voice/.mode")
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
ASK_USER_FLAG = os.path.expanduser("/tmp/claude-voice/.ask_user_active")

# Audio cue frequency patterns
CUE_ASCENDING = [440, 660, 880]
CUE_DESCENDING = [880, 660, 440]
CUE_REC_START = [440, 880]
CUE_REC_STOP = [880, 440]
CUE_FADE = 0.005   # fade in/out per tone (seconds)
CUE_VOLUME = 0.3   # amplitude multiplier

_cue_stream: sd.OutputStream | None = None
_cue_lock = threading.Lock()


def _read_mode() -> str:
    """Read the current TTS mode from the mode file. Defaults to notify."""
    if os.path.exists(MODE_FILE):
        try:
            with open(MODE_FILE) as f:
                mode = f.read().strip()
            if mode in ("narrate", "notify"):
                return mode
        except Exception:
            pass
    return "notify"


def _write_mode(mode: str) -> None:
    """Write the current TTS mode to the mode file."""
    with open(MODE_FILE, "w") as f:
        f.write(mode)


def _play_cue(frequencies: list[int], duration: float = 0.05, sample_rate: int = 44100) -> None:
    """Play a short audio cue with the given frequency sequence."""
    global _cue_stream

    def _play():
        global _cue_stream
        samples = []
        for freq in frequencies:
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = np.sin(2 * np.pi * freq * t)
            fade_samples = int(sample_rate * CUE_FADE)
            tone[:fade_samples] *= np.linspace(0, 1, fade_samples)
            tone[-fade_samples:] *= np.linspace(1, 0, fade_samples)
            samples.append(tone)

        audio = np.concatenate(samples).astype(np.float32) * CUE_VOLUME

        with _cue_lock:
            if _cue_stream is None or not _cue_stream.active:
                _cue_stream = sd.OutputStream(
                    samplerate=sample_rate, channels=1, dtype=np.float32,
                )
                _cue_stream.start()
            _cue_stream.write(audio.reshape(-1, 1))

    threading.Thread(target=_play, daemon=True).start()

class VoiceDaemon:
    """Main voice input daemon."""

    def __init__(self):
        self.config = load_config()

        self.recorder = AudioRecorder(
            sample_rate=self.config.audio.sample_rate,
            device=self.config.audio.input_device,
        )

        self.transcriber = Transcriber(
            model_name=self.config.transcription.model,
            device=self.config.transcription.device,
            backend=self.config.transcription.backend,
        )

        self.keyboard = KeyboardSimulator(
            typing_delay=self.config.input.typing_delay,
            auto_submit=self.config.input.auto_submit,
        )

        # Build language cycle list
        self._languages = [self.config.transcription.language]
        if self.config.transcription.extra_languages:
            self._languages += self.config.transcription.extra_languages

        self.hotkey_listener = HotkeyListener(
            hotkey=self.config.input.hotkey,
            on_press=self._on_hotkey_press,
            on_release=self._on_hotkey_release,
            language_hotkey=self.config.input.language_hotkey,
            languages=self._languages,
            on_language_change=self._on_language_change,
            combo_hotkey=self.config.afk.hotkey,
            on_combo=self._toggle_afk,
            combo_hotkey_2=self.config.speech.hotkey,
            on_combo_2=self._toggle_voice,
        )

        self.tts_engine = TTSEngine()
        self._tts_server = None
        self._shutting_down = False
        self._interrupted_tts = False
        self.afk = AfkManager(self.config)

        # Optional transcription cleanup via LLM
        self.cleaner = None
        if self.config.input.transcription_cleanup:
            self.cleaner = TranscriptionCleaner(
                model_name=self.config.input.cleanup_model,
                debug=self.config.input.debug,
            )

    # -- Control socket helpers (called by ControlServer) --

    def get_mode(self) -> str:
        return _read_mode()

    def set_mode(self, mode: str) -> None:
        _write_mode(mode)

    def get_voice_enabled(self) -> bool:
        return not os.path.exists(SILENT_FLAG)

    def set_voice_enabled(self, enabled: bool) -> None:
        if enabled:
            if os.path.exists(SILENT_FLAG):
                os.remove(SILENT_FLAG)
        else:
            with open(SILENT_FLAG, "w") as f:
                pass

    def reload_config(self) -> None:
        old = self.config
        new = load_config()
        changed = []

        # KeyboardSimulator: update in place
        if new.input.typing_delay != old.input.typing_delay:
            self.keyboard.typing_delay = new.input.typing_delay
            changed.append("keyboard(typing_delay)")
        if new.input.auto_submit != old.input.auto_submit:
            self.keyboard.auto_submit = new.input.auto_submit
            changed.append("keyboard(auto_submit)")

        # AudioRecorder: update in place (stream opens lazily per recording)
        if new.audio.sample_rate != old.audio.sample_rate:
            self.recorder.sample_rate = new.audio.sample_rate
            changed.append("audio(sample_rate)")
        if new.audio.input_device != old.audio.input_device:
            self.recorder.device = new.audio.input_device
            changed.append("audio(device)")

        # HotkeyListener: rebuild if hotkey, language hotkey, languages, or AFK hotkey changed
        new_languages = [new.transcription.language]
        if new.transcription.extra_languages:
            new_languages += new.transcription.extra_languages
        hotkey_changed = (
            new.input.hotkey != old.input.hotkey
            or new.input.language_hotkey != old.input.language_hotkey
            or new_languages != self._languages
            or new.afk.hotkey != old.afk.hotkey
            or new.speech.hotkey != old.speech.hotkey
        )
        if hotkey_changed:
            self.hotkey_listener.stop()
            self._languages = new_languages
            self.hotkey_listener = HotkeyListener(
                hotkey=new.input.hotkey,
                on_press=self._on_hotkey_press,
                on_release=self._on_hotkey_release,
                language_hotkey=new.input.language_hotkey,
                languages=self._languages,
                on_language_change=self._on_language_change,
                combo_hotkey=new.afk.hotkey,
                on_combo=self._toggle_afk,
                combo_hotkey_2=new.speech.hotkey,
                on_combo_2=self._toggle_voice,
            )
            self.hotkey_listener.start()
            changed.append("hotkey_listener")

        # Transcriber: reset model if model name or backend changed
        if (new.transcription.model != old.transcription.model
                or new.transcription.backend != old.transcription.backend):
            self.transcriber._model = None
            self.transcriber.model_name = new.transcription.model
            self.transcriber.backend = new.transcription.backend
            self.transcriber.device = new.transcription.device
            changed.append("transcriber(model reset)")
        elif new.transcription.device != old.transcription.device:
            self.transcriber.device = new.transcription.device
            changed.append("transcriber(device)")

        # TranscriptionCleaner: recreate if settings changed, destroy if disabled
        if new.input.transcription_cleanup:
            if (not old.input.transcription_cleanup
                    or new.input.cleanup_model != old.input.cleanup_model
                    or new.input.debug != old.input.debug):
                self.cleaner = TranscriptionCleaner(
                    model_name=new.input.cleanup_model,
                    debug=new.input.debug,
                )
                if not self.cleaner.ensure_ready():
                    self.cleaner = None
                    changed.append("cleaner(failed)")
                else:
                    changed.append("cleaner(recreated)")
        elif old.input.transcription_cleanup:
            self.cleaner = None
            changed.append("cleaner(disabled)")

        # Overlay: re-init if style changed
        if new.overlay.style != old.overlay.style and new.overlay.enabled:
            from daemon import overlay
            overlay.update_style(style=new.overlay.style)
            changed.append("overlay")

        # Notify phrases: regenerate if voice/speed/lang_code changed
        voice_changed = (
            new.speech.voice != old.speech.voice
            or new.speech.speed != old.speech.speed
            or new.speech.lang_code != old.speech.lang_code
            or new.speech.notify_phrases != old.speech.notify_phrases
        )
        if voice_changed:
            from daemon.notify import regenerate_custom_phrases
            regenerate_custom_phrases(
                new.speech.notify_phrases,
                voice=new.speech.voice,
                speed=new.speech.speed,
                lang_code=new.speech.lang_code,
                interactive=False,
            )
            changed.append("notify_phrases")

        # AfkManager: recreate with new config
        if (new.afk.telegram.bot_token != old.afk.telegram.bot_token
                or new.afk.telegram.chat_id != old.afk.telegram.chat_id):
            was_active = self.afk.active
            self.afk.stop_listening()
            self.afk = AfkManager(new)
            if self.afk.is_configured:
                ok, reason = self.afk.start_listening(on_toggle=self._toggle_afk)
                if not ok:
                    print(f"Telegram: failed to connect ({reason})")
                    from daemon import overlay
                    overlay.show_flash(f"Telegram: {reason}")
                elif was_active:
                    self.afk.activate()
            changed.append("afk")

        self.config = new
        summary = ", ".join(changed) if changed else "no components changed"
        print(f"Config reloaded: {summary}")

    def _on_language_change(self, lang: str) -> None:
        """Called when language is cycled."""
        code = lang.upper()
        print(f"Language: {code}")
        _play_cue(CUE_ASCENDING)
        from daemon import overlay
        overlay.show_language_flash(code)

    def _on_hotkey_press(self) -> None:
        """Called when hotkey is pressed - start recording."""
        # Start recording FIRST - minimize latency
        self.recorder.start()
        # Play ascending cue to signal recording started
        _play_cue(CUE_REC_START)
        print("Recording...")
        # Show language label on overlay if not default language
        lang = self.hotkey_listener.active_language
        default_lang = self._languages[0]
        label = lang.upper() if lang != default_lang else None
        # Show overlay
        from daemon import overlay
        overlay.show_recording(label=label)
        # Stop any TTS playback
        self._interrupted_tts = self.tts_engine.stop_playback()
        if not self._interrupted_tts:
            self._interrupted_tts = stop_notify_playback()

    def _handle_voice_command(self, text: str) -> bool:
        """Check for voice commands. Returns True if command was handled."""
        text_lower = text.lower().strip().rstrip('.')

        # Stop speaking commands
        if text_lower in ["stop speaking", "stop talking"]:
            with open(SILENT_FLAG, 'w') as f:
                pass
            print("Voice output disabled")
            return True

        # Start speaking commands
        if text_lower in ["start speaking", "start talking"]:
            if os.path.exists(SILENT_FLAG):
                os.remove(SILENT_FLAG)
            print("Voice output enabled")
            return True

        # Mode switching commands
        if text_lower in ["switch to narrate mode", "switch to narration mode"]:
            _write_mode("narrate")
            print("Switched to narrate mode")
            return True

        if text_lower in ["switch to notify mode", "switch to notification mode"]:
            _write_mode("notify")
            print("Switched to notify mode")
            return True

        # AFK mode commands
        if text_lower in self.config.afk.voice_commands_activate:
            self._activate_afk()
            return True

        if text_lower in self.config.afk.voice_commands_deactivate:
            self._deactivate_afk()
            return True

        return False

    def _activate_afk(self) -> None:
        """Activate AFK mode with cue and overlay feedback."""
        from daemon import overlay
        if not self.afk.is_configured:
            print("AFK mode: Telegram not configured")
            return
        if self.afk.active:
            print("Already in AFK mode")
            return
        self.afk._previous_mode = _read_mode()
        _write_mode("afk")
        if self.afk.activate():
            _play_cue(CUE_ASCENDING)
            overlay.show_flash("AFK")
            print("AFK mode activated")
        else:
            _write_mode(self.afk._previous_mode or "notify")
            print("AFK mode: Telegram not connected")

    def _deactivate_afk(self) -> None:
        """Deactivate AFK mode, restore previous voice mode, with feedback."""
        from daemon import overlay
        if not self.afk.active:
            return
        previous = self.afk._previous_mode or "notify"
        self.afk.deactivate()
        _write_mode(previous)
        _play_cue(CUE_DESCENDING)
        overlay.show_flash("AFK OFF")
        print(f"AFK mode deactivated, restored {previous} mode")

    def _toggle_afk(self) -> None:
        """Toggle AFK mode on/off."""
        if self.afk.active:
            self._deactivate_afk()
        else:
            self._activate_afk()

    def _toggle_voice(self) -> None:
        """Toggle voice output on/off via speech hotkey."""
        from daemon import overlay
        enabled = not self.get_voice_enabled()
        self.set_voice_enabled(enabled)
        _play_cue(CUE_ASCENDING if enabled else CUE_DESCENDING)
        overlay.show_flash("VOICE ON" if enabled else "VOICE OFF")
        print(f"Voice output {'enabled' if enabled else 'disabled'} (hotkey)")
        if hasattr(self, 'control_server'):
            self.control_server.emit({"event": "voice_changed", "enabled": enabled})

    def _run_tts_server(self) -> None:
        """Run Unix socket server for TTS requests from the hook."""
        # Clean up stale socket file
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(TTS_SOCK_PATH)
        server.listen(5)
        server.settimeout(1.0)  # Allow periodic shutdown checks

        self._tts_server = server

        while not self._shutting_down:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            conn_closed = False
            try:
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk

                if not data:
                    continue

                request = json.loads(data.decode())

                # Check if this is an AFK-eligible request
                session = request.get("session")

                if self.afk.active and session:
                    # Route through AFK manager
                    response = self.afk.handle_hook_request(request)
                    # Send response back to hook
                    conn.sendall(json.dumps(response).encode())
                    conn.close()
                    conn_closed = True
                    continue

                # Not AFK - send non-waiting response and handle normally
                if session:
                    conn.sendall(json.dumps({"wait": False}).encode())
                conn.close()
                conn_closed = True

                # Direct category from hooks (e.g. PreToolUse permission)
                notify_category = request.get("notify_category")
                if notify_category:
                    print(f"Notify: {notify_category}")
                    play_phrase(notify_category, self.config.speech.notify_phrases)
                    continue

                text = request.get("text", "")
                voice = request.get("voice", self.config.speech.voice)
                speed = request.get("speed", self.config.speech.speed)
                lang_code = request.get("lang_code", self.config.speech.lang_code)

                if text:
                    mode = _read_mode()
                    if mode == "notify":
                        category = classify(text)
                        print(f"Notify: {category}")
                        play_phrase(category, self.config.speech.notify_phrases)
                    else:
                        self.tts_engine.speak(text, voice=voice, speed=speed, lang_code=lang_code)
            except Exception as e:
                print(f"TTS server error: {e}")
            finally:
                if not conn_closed:
                    try:
                        conn.close()
                    except Exception:
                        pass

        server.close()
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)

    def _on_hotkey_release(self) -> None:
        """Called when hotkey is released - stop, transcribe, type."""
        from daemon import overlay

        audio = self.recorder.stop()
        # Play descending cue to signal recording stopped
        _play_cue(CUE_REC_STOP)
        duration = self.recorder.get_duration(audio)

        if duration < self.config.input.min_audio_length:
            overlay.hide()
            if duration > 0.1 and not self._interrupted_tts:
                print(f"Too short ({duration:.1f}s), ignoring")
            return

        overlay.show_transcribing()
        print(f"Transcribing {duration:.1f}s of audio...")
        text = self.transcriber.transcribe(audio, language=self.hotkey_listener.active_language)

        if not text:
            overlay.hide()
            print("No speech detected")
            return

        # Apply word replacements (deterministic, before LLM cleanup)
        if self.config.transcription.word_replacements:
            replaced = apply_word_replacements(text, self.config.transcription.word_replacements)
            if replaced != text:
                print(f"Whisper:   {text}")
                print(f"Replaced:  {replaced}")
                text = replaced

        # Clean up transcription if enabled
        if self.cleaner:
            original = text
            text = self.cleaner.cleanup(text)
            print(f"Whisper: {original}")
            if text != original:
                print(f"Cleaned: {text}")
            else:
                print("Cleaned: (no changes)")

        # Check for voice commands first
        if self._handle_voice_command(text):
            overlay.hide()
            return

        print(f"Typing:  {text}")
        print()
        self.keyboard.type_text(text + " ")
        overlay.hide()

    def _shutdown(self) -> None:
        """Clean shutdown of the daemon."""
        global _cue_stream
        print("\nShutting down...")
        if self.afk.active:
            self.afk.deactivate()
        self.afk.stop_listening()
        self._shutting_down = True

        # Close audio cue stream
        with _cue_lock:
            if _cue_stream is not None:
                try:
                    _cue_stream.stop()
                    _cue_stream.close()
                except Exception:
                    pass
                _cue_stream = None

        # Hide overlay
        from daemon import overlay
        overlay.hide()

        if hasattr(self, "control_server"):
            self.control_server.shutdown()

        if self._tts_server:
            try:
                self._tts_server.close()
            except Exception:
                pass
        if os.path.exists(TTS_SOCK_PATH):
            os.unlink(TTS_SOCK_PATH)
        self.hotkey_listener.stop()
        self.recorder.shutdown()

        # Cocoa run loop exits via self._shutting_down flag

        # Kill the multiprocessing resource_tracker to prevent semaphore warnings
        # It's a separate subprocess that prints warnings after we exit
        try:
            from multiprocessing import resource_tracker
            tracker = resource_tracker._resource_tracker
            if tracker._pid is not None:
                os.kill(tracker._pid, signal.SIGKILL)
        except:
            pass

        # Exit immediately without Python's cleanup
        os._exit(0)

    def run(self) -> None:
        """Start the daemon."""
        # Handle SIGTERM (from kill command) and SIGINT (Ctrl+C) gracefully
        # SIGINT must be explicit because NSApplication.run() swallows KeyboardInterrupt
        signal.signal(signal.SIGTERM, lambda sig, frame: self._shutdown())
        signal.signal(signal.SIGINT, lambda sig, frame: self._shutdown())

        print("=" * 50)
        print("Claude Voice Daemon")
        print("=" * 50)
        print(f"Hotkey: {self.config.input.hotkey} (hold to record)")
        if self.config.input.language_hotkey and self.config.transcription.extra_languages:
            print(f"Language hotkey: {self.config.input.language_hotkey} (cycle languages)")
            print(f"Languages: {', '.join(self._languages)}")
        print(f"Model: {self.config.transcription.model}")
        if self.config.transcription.extra_languages:
            model = self.config.transcription.model
            if model.endswith(".en"):
                print(f"WARNING: Model '{model}' only supports English.")
                print(f"  Extra languages {self.config.transcription.extra_languages} require a multilingual model (e.g. large-v3).")
        print("Press Ctrl+C to stop")
        print("=" * 50)

        # Initialize mode from config (only if no mode file exists yet)
        # Reset "afk" mode — AFK is never active at startup, so a stale
        # mode file from a previous session must not persist.
        if not os.path.exists(MODE_FILE):
            _write_mode(self.config.speech.mode)
        elif _read_mode() == "afk":
            _write_mode(self.config.speech.mode)

        # Clean stale ask-user flag from a previous crash
        if os.path.exists(ASK_USER_FLAG):
            try:
                os.remove(ASK_USER_FLAG)
            except OSError:
                pass
        print(f"TTS mode: {_read_mode()}")
        if self.afk.is_configured:
            print(f"AFK mode: configured (Telegram)")
        else:
            print(f"AFK mode: not configured (set telegram bot_token and chat_id)")

        # Initialize overlay (creates window, but Cocoa run loop isn't running yet
        # so animations won't play until later)
        overlay_cfg = self.config.overlay
        if overlay_cfg.enabled:
            from daemon import overlay
            overlay.init(style=overlay_cfg.style)

        # Interactive prompts run on main thread BEFORE Cocoa steals focus
        is_foreground = sys.stdin.isatty()
        if is_foreground:
            # Pre-load models so sound check can play
            self.transcriber._ensure_model()
            if self.config.speech.enabled:
                self.tts_engine._ensure_model()

                print('\nSound check: playing "Hello!! Can you hear me?"')
                self.tts_engine.speak(
                    "Hello!! Can you hear me?",
                    voice=self.config.speech.voice,
                    speed=self.config.speech.speed,
                    lang_code=self.config.speech.lang_code,
                )
                answer = input("Did you hear the test phrase? [Y/n] (default: Y) ").strip().lower()
                if answer in ("n", "no"):
                    print("Tip: check your audio output device and volume settings.")
                    print("Continuing startup anyway...\n")
                else:
                    print("Sound check passed.\n")

            # Regenerate custom notify phrases if needed
            if self.config.speech.mode == "notify" or self.config.speech.notify_phrases:
                from daemon.notify import regenerate_custom_phrases
                regenerate_custom_phrases(
                    self.config.speech.notify_phrases,
                    voice=self.config.speech.voice,
                    speed=self.config.speech.speed,
                    lang_code=self.config.speech.lang_code,
                    interactive=True,
                )

        def _finish_startup():
            """Heavy startup work (model loading, etc.) — runs in background thread."""
            # Pre-load models (skip if already done in interactive mode above)
            if not is_foreground:
                self.transcriber._ensure_model()
                if self.config.speech.enabled:
                    self.tts_engine._ensure_model()

                # Regenerate custom notify phrases if needed
                if self.config.speech.mode == "notify" or self.config.speech.notify_phrases:
                    from daemon.notify import regenerate_custom_phrases
                    regenerate_custom_phrases(
                        self.config.speech.notify_phrases,
                        voice=self.config.speech.voice,
                        speed=self.config.speech.speed,
                        lang_code=self.config.speech.lang_code,
                        interactive=False,
                    )

            # Check transcription cleanup if enabled
            if self.cleaner:
                if not self.cleaner.ensure_ready():
                    self.cleaner = None  # Disable on failure

            print("Ready! Hold the hotkey and speak.")
            print()

            # Start TTS socket server
            tts_thread = threading.Thread(target=self._run_tts_server, daemon=True)
            tts_thread.start()
            print(f"TTS server listening on {TTS_SOCK_PATH}")

            # Start control socket server (for external app communication)
            self.control_server = ControlServer(self)
            control_thread = threading.Thread(target=self.control_server.run, daemon=True)
            control_thread.start()
            print("Control server listening on ~/.claude-voice/.control.sock")

            # Start Telegram polling (always-on for /afk command)
            if self.afk.is_configured:
                ok, reason = self.afk.start_listening(on_toggle=self._toggle_afk)
                if ok:
                    print("Telegram: listening for /afk command")
                else:
                    print(f"Telegram: failed to connect ({reason})")
                    overlay.show_flash(f"Telegram: {reason}")

            # Start hotkey listener on background thread
            self.hotkey_listener.start()

            # Startup complete
            _play_cue(CUE_ASCENDING)
            if overlay_cfg.enabled:
                overlay.show_flash("Claude Voice Started")

        if overlay_cfg.enabled:
            # Run startup in background so Cocoa run loop can drive overlay animations
            threading.Thread(target=_finish_startup, daemon=True).start()

            # Run Cocoa run loop on main thread (required for NSWindow)
            # Manual run loop instead of NSApplication.run() because the
            # latter overrides Python's SIGINT handler, breaking Ctrl+C.
            from AppKit import NSApplication, NSDate
            from Foundation import NSRunLoop
            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
            app.finishLaunching()
            run_loop = NSRunLoop.currentRunLoop()
            while not self._shutting_down:
                run_loop.runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(0.2)
                )
        else:
            # No overlay — run startup synchronously
            _finish_startup()
            try:
                self.hotkey_listener.join()
            except KeyboardInterrupt:
                self._shutdown()

def main():
    daemon = VoiceDaemon()
    daemon.run()

if __name__ == "__main__":
    main()
