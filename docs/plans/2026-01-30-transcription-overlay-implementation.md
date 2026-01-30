# Transcription Overlay Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a floating macOS overlay capsule that shows recording (green) and transcribing (purple pulse) states during the voice input lifecycle.

**Architecture:** A new `daemon/overlay.py` module uses PyObjC to create a borderless NSWindow with a colored pill view. The main thread runs the Cocoa NSApplication run loop; the existing daemon logic (hotkey, audio, TTS) moves to a background thread. State changes are dispatched to the main thread via `performSelectorOnMainThread`.

**Tech Stack:** PyObjC (AppKit, Foundation, Quartz Core Animation), already available in the venv.

---

### Task 1: Create overlay module with NSWindow and pill view

**Files:**
- Create: `daemon/overlay.py`

**Step 1: Create `daemon/overlay.py` with the overlay window and pill view**

```python
"""Floating overlay indicator for voice input state."""

import threading

try:
    import objc
    from AppKit import (
        NSApplication,
        NSWindow,
        NSView,
        NSColor,
        NSScreen,
        NSBezierPath,
        NSBackingStoreBuffered,
        NSShadow,
        NSGraphicsContext,
        NSCompositingOperationSourceOver,
    )
    from Foundation import NSRect, NSPoint, NSSize, NSTimer, NSObject, NSMakeRect
    from Quartz import (
        kCGWindowLevelStatusBar,
        CGWindowLevelForKey,
        kCGMaximumWindowLevelKey,
    )

    PYOBJC_AVAILABLE = True
except ImportError:
    PYOBJC_AVAILABLE = False


def _hex_to_nscolor(hex_str: str, alpha: float = 1.0):
    """Convert '#RRGGBB' to NSColor."""
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)


# Pill dimensions (points)
PILL_WIDTH = 100
PILL_HEIGHT = 40
PILL_RADIUS = PILL_HEIGHT / 2
MARGIN_TOP = 10  # below menu bar

# Animation
PULSE_INTERVAL = 0.03  # ~30fps timer for pulse animation
PULSE_CYCLE = 1.5  # seconds per full pulse cycle


class _PillView(NSView):
    """Custom view that draws a rounded pill with configurable color and glow."""

    def initWithFrame_(self, frame):
        self = objc.super(_PillView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._color = NSColor.greenColor()
        self._glow_alpha = 0.0
        self._glow_color = NSColor.greenColor()
        return self

    def setColor_(self, color):
        self._color = color
        self._glow_color = color
        self.setNeedsDisplay_(True)

    def setGlowAlpha_(self, alpha):
        self._glow_alpha = alpha
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        bounds = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, PILL_RADIUS, PILL_RADIUS
        )

        # Draw glow (shadow) behind pill
        if self._glow_alpha > 0:
            context = NSGraphicsContext.currentContext()
            context.saveGraphicsState()
            shadow = NSShadow.alloc().init()
            shadow.setShadowOffset_(NSSize(0, 0))
            shadow.setShadowBlurRadius_(15.0 * self._glow_alpha)
            glow = self._glow_color.colorWithAlphaComponent_(0.6 * self._glow_alpha)
            shadow.setShadowColor_(glow)
            shadow.set()
            self._color.colorWithAlphaComponent_(0.9).setFill()
            path.fill()
            context.restoreGraphicsState()
        else:
            self._color.colorWithAlphaComponent_(0.9).setFill()
            path.fill()

        # Dark border
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.2).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()


class OverlayController:
    """Controls the floating overlay window. All public methods are thread-safe."""

    def __init__(self, recording_color: str = "#34C759", transcribing_color: str = "#A855F7"):
        if not PYOBJC_AVAILABLE:
            return

        self._recording_color = _hex_to_nscolor(recording_color)
        self._transcribing_color = _hex_to_nscolor(transcribing_color)
        self._window = None
        self._pill_view = None
        self._pulse_timer = None
        self._pulse_phase = 0.0
        self._state = "idle"  # idle, recording, transcribing

    def setup(self):
        """Create the overlay window. Must be called on the main thread."""
        if not PYOBJC_AVAILABLE:
            return

        # Get screen dimensions
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()
        menu_bar_height = screen_frame.size.height - screen.visibleFrame().size.height - screen.visibleFrame().origin.y

        # Position centered horizontally, below menu bar
        x = (screen_frame.size.width - PILL_WIDTH) / 2
        y = screen_frame.size.height - menu_bar_height - PILL_HEIGHT - MARGIN_TOP

        window_rect = NSMakeRect(x, y, PILL_WIDTH, PILL_HEIGHT)

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            window_rect,
            0,  # NSBorderlessWindowMask
            NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(CGWindowLevelForKey(kCGMaximumWindowLevelKey))
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            1 << 0  # NSWindowCollectionBehaviorCanJoinAllSpaces
            | 1 << 4  # NSWindowCollectionBehaviorStationary
        )
        self._window.setHasShadow_(True)
        self._window.setAlphaValue_(0.0)

        # Create pill view
        pill_rect = NSMakeRect(0, 0, PILL_WIDTH, PILL_HEIGHT)
        self._pill_view = _PillView.alloc().initWithFrame_(pill_rect)
        self._window.contentView().addSubview_(self._pill_view)

        # Order window to front but keep it hidden (alpha=0)
        self._window.orderFrontRegardless()

    def _on_main_thread(self, method, arg=None):
        """Dispatch a call to the main thread."""
        if arg is not None:
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                method, arg, False
            )
        else:
            # Use a timer with 0 delay to run on the main thread's run loop
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0, self, method, None, False
            )

    def show_recording(self):
        """Show green pill (recording state). Thread-safe."""
        if not PYOBJC_AVAILABLE or self._window is None:
            return
        self._dispatch("_do_show_recording")

    def show_transcribing(self):
        """Transition to purple pulsing pill (transcribing state). Thread-safe."""
        if not PYOBJC_AVAILABLE or self._window is None:
            return
        self._dispatch("_do_show_transcribing")

    def hide(self):
        """Hide the overlay. Thread-safe."""
        if not PYOBJC_AVAILABLE or self._window is None:
            return
        self._dispatch("_do_hide")

    def _dispatch(self, selector_name: str):
        """Dispatch a selector to the main thread's run loop."""
        NSObject.cancelPreviousPerformRequestsWithTarget_(self)
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            selector_name, None, False
        )

    def _do_show_recording(self):
        """Main thread: show green pill."""
        self._stop_pulse()
        self._state = "recording"
        self._pill_view.setColor_(self._recording_color)
        self._pill_view.setGlowAlpha_(0.0)
        self._window.setAlphaValue_(1.0)

    def _do_show_transcribing(self):
        """Main thread: transition to purple pulsing pill."""
        self._state = "transcribing"
        self._pill_view.setColor_(self._transcribing_color)
        self._start_pulse()

    def _do_hide(self):
        """Main thread: hide the pill."""
        self._stop_pulse()
        self._state = "idle"
        self._window.setAlphaValue_(0.0)

    def _start_pulse(self):
        """Start the glow pulse animation timer."""
        self._pulse_phase = 0.0
        self._pulse_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            PULSE_INTERVAL, self, "_pulse_tick:", None, True
        )

    def _stop_pulse(self):
        """Stop the pulse animation timer."""
        if self._pulse_timer:
            self._pulse_timer.invalidate()
            self._pulse_timer = None

    def _pulse_tick_(self, timer):
        """Timer callback: update glow alpha for pulse effect."""
        import math

        self._pulse_phase += PULSE_INTERVAL
        # Sine wave: 0 → 1 → 0 over PULSE_CYCLE seconds
        t = (self._pulse_phase % PULSE_CYCLE) / PULSE_CYCLE
        glow = (math.sin(t * 2 * math.pi - math.pi / 2) + 1) / 2
        self._pill_view.setGlowAlpha_(glow)


# Module-level singleton
_controller: OverlayController | None = None


def init(recording_color: str = "#34C759", transcribing_color: str = "#A855F7"):
    """Initialize the overlay. Must be called on the main thread."""
    global _controller
    if not PYOBJC_AVAILABLE:
        print("Warning: PyObjC not available, overlay disabled")
        return
    _controller = OverlayController(recording_color, transcribing_color)
    _controller.setup()


def show_recording():
    if _controller:
        _controller.show_recording()


def show_transcribing():
    if _controller:
        _controller.show_transcribing()


def hide():
    if _controller:
        _controller.hide()
```

