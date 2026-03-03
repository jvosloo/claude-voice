"""Main daemon for Claude Voice - ties all components together."""

import os
import stat
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
from daemon.transcribe import Transcriber, apply_word_replacements, strip_filler_words
from daemon.keyboard import KeyboardSimulator
from daemon.hotkey import HotkeyListener
from daemon.summarize import ResponseSummarizer
from daemon.tts import create_tts_engine
from daemon.notify import classify, play_phrase, stop_playback as stop_notify_playback

SILENT_FLAG = os.path.expanduser("~/.claude-voice/.silent")
TTS_SOCK_PATH = os.path.expanduser("~/.claude-voice/.tts.sock")
ASK_USER_FLAG = os.path.expanduser("/tmp/claude-voice/.ask_user_active")

# Audio cue frequency patterns
CUE_ASCENDING = [440, 660, 880]
CUE_DESCENDING = [880, 660, 440]
CUE_REC_START = [440, 880]
CUE_REC_STOP = [880, 440]
CUE_FADE = 0.005   # fade in/out per tone (seconds)
CUE_VOLUME = 0.15  # amplitude multiplier

# Pre-computed audio arrays keyed by frequency tuple — populated by _init_cue_cache()
_cue_cache: dict[tuple[int, ...], np.ndarray] = {}
_cue_stream: sd.OutputStream | None = None
_cue_lock = threading.Lock()


def _init_cue_cache(duration: float = 0.05, sample_rate: int = 44100) -> None:
    """Pre-compute cue audio arrays so _play_cue has zero work at play time."""
    for freqs in [CUE_ASCENDING, CUE_DESCENDING, CUE_REC_START, CUE_REC_STOP]:
        samples = []
        for freq in freqs:
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = np.sin(2 * np.pi * freq * t)
            fade_samples = int(sample_rate * CUE_FADE)
            tone[:fade_samples] *= np.linspace(0, 1, fade_samples)
            tone[-fade_samples:] *= np.linspace(1, 0, fade_samples)
            samples.append(tone)
        audio = np.concatenate(samples).astype(np.float32) * CUE_VOLUME
        _cue_cache[tuple(freqs)] = audio.reshape(-1, 1)


def _read_mode(config=None) -> str:
    """Read the current TTS mode from config."""
    if config:
        return config.speech.mode

    # Fallback: read config file directly (for module-level calls)
    try:
        import yaml
        config_path = os.path.expanduser("~/.claude-voice/config.yaml")
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("speech", {}).get("mode", "notify")
    except (OSError, ImportError):
        return "notify"


