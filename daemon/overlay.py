"""Floating overlay indicator for voice input state."""

import math
import threading

try:
    import objc
    from AppKit import (
        NSWindow,
        NSView,
        NSColor,
        NSScreen,
        NSBezierPath,
        NSBackingStoreBuffered,
        NSShadow,
        NSGraphicsContext,
    )
    from Foundation import NSSize, NSTimer, NSObject, NSMakeRect
    from Quartz import (
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


if PYOBJC_AVAILABLE:

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
                glow = self._glow_color.colorWithAlphaComponent_(
                    0.6 * self._glow_alpha
                )
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

    class OverlayController(NSObject):
        """Controls the floating overlay window. All public methods are thread-safe."""

        def init(self):
            self = objc.super(OverlayController, self).init()
            if self is None:
                return None
            self._window = None
            self._pill_view = None
            self._pulse_timer = None
            self._pulse_phase = 0.0
            self._state = "idle"  # idle, recording, transcribing
            self._recording_color = None
            self._transcribing_color = None
            return self

        def setColors_transcribing_(self, recording_color, transcribing_color):
            self._recording_color = recording_color
            self._transcribing_color = transcribing_color

        def setup(self):
            """Create the overlay window. Must be called on the main thread."""
            # Get screen dimensions
            screen = NSScreen.mainScreen()
            screen_frame = screen.frame()
            visible = screen.visibleFrame()
            menu_bar_height = (
                screen_frame.size.height - visible.size.height - visible.origin.y
            )

            # Position centered horizontally, below menu bar
            x = (screen_frame.size.width - PILL_WIDTH) / 2
            y = screen_frame.size.height - menu_bar_height - PILL_HEIGHT - MARGIN_TOP

            window_rect = NSMakeRect(x, y, PILL_WIDTH, PILL_HEIGHT)

            self._window = (
                NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    window_rect,
                    0,  # NSBorderlessWindowMask
                    NSBackingStoreBuffered,
                    False,
                )
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

        def show_recording(self):
            """Show green pill (recording state). Thread-safe."""
            if self._window is None:
                return
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doShowRecording", None, False
            )

        def show_transcribing(self):
            """Transition to purple pulsing pill (transcribing state). Thread-safe."""
            if self._window is None:
                return
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doShowTranscribing", None, False
            )

        def hide(self):
            """Hide the overlay. Thread-safe."""
            if self._window is None:
                return
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doHide", None, False
            )

        def doShowRecording(self):
            """Main thread: show green pill."""
            self._stop_pulse()
            self._state = "recording"
            self._pill_view.setColor_(self._recording_color)
            self._pill_view.setGlowAlpha_(0.0)
            self._window.setAlphaValue_(1.0)

        def doShowTranscribing(self):
            """Main thread: transition to purple pulsing pill."""
            self._stop_pulse()
            self._state = "transcribing"
            self._pill_view.setColor_(self._transcribing_color)
            self._start_pulse()

        def doHide(self):
            """Main thread: hide the pill."""
            self._stop_pulse()
            self._state = "idle"
            self._window.setAlphaValue_(0.0)

        def _start_pulse(self):
            """Start the glow pulse animation timer."""
            self._pulse_phase = 0.0
            self._pulse_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                PULSE_INTERVAL, self, "pulseTick:", None, True
            )

        def _stop_pulse(self):
            """Stop the pulse animation timer."""
            if self._pulse_timer:
                self._pulse_timer.invalidate()
                self._pulse_timer = None

        def pulseTick_(self, timer):
            """Timer callback: update glow alpha for pulse effect."""
            self._pulse_phase += PULSE_INTERVAL
            # Sine wave: 0 -> 1 -> 0 over PULSE_CYCLE seconds
            t = (self._pulse_phase % PULSE_CYCLE) / PULSE_CYCLE
            glow = (math.sin(t * 2 * math.pi - math.pi / 2) + 1) / 2
            self._pill_view.setGlowAlpha_(glow)


# Module-level singleton
_controller: "OverlayController | None" = None


def init(recording_color: str = "#34C759", transcribing_color: str = "#A855F7"):
    """Initialize the overlay. Must be called on the main thread."""
    global _controller
    if not PYOBJC_AVAILABLE:
        print("Warning: PyObjC not available, overlay disabled")
        return
    _controller = OverlayController.alloc().init()
    _controller.setColors_transcribing_(
        _hex_to_nscolor(recording_color),
        _hex_to_nscolor(transcribing_color),
    )
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