**Step 2: Verify the file was created correctly**

Run: `python3 -c "import ast; ast.parse(open('daemon/overlay.py').read()); print('Syntax OK')"`
Expected: `Syntax OK`

**Step 3: Commit**

```bash
git add daemon/overlay.py
git commit -m "Add overlay module with PyObjC floating pill indicator"
```

---

### Task 2: Restructure main thread to run Cocoa run loop

NSWindow must be created on the main thread. Currently `main.py` runs the hotkey listener on the main thread. We need to flip this: main thread runs the Cocoa `NSApplication` run loop, daemon logic runs on a background thread.

**Files:**
- Modify: `daemon/main.py`

**Step 1: Update `main.py` to run Cocoa on main thread, daemon on background thread**

The key changes to `VoiceDaemon.run()`:

1. Import the overlay module
2. Call `overlay.init()` on the main thread before starting the app run loop
3. Move the existing run logic (hotkey listener, TTS server) into a background thread
4. Start `NSApplication.sharedApplication().run()` on the main thread
5. On shutdown, call `NSApp.terminate_()` to exit the run loop

Replace the `run()` method and `main()` function:

```python
def run(self) -> None:
    """Start the daemon."""
    signal.signal(signal.SIGTERM, lambda sig, frame: self._shutdown())

    print("=" * 50)
    print("Claude Voice Daemon")
    print("=" * 50)
    print(f"Hotkey: {self.config.input.hotkey} (hold to record)")
    print(f"Model: {self.config.transcription.model}")
    print("Press Ctrl+C to stop")
    print("=" * 50)

    if not os.path.exists(MODE_FILE):
        _write_mode(self.config.speech.mode)
    print(f"TTS mode: {_read_mode()}")

    if os.path.exists(ERROR_FLAG):
        os.remove(ERROR_FLAG)

    # Pre-load models
    self.transcriber._ensure_model()
    if self.config.speech.enabled:
        self.tts_engine._ensure_model()

        if sys.stdin.isatty():
            print('\nSound check: playing "Hello!! Can you hear me?"')
            self.tts_engine.speak(
                "Hello!! Can you hear me?",
                voice=self.config.speech.voice,
                speed=self.config.speech.speed,
                lang_code=self.config.speech.lang_code,
            )
            answer = input("Did you hear the test phrase? [Y/n] ").strip().lower()
            if answer in ("n", "no"):
                print("Tip: check your audio output device and volume settings.")
                print("Continuing startup anyway...\n")
            else:
                print("Sound check passed.\n")

    if self.config.speech.mode == "notify" or self.config.speech.notify_phrases:
        from daemon.notify import regenerate_custom_phrases
        is_foreground = sys.stdin.isatty()
        regenerate_custom_phrases(
            self.config.speech.notify_phrases,
            voice=self.config.speech.voice,
            speed=self.config.speech.speed,
            lang_code=self.config.speech.lang_code,
            interactive=is_foreground,
        )

    if self.cleaner:
        if not self.cleaner.ensure_ready():
            self.cleaner = None

    print("Ready! Hold the hotkey and speak.")
    print()

    # Start TTS socket server
    tts_thread = threading.Thread(target=self._run_tts_server, daemon=True)
    tts_thread.start()
    print(f"TTS server listening on {TTS_SOCK_PATH}")

    # Initialize overlay on main thread
    overlay_cfg = self.config.overlay
    if overlay_cfg.enabled:
        from daemon import overlay
        overlay.init(
            recording_color=overlay_cfg.recording_color,
            transcribing_color=overlay_cfg.transcribing_color,
        )

    # Start hotkey listener on background thread
    self.hotkey_listener.start()

    if overlay_cfg.enabled:
        # Run Cocoa run loop on main thread (required for NSWindow)
        from AppKit import NSApplication
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
        try:
            app.run()
        except KeyboardInterrupt:
            self._shutdown()
    else:
        # No overlay - block on hotkey listener as before
        try:
            self.hotkey_listener.join()
        except KeyboardInterrupt:
            self._shutdown()
```

