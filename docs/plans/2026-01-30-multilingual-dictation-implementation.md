# Multilingual Dictation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a language-cycle hotkey that toggles between configured languages, passing the active language to Whisper and showing visual feedback via the overlay.

**Architecture:** A new `language_hotkey` triggers a `LanguageCycler` that rotates through `[default_language] + extra_languages`. The active language is passed to `Transcriber.transcribe()` on each recording. The overlay gains a text-label mode for language flash notifications and a label on the recording pill for non-default languages.

**Tech Stack:** Python, pynput, PyObjC (AppKit/CoreText for text rendering), mlx-whisper/faster-whisper

**Design doc:** `docs/plans/2026-01-30-multilingual-dictation-design.md`

**Note:** This project has no automated test infrastructure. All tasks use manual verification via daemon startup and hotkey interaction.

---

### Task 1: Add config fields

**Files:**
- Modify: `daemon/config.py`
- Modify: `config.yaml.example`

**Step 1: Add `language_hotkey` to `InputConfig` and `extra_languages` to `TranscriptionConfig`**

In `daemon/config.py`, add to `InputConfig`:
```python
language_hotkey: Optional[str] = None
```

Add to `TranscriptionConfig`:
```python
extra_languages: list[str] = None  # will default to [] in __post_init__
```

Note: dataclasses don't allow mutable defaults. Use `None` and convert in `load_config` or use `field(default_factory=list)`.

Simplest approach — just use `None` and treat it as empty list downstream. But cleaner to use `field`:

```python
from dataclasses import dataclass, field

@dataclass
class TranscriptionConfig:
    model: str = "large-v3"
    language: str = "en"
    device: str = "cpu"
    backend: str = "faster-whisper"
    extra_languages: list = field(default_factory=list)
```

Also add `field` import and update `InputConfig`:
```python
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
```

**Step 2: Update `config.yaml.example` with new fields**

Add under `input:` section:
```yaml
  language_hotkey: null          # Key to cycle languages (e.g. "right_cmd")
```

Add under `transcription:` section:
```yaml
  extra_languages: []            # Additional languages to cycle through (e.g. ["af", "de"])
```

**Step 3: Verify config loads**

Run: `cd /Users/johan/IdeaProjects/claude-voice && python -c "from daemon.config import load_config; c = load_config(); print(c.input.language_hotkey, c.transcription.extra_languages)"`

Expected: `None []` (or current config values if user has custom config)

**Step 4: Commit**

```bash
git add daemon/config.py config.yaml.example
git commit -m "feat: add language_hotkey and extra_languages config fields"
```

---

### Task 2: Accept language parameter in Transcriber

**Files:**
- Modify: `daemon/transcribe.py`

**Step 1: Add `language` parameter to `transcribe()` and pass it through**

Change `transcribe()` signature:
```python
def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, language: str = "en") -> str:
```

Change `_transcribe_mlx()` signature and body:
```python
def _transcribe_mlx(self, audio: np.ndarray, language: str = "en") -> str:
    """Transcribe using MLX Whisper."""
    import mlx_whisper
    mlx_model = self.MLX_MODELS.get(self.model_name, f"mlx-community/whisper-{self.model_name}-mlx")
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=mlx_model,
        language=language,
    )
    return result.get("text", "").strip()
```

Change `_transcribe_faster_whisper()` signature and body:
```python
def _transcribe_faster_whisper(self, audio: np.ndarray, language: str = "en") -> str:
    """Transcribe using faster-whisper."""
    segments, info = self._model.transcribe(
        audio,
        language=language,
        vad_filter=True,
    )
    text_parts = [segment.text.strip() for segment in segments]
    return " ".join(text_parts).strip()
```

Update `transcribe()` to pass language through:
```python
if self.backend == "mlx":
    return self._transcribe_mlx(audio, language=language)
else:
    return self._transcribe_faster_whisper(audio, language=language)
```

**Step 2: Verify it still works with default language**