def _play_cue(frequencies: list[int]) -> None:
    """Play a pre-cached audio cue via sounddevice (instant, respects system volume)."""
    global _cue_stream
    audio = _cue_cache.get(tuple(frequencies))
    if audio is None:
        return

    def _play():
        global _cue_stream
        with _cue_lock:
            if _cue_stream is None or not _cue_stream.active:
                _cue_stream = sd.OutputStream(
                    samplerate=44100, channels=1, dtype=np.float32,
                )
                _cue_stream.start()
            _cue_stream.write(audio)

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
            language_backends=self.config.transcription.language_backends,
            openai_api_key=self.config.speech.openai_api_key,
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
            combo_hotkey=self.config.speech.hotkey,
            on_combo=self._toggle_voice,
        )

        self.tts_engine = create_tts_engine(
            engine=self.config.speech.engine,
            api_key=self.config.speech.openai_api_key,
            model=self.config.speech.openai_model,
        )
        self._tts_server = None
        self._shutting_down = False
        self._interrupted_tts = False
        self._ready = False  # Set True when fully initialized

        # Response summarizer for narrate mode
        self.summarizer = ResponseSummarizer(
            model_name=self.config.speech.summarize_model,
            debug=self.config.input.debug,
        )

    # -- Control socket helpers (called by ControlServer) --

    def get_mode(self) -> str:
        return _read_mode(self.config)

    def set_mode(self, mode: str) -> None:
        """Set mode by reloading config."""
        self.reload_config()

    def get_voice_enabled(self) -> bool:
        return not os.path.exists(SILENT_FLAG)

    def is_ready(self) -> bool:
        return self._ready

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

        # HotkeyListener: rebuild if hotkey, language hotkey, or languages changed
        new_languages = [new.transcription.language]
        if new.transcription.extra_languages:
            new_languages += new.transcription.extra_languages
        hotkey_changed = (
            new.input.hotkey != old.input.hotkey
            or new.input.language_hotkey != old.input.language_hotkey
            or new_languages != self._languages
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
                combo_hotkey=new.speech.hotkey,
                on_combo=self._toggle_voice,
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

        # Update language_backends and openai_api_key (hot-reloadable)
        cloud_changed = (
            new.transcription.language_backends != old.transcription.language_backends
            or new.speech.openai_api_key != old.speech.openai_api_key
        )
        if cloud_changed:
            self.transcriber.language_backends = new.transcription.language_backends
            self.transcriber.openai_api_key = new.speech.openai_api_key
            self.transcriber._cloud_transcribers = {}  # Force re-creation
            changed.append("transcriber(language_backends)")

        # ResponseSummarizer: recreate if model changed
        if (new.speech.summarize_model != old.speech.summarize_model
                or new.input.debug != old.input.debug):
            self.summarizer = ResponseSummarizer(
                model_name=new.speech.summarize_model,
                debug=new.input.debug,
            )
            if not self.summarizer.ensure_ready():
                changed.append("summarizer(failed)")
            else:
                changed.append("summarizer(recreated)")

        # Overlay: re-init if style changed
        if new.overlay.style != old.overlay.style and new.overlay.enabled:
            from daemon import overlay
            overlay.update_style(style=new.overlay.style)
            changed.append("overlay")

        # Notify phrases: regenerate if voice/speed/lang_code/engine changed
        voice_changed = (
            new.speech.voice != old.speech.voice
            or new.speech.speed != old.speech.speed
            or new.speech.lang_code != old.speech.lang_code
            or new.speech.notify_phrases != old.speech.notify_phrases
            or new.speech.engine != old.speech.engine
            or new.speech.openai_api_key != old.speech.openai_api_key
            or new.speech.openai_model != old.speech.openai_model
        )
        if voice_changed:
            from daemon.notify import regenerate_custom_phrases
            regenerate_custom_phrases(
                new.speech.notify_phrases,
                voice=new.speech.voice,
                speed=new.speech.speed,
                lang_code=new.speech.lang_code,
                engine=new.speech.engine,
                openai_api_key=new.speech.openai_api_key,
                openai_model=new.speech.openai_model,
                interactive=False,
            )
            changed.append("notify_phrases")

        # TTS engine: recreate if engine type or credentials changed
        engine_changed = (
            new.speech.engine != old.speech.engine
            or new.speech.openai_api_key != old.speech.openai_api_key
            or new.speech.openai_model != old.speech.openai_model
        )
        if engine_changed:
            self.tts_engine.stop_playback()
            self.tts_engine = create_tts_engine(
                engine=new.speech.engine,
                api_key=new.speech.openai_api_key,
                model=new.speech.openai_model,
            )
            if hasattr(self.tts_engine, 'set_emitter') and hasattr(self, 'control_server'):
                self.tts_engine.set_emitter(self.control_server.emit)
            changed.append("tts_engine")

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

        return False

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
        os.chmod(TTS_SOCK_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600 - owner only
        server.listen(5)
        server.settimeout(1.0)  # Allow periodic shutdown checks

        self._tts_server = server

        while not self._shutting_down:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError as e:
                if not self._shutting_down:
                    print(f"TTS server: accept error, exiting: {e}")
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
                    elif mode == "narrate":
                        # Summarize response before speaking
                        summary = self.summarizer.summarize(
                            text, style=self.config.speech.narrate_style
                        )
                        if summary:
                            print(f"Narrate ({self.config.speech.narrate_style}): {summary[:80]}...")
                            self.tts_engine.speak(summary, voice=voice, speed=speed, lang_code=lang_code)
                        else:
                            # Summarization failed, fall back to notify
                            print("Narrate: summarization failed, using notify fallback")
                            play_phrase("done", self.config.speech.notify_phrases)
            except Exception as e:
                print(f"TTS server error: {e}")
            finally:
                if not conn_closed:
                    try:
                        conn.close()
                    except OSError:
                        pass  # Connection already closed

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

        # Skip silence — prevents Whisper hallucinations on empty audio
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 0.003:
            overlay.hide()
            print(f"Silent ({rms:.4f} RMS), ignoring")
            return

        overlay.show_transcribing()
        print(f"Transcribing {duration:.1f}s of audio...")

        # Build initial_prompt from word_replacements to bias Whisper toward domain vocabulary
        initial_prompt = None
        if self.config.transcription.word_replacements:
            vocab = list(dict.fromkeys(self.config.transcription.word_replacements.values()))
            initial_prompt = ", ".join(vocab)

        text = self.transcriber.transcribe(
            audio, language=self.hotkey_listener.active_language,
            initial_prompt=initial_prompt,
        )

        if not text:
            overlay.hide()
            print("No speech detected")
            return

        # Strip filler words (um, uh, etc.)
        cleaned = strip_filler_words(text)
        if cleaned != text:
            print(f"Raw:       {text}")
            print(f"Cleaned:   {cleaned}")
            text = cleaned

        if not text:
            overlay.hide()
            print("Only filler words detected")
            return

        # Apply word replacements
        if self.config.transcription.word_replacements:
            replaced = apply_word_replacements(text, self.config.transcription.word_replacements)
            if replaced != text:
                print(f"Before:    {text}")
                print(f"Replaced:  {replaced}")
                text = replaced

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
        self._shutting_down = True

        # Close audio cue stream
        with _cue_lock:
            if _cue_stream is not None:
                try:
                    _cue_stream.stop()
                    _cue_stream.close()
                except (sd.PortAudioError, OSError):
                    pass  # Device already closed or unavailable
                _cue_stream = None

        # Hide overlay
        from daemon import overlay
        overlay.hide()

        if hasattr(self, "control_server"):
            self.control_server.shutdown()

        if self._tts_server:
            try:
                self._tts_server.close()
            except OSError:
                pass  # Socket already closed
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
        except (ProcessLookupError, OSError, AttributeError, ImportError):
            pass  # Process already dead, or tracker internals changed

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
                # Only warn about languages that don't have a cloud backend
                local_only = [lang for lang in self.config.transcription.extra_languages
                              if lang not in self.config.transcription.language_backends]
                if local_only:
                    print(f"WARNING: Model '{model}' only supports English.")
                    print(f"  Languages {local_only} require a multilingual model (e.g. large-v3) or a cloud backend.")
        print("Press Ctrl+C to stop")
        print("=" * 50)

        # Clean stale ask-user flag from a previous crash
        if os.path.exists(ASK_USER_FLAG):
            try:
                os.remove(ASK_USER_FLAG)
            except OSError:
                pass
        _init_cue_cache()
        print(f"TTS mode: {_read_mode()}")
        print(f"TTS engine: {self.config.speech.engine}")

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
                    engine=self.config.speech.engine,
                    openai_api_key=self.config.speech.openai_api_key,
                    openai_model=self.config.speech.openai_model,
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
                        engine=self.config.speech.engine,
                        openai_api_key=self.config.speech.openai_api_key,
                        openai_model=self.config.speech.openai_model,
                        interactive=False,
                    )

            # Check response summarizer for narrate mode
            if not self.summarizer.ensure_ready():
                print("  → Narrate mode will fall back to notify phrases")

            print("Ready! Hold the hotkey and speak.")
            print()

            # Start TTS socket server
            tts_thread = threading.Thread(target=self._run_tts_server, daemon=True, name="tts-server")
            tts_thread.start()
            print(f"TTS server listening on {TTS_SOCK_PATH}")

            # Start control socket server (for external app communication)
            self.control_server = ControlServer(self)
            control_thread = threading.Thread(target=self.control_server.run, daemon=True, name="control-server")
            control_thread.start()
            print("Control server listening on ~/.claude-voice/.control.sock")

            # Wire TTS error events to socket subscribers
            if hasattr(self.tts_engine, 'set_emitter'):
                self.tts_engine.set_emitter(self.control_server.emit)

            # Start hotkey listener on background thread
            self.hotkey_listener.start()

            # Startup complete
            _play_cue(CUE_ASCENDING)
            if overlay_cfg.enabled:
                overlay.show_flash("Claude Voice Started")
            self._ready = True

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