Update `_shutdown()` to stop the Cocoa run loop:

```python
def _shutdown(self) -> None:
    """Clean shutdown of the daemon."""
    print("\nShutting down...")
    self._shutting_down = True

    # Hide overlay
    from daemon import overlay
    overlay.hide()

    if self._tts_server:
        try:
            self._tts_server.close()
        except Exception:
            pass
    if os.path.exists(TTS_SOCK_PATH):
        os.unlink(TTS_SOCK_PATH)
    self.hotkey_listener.stop()
    self.recorder.shutdown()

    # Stop Cocoa run loop if running
    try:
        from AppKit import NSApplication
        app = NSApplication.sharedApplication()
        app.stop_(None)
    except Exception:
        pass

    try:
        from multiprocessing import resource_tracker
        tracker = resource_tracker._resource_tracker
        if tracker._pid is not None:
            os.kill(tracker._pid, signal.SIGKILL)
    except:
        pass

    os._exit(0)
```

**Step 2: Verify daemon starts without errors**

Run: `~/.claude-voice/claude-voice-daemon foreground` and press Ctrl+C after startup completes.
Expected: Daemon starts, prints "Ready!", Ctrl+C shuts down cleanly.

**Step 3: Commit**

```bash
git add daemon/main.py
git commit -m "Run Cocoa run loop on main thread for overlay support"
```

---

### Task 3: Wire overlay state transitions into hotkey callbacks

**Files:**
- Modify: `daemon/main.py`

**Step 1: Add overlay calls to `_on_hotkey_press` and `_on_hotkey_release`**

In `_on_hotkey_press`, add after `self.recorder.start()`:

```python
from daemon import overlay
overlay.show_recording()
```