Run: `cd /Users/johan/IdeaProjects/claude-voice && python -c "from daemon.transcribe import Transcriber; t = Transcriber(model_name='base.en', backend='faster-whisper'); print('OK')"`

Expected: `OK` (just import check, no model load)

**Step 3: Commit**

```bash
git add daemon/transcribe.py
git commit -m "feat: accept language parameter in Transcriber.transcribe()"
```

---

### Task 3: Add language cycling to HotkeyListener

**Files:**
- Modify: `daemon/hotkey.py`

**Step 1: Add language cycling support**

The `HotkeyListener` needs to:
- Accept an optional `language_hotkey` and list of languages
- Track the active language
- Call a callback when language changes
- Listen for both the recording hotkey and the language hotkey

Replace the class to support both hotkeys:

```python
class HotkeyListener:
    """Listens for push-to-talk hotkey and optional language cycle hotkey."""

    def __init__(
        self,
        hotkey: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        language_hotkey: Optional[str] = None,
        languages: Optional[list[str]] = None,
        on_language_change: Optional[Callable[[str], None]] = None,
    ):
        self.hotkey = KEY_MAP.get(hotkey, keyboard.Key.alt_r)
        self.on_press = on_press
        self.on_release = on_release
        self._listener: Optional[keyboard.Listener] = None
        self._pressed = False

        # Language cycling
        self._language_hotkey = KEY_MAP.get(language_hotkey) if language_hotkey else None
        self._languages = languages or ["en"]
        self._language_index = 0
        self._on_language_change = on_language_change

    @property
    def active_language(self) -> str:
        return self._languages[self._language_index]

    def _handle_press(self, key) -> None:
        if key == self.hotkey and not self._pressed:
            self._pressed = True
            self.on_press()

    def _handle_release(self, key) -> None:
        if key == self.hotkey and self._pressed:
            self._pressed = False
            self.on_release()
        elif key == self._language_hotkey and self._language_hotkey is not None:
            self._cycle_language()

    def _cycle_language(self) -> None:
        self._language_index = (self._language_index + 1) % len(self._languages)
        lang = self._languages[self._language_index]
        if self._on_language_change:
            self._on_language_change(lang)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        if self._listener:
            self._listener.join()
```

Key details:
- Language cycles on key **release** (not press) to avoid repeated triggers
- `active_language` property lets main.py read the current language at transcription time
- `on_language_change` callback lets main.py trigger overlay feedback

**Step 2: Verify import**

Run: `cd /Users/johan/IdeaProjects/claude-voice && python -c "from daemon.hotkey import HotkeyListener; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add daemon/hotkey.py
git commit -m "feat: add language cycling support to HotkeyListener"
```

---

### Task 4: Add text label and language flash to overlay

**Files:**
- Modify: `daemon/overlay.py`

This is the most involved task. Two changes needed:

**A) Add text label support to the pill** — for showing "AF" during recording
**B) Add language flash notification** — briefly show pill with large language code text, then fade

**Step 1: Add text drawing to `_PillView`**

Add a `_label` attribute to `_PillView.initWithFrame_`:
```python
self._label = None  # e.g. "AF"
```

Add setter:
```python
def setLabel_(self, label):
    self._label = label
    self.setNeedsDisplay_(True)
```

Add a new mode `"language_flash"` to `drawRect_` and a text drawing method. In `drawRect_`, after the existing content drawing block:
```python
if self._mode == "recording":
    self._draw_waveform(bounds)
elif self._mode == "transcribing":
    self._draw_dots(bounds)
elif self._mode == "language_flash":
    self._draw_label(bounds, large=True)

# Draw small label overlay (e.g. "AF" next to waveform during recording)
if self._label and self._mode == "recording":
    self._draw_label(bounds, large=False)
```