In `_on_hotkey_release`, add after `audio = self.recorder.stop()`:

```python
from daemon import overlay
overlay.show_transcribing()
```

Add `overlay.hide()` at every exit point in `_on_hotkey_release`:
- After "too short, ignoring"
- After "no speech detected"
- After voice command handled
- After `self.keyboard.type_text(text + " ")`

**Step 2: Test the full flow**

Run the daemon in foreground, hold the hotkey, speak, release. Verify:
- Green pill appears when hotkey is pressed
- Pill turns purple and pulses when hotkey is released
- Pill disappears when text is typed

**Step 3: Commit**

```bash
git add daemon/main.py
git commit -m "Wire overlay state transitions to hotkey press/release"
```

---

### Task 4: Add overlay config to config module

**Files:**
- Modify: `daemon/config.py`
- Modify: `config.yaml.example`

**Step 1: Add `OverlayConfig` dataclass and wire it into `Config`**

In `daemon/config.py`, add:

```python
@dataclass
class OverlayConfig:
    enabled: bool = True
    recording_color: str = "#34C759"
    transcribing_color: str = "#A855F7"
```

Add `overlay: OverlayConfig` to the `Config` dataclass.

In `load_config()`, add:

```python
overlay=OverlayConfig(**data.get('overlay', {})),
```

**Step 2: Add overlay section to `config.yaml.example`**

```yaml
overlay:
  enabled: true                 # Show visual indicator during recording/transcription
  recording_color: "#34C759"    # Green pill while recording
  transcribing_color: "#A855F7" # Purple pulsing pill while transcribing
```

**Step 3: Commit**

```bash
git add daemon/config.py config.yaml.example
git commit -m "Add overlay configuration options"
```

---

### Task 5: Handle PyObjC dispatch correctly for OverlayController

The `OverlayController` uses `performSelectorOnMainThread` which requires it to be an `NSObject` subclass. Fix the class hierarchy.

**Files:**
- Modify: `daemon/overlay.py`

**Step 1: Make `OverlayController` extend `NSObject`**

Change:
```python
class OverlayController:
```
To:
```python
class OverlayController(NSObject):
    def init(self):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None
        self._window = None
        self._pill_view = None
        self._pulse_timer = None
        self._pulse_phase = 0.0
        self._state = "idle"
        self._recording_color = None
        self._transcribing_color = None
        return self
```

Update `init()` module function to use `alloc().init()` pattern and set colors after construction.

Update `_dispatch()` to use proper ObjC selector syntax.

**Step 2: Verify overlay creates without errors**

Run: short test script that imports overlay, calls `init()`, and exits.

**Step 3: Commit**

```bash
git add daemon/overlay.py
git commit -m "Fix OverlayController to extend NSObject for main thread dispatch"
```

---

### Task 6: Handle edge case — rapid hotkey press/release and early exit

**Files:**
- Modify: `daemon/overlay.py`

**Step 1: Ensure state transitions cancel previous animations**

In `_do_show_recording`, `_do_show_transcribing`, and `_do_hide`: always call `_stop_pulse()` first and set state before any visual change.

**Step 2: Handle the "too short" path in main.py**

When recording is too short (< min_audio_length), we go straight from recording → idle (skip transcribing). Verify `overlay.hide()` is called in that code path (already done in Task 3).

**Step 3: Test rapid press/release**

Run daemon, quickly tap the hotkey multiple times. Verify no animation artifacts or errors.

**Step 4: Commit**

```bash
git add daemon/overlay.py daemon/main.py
git commit -m "Handle rapid hotkey press/release in overlay"
```

---

### Task 7: Update install script for overlay dependency

**Files:**
- Modify: `install.sh`

**Step 1: Add `pyobjc-framework-Cocoa` to the pip install line**

PyObjC is already available in the venv (confirmed), but the install script should explicitly list it so fresh installs get it too. Add `pyobjc-framework-Cocoa pyobjc-framework-Quartz` to the `_spin_run "Installing core dependencies"` line.

**Step 2: Commit**

```bash
git add install.sh
git commit -m "Add PyObjC frameworks to install dependencies"
```

---

### Task 8: Manual integration test

**No files to change.** This is a full end-to-end verification.

**Step 1:** Copy updated daemon files to `~/.claude-voice/daemon/`
**Step 2:** Start daemon in foreground: `~/.claude-voice/claude-voice-daemon foreground`
**Step 3:** Test the full flow:
- Hold hotkey → green pill appears centered below notch
- Release hotkey → pill turns purple and pulses
- Text is typed → pill disappears
- Quick tap hotkey (< 0.5s) → pill appears and disappears cleanly
- Disable overlay in config (`enabled: false`) → no pill, daemon works normally
**Step 4:** Verify no regressions: TTS, voice commands, and transcription all work as before.