Add the `_draw_label` method to `_PillView`:
```python
def _draw_label(self, bounds, large=False):
    """Draw language code text centered in the pill."""
    from AppKit import NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSString
    text = NSString.stringWithString_(self._label)
    font_size = 18.0 if large else 11.0
    font = NSFont.boldSystemFontOfSize_(font_size)
    attrs = {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: self._fg_color.colorWithAlphaComponent_(0.95),
    }
    text_size = text.sizeWithAttributes_(attrs)
    if large:
        # Centered
        x = (bounds.size.width - text_size.width) / 2
    else:
        # Right side of pill, after waveform area
        x = bounds.size.width - text_size.width - 10
    y = (bounds.size.height - text_size.height) / 2
    text.drawAtPoint_withAttributes_((x, y), attrs)
```

**Step 2: Add `show_language_flash` to `OverlayController`**

Add a fade timer attribute in `OverlayController.init`:
```python
self._fade_timer = None
```

Add the flash method:
```python
def show_language_flash(self, lang_code):
    """Flash the pill with a language code. Thread-safe."""
    if self._window is None:
        return
    self.performSelectorOnMainThread_withObject_waitUntilDone_(
        "doShowLanguageFlash:", lang_code.upper(), False
    )

def doShowLanguageFlash_(self, lang_code):
    """Main thread: show pill with language code, auto-fade after 1.5s."""
    self._stop_anim()
    self._cancel_fade()
    self._state = "language_flash"
    self._pill_view.setLabel_(lang_code)
    self._pill_view.setBackgroundColor_(None)  # use default dark bg
    self._pill_view.setForegroundColor_(NSColor.whiteColor())
    self._pill_view.setMode_("language_flash")
    self._window.setAlphaValue_(1.0)
    # Auto-hide after 1.5 seconds
    self._fade_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.5, self, "fadeOut:", None, False
    )

def fadeOut_(self, timer):
    """Timer callback: hide the pill after language flash."""
    self._fade_timer = None
    self._pill_view.setLabel_(None)
    self._pill_view.setMode_("idle")
    self._window.setAlphaValue_(0.0)

def _cancel_fade(self):
    """Cancel any pending fade timer."""
    if self._fade_timer:
        self._fade_timer.invalidate()
        self._fade_timer = None
```

**Step 3: Update `show_recording` to accept a language label**

Update `OverlayController.show_recording` to accept an optional label:
```python
def show_recording(self, label=None):
    """Show pill with waveform animation. Thread-safe."""
    if self._window is None:
        return
    self.performSelectorOnMainThread_withObject_waitUntilDone_(
        "doShowRecording:", label, False
    )

def doShowRecording_(self, label):
    """Main thread: show pill with waveform bars."""
    self._stop_anim()
    self._cancel_fade()
    self._state = "recording"
    self._pill_view.setLabel_(label)
    self._pill_view.setBackgroundColor_(self._recording_color)
    self._pill_view.setForegroundColor_(self._fg_color_for_state("recording"))
    self._pill_view.setMode_("recording")
    self._window.setAlphaValue_(1.0)
    self._start_anim()
```

Note: the existing `doShowRecording` (no args) becomes `doShowRecording:` (with arg) — the ObjC selector name changes due to the argument.

Also update `doShowTranscribing` to clear the label:
```python
def doShowTranscribing(self):
    """Main thread: show pill with bouncing dots."""
    self._stop_anim()
    self._cancel_fade()
    self._state = "transcribing"
    self._pill_view.setLabel_(None)
    ...
```

And `doHide`:
```python
def doHide(self):
    """Main thread: hide the pill."""
    self._stop_anim()
    self._cancel_fade()
    self._state = "idle"
    self._pill_view.setLabel_(None)
    self._pill_view.setMode_("idle")
    self._window.setAlphaValue_(0.0)
```

**Step 4: Update module-level functions**

```python
def show_recording(label=None):
    if _controller:
        _controller.show_recording(label=label)

def show_language_flash(lang_code):
    if _controller:
        _controller.show_language_flash(lang_code)
```

**Step 5: Verify import**

Run: `cd /Users/johan/IdeaProjects/claude-voice && python -c "from daemon import overlay; print('OK')"`

Expected: `OK`

**Step 6: Commit**

```bash
git add daemon/overlay.py
git commit -m "feat: add text label and language flash notification to overlay"
```

---

### Task 5: Wire everything together in main.py

**Files:**
- Modify: `daemon/main.py`

**Step 1: Build language list and pass to HotkeyListener**

In `VoiceDaemon.__init__`, build the language list from config and update the HotkeyListener construction:

```python
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
)
```

**Step 2: Add language change callback**

```python
def _on_language_change(self, lang: str) -> None:
    """Called when language is cycled."""
    code = lang.upper()
    print(f"Language: {code}")
    from daemon import overlay
    overlay.show_language_flash(code)
```

**Step 3: Pass active language to transcriber in `_on_hotkey_release`**

Change the transcribe call:
```python
text = self.transcriber.transcribe(audio, language=self.hotkey_listener.active_language)
```

**Step 4: Pass language label to overlay in `_on_hotkey_press`**

Determine the label (None for default language, uppercase code for others):
```python
def _on_hotkey_press(self) -> None:
    """Called when hotkey is pressed - start recording."""
    self.recorder.start()
    _play_cue([440, 880])
    print("Recording...")

    # Show language label on overlay if not default language
    lang = self.hotkey_listener.active_language
    default_lang = self._languages[0]
    label = lang.upper() if lang != default_lang else None

    from daemon import overlay
    overlay.show_recording(label=label)

    self._interrupted_tts = self.tts_engine.stop_playback()
    if not self._interrupted_tts:
        self._interrupted_tts = stop_notify_playback()
```

**Step 5: Add startup warning for English-only models with extra languages**

In `VoiceDaemon.run()`, after printing config info, add:
```python
if self.config.transcription.extra_languages:
    model = self.config.transcription.model
    if model.endswith(".en"):
        print(f"WARNING: Model '{model}' only supports English.")
        print(f"  Extra languages {self.config.transcription.extra_languages} require a multilingual model (e.g. large-v3).")
```

Also update the startup banner to show language info:
```python
print(f"Hotkey: {self.config.input.hotkey} (hold to record)")
if self.config.input.language_hotkey and self.config.transcription.extra_languages:
    print(f"Language hotkey: {self.config.input.language_hotkey} (cycle languages)")
    print(f"Languages: {', '.join(self._languages)}")
print(f"Model: {self.config.transcription.model}")
```

**Step 6: Commit**

```bash
git add daemon/main.py
git commit -m "feat: wire language cycling into daemon"
```

---

### Task 6: Manual integration test

**No files to modify** — just verify everything works end-to-end.

**Step 1: Update your config**

Ensure `~/.claude-voice/config.yaml` has:
```yaml
input:
  hotkey: "right_alt"
  language_hotkey: "right_cmd"

transcription:
  model: "large-v3"
  backend: "mlx"
  language: "en"
  extra_languages: ["af"]
```

**Step 2: Start the daemon**

Run: `cd /Users/johan/IdeaProjects/claude-voice && python -m daemon.main`

Verify startup output shows:
```
Hotkey: right_alt (hold to record)
Language hotkey: right_cmd (cycle languages)
Languages: en, af
```

**Step 3: Test language cycling**

- Tap `right_cmd` → overlay should flash "AF" for ~1.5s
- Tap `right_cmd` again → overlay should flash "EN" for ~1.5s

**Step 4: Test Afrikaans recording**

- Tap `right_cmd` to switch to AF
- Hold `right_alt` → overlay should show green pill with "AF" label
- Speak Afrikaans → verify transcription is Afrikaans (not Dutch)

**Step 5: Test English recording (no regression)**

- Tap `right_cmd` to switch back to EN
- Hold `right_alt` → overlay should show green pill with NO label
- Speak English → verify transcription works as before

**Step 6: Test without extra_languages configured**

Remove `extra_languages` and `language_hotkey` from config, restart daemon.
Verify it works exactly as before with no errors.

**Step 7: Commit config example update if not already done**

```bash
git add config.yaml.example
git commit -m "docs: add language cycling config to example"
```
