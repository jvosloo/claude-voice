"""Floating overlay indicator for voice input state."""

import math

try:
    import objc
    from AppKit import (
        NSWindow,
        NSView,
        NSVisualEffectView,
        NSColor,
        NSScreen,
        NSBezierPath,
        NSBackingStoreBuffered,
    )
    from Foundation import NSTimer, NSObject, NSMakeRect
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
PILL_WIDTH = 120
PILL_HEIGHT = 36
PILL_RADIUS = PILL_HEIGHT / 2
MARGIN_TOP = 10  # below menu bar

# Dark style background
DARK_BG = (0.0, 0.0, 0.0, 0.7)

# Animation
ANIM_INTERVAL = 0.03  # ~30fps

# Waveform bars (recording)
NUM_BARS = 7
BAR_WIDTH = 4
BAR_GAP = 3
BAR_MIN_H = 4
BAR_MAX_H = 20
# Each bar oscillates at a different speed for organic movement
BAR_SPEEDS = [2.7, 3.4, 2.1, 3.9, 2.5, 3.1, 2.8]

# Typing dots (transcribing)
NUM_DOTS = 3
DOT_RADIUS = 4
DOT_GAP = 12
DOT_BOUNCE = 6  # vertical bounce distance
DOT_CYCLE = 1.2  # seconds for full cycle
DOT_STAGGER = 0.18  # seconds delay between each dot


if PYOBJC_AVAILABLE:

    class _PillView(NSView):
        """Custom view that draws a pill with animated content."""

        def initWithFrame_(self, frame):
            self = objc.super(_PillView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._bg_color = None  # None = transparent (frosted/dark handled elsewhere or inline)
            self._fg_color = NSColor.whiteColor()
            self._style = "dark"
            self._mode = "idle"  # idle, recording, transcribing
            self._phase = 0.0
            return self

        def setStyle_(self, style):
            self._style = style

        def setBackgroundColor_(self, color):
            self._bg_color = color
            self.setNeedsDisplay_(True)

        def setForegroundColor_(self, color):
            self._fg_color = color

        def setMode_(self, mode):
            self._mode = mode
            self._phase = 0.0
            self.setNeedsDisplay_(True)

        def setPhase_(self, phase):
            self._phase = phase
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            bounds = self.bounds()
            pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, PILL_RADIUS, PILL_RADIUS
            )

            # Background fill depends on style
            if self._style == "colored" and self._bg_color:
                self._bg_color.colorWithAlphaComponent_(0.92).setFill()
                pill.fill()
            elif self._style == "dark":
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    *DARK_BG
                ).setFill()
                pill.fill()
            # "frosted" style: background handled by NSVisualEffectView, skip fill

            # Subtle border
            if self._style == "dark":
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1, 1, 1, 0.08
                ).setStroke()
            else:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0, 0, 0, 0.15
                ).setStroke()
            pill.setLineWidth_(0.5)
            pill.stroke()

            # Draw animated content
            if self._mode == "recording":
                self._draw_waveform(bounds)
            elif self._mode == "transcribing":
                self._draw_dots(bounds)

        def _draw_waveform(self, bounds):
            """Draw animated waveform bars."""
            total_w = NUM_BARS * BAR_WIDTH + (NUM_BARS - 1) * BAR_GAP
            start_x = (bounds.size.width - total_w) / 2
            center_y = bounds.size.height / 2

            self._fg_color.colorWithAlphaComponent_(0.95).setFill()

            for i in range(NUM_BARS):
                speed = BAR_SPEEDS[i]
                wave = math.sin(self._phase * speed * 2 * math.pi)
                h = BAR_MIN_H + (BAR_MAX_H - BAR_MIN_H) * (wave + 1) / 2

                x = start_x + i * (BAR_WIDTH + BAR_GAP)
                y = center_y - h / 2

                bar = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(x, y, BAR_WIDTH, h),
                    BAR_WIDTH / 2,
                    BAR_WIDTH / 2,
                )
                bar.fill()

        def _draw_dots(self, bounds):
            """Draw bouncing typing-indicator dots."""
            total_w = NUM_DOTS * (DOT_RADIUS * 2) + (NUM_DOTS - 1) * DOT_GAP
            start_x = (bounds.size.width - total_w) / 2
            base_y = bounds.size.height / 2

            for i in range(NUM_DOTS):
                dot_phase = self._phase - i * DOT_STAGGER / DOT_CYCLE
                t = dot_phase % 1.0
                if t < 0.4:
                    bounce = math.sin(t / 0.4 * math.pi) * DOT_BOUNCE
                else:
                    bounce = 0.0

                cx = start_x + DOT_RADIUS + i * (DOT_RADIUS * 2 + DOT_GAP)
                cy = base_y + bounce

                alpha = 0.95 if t < 0.4 else 0.5
                self._fg_color.colorWithAlphaComponent_(alpha).setFill()

                dot = NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(
                        cx - DOT_RADIUS, cy - DOT_RADIUS,
                        DOT_RADIUS * 2, DOT_RADIUS * 2,
                    )
                )
                dot.fill()

    class OverlayController(NSObject):
        """Controls the floating overlay window. All public methods are thread-safe."""

        def init(self):
            self = objc.super(OverlayController, self).init()
            if self is None:
                return None
            self._window = None
            self._pill_view = None
            self._anim_timer = None
            self._anim_phase = 0.0
            self._state = "idle"  # idle, recording, transcribing
            self._style = "dark"
            self._recording_color = None
            self._transcribing_color = None
            return self

        def setStyle_(self, style):
            self._style = style

        def setColors_transcribing_(self, recording_color, transcribing_color):
            self._recording_color = recording_color
            self._transcribing_color = transcribing_color

        def setup(self):
            """Create the overlay window. Must be called on the main thread."""
            screen = NSScreen.mainScreen()
            screen_frame = screen.frame()
            visible = screen.visibleFrame()
            menu_bar_height = (
                screen_frame.size.height - visible.size.height - visible.origin.y
            )

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

            content = self._window.contentView()
            pill_rect = NSMakeRect(0, 0, PILL_WIDTH, PILL_HEIGHT)

            # Frosted style: add NSVisualEffectView as background layer
            if self._style == "frosted":
                effect_view = NSVisualEffectView.alloc().initWithFrame_(pill_rect)
                # NSVisualEffectMaterialHUDWindow = 13
                effect_view.setMaterial_(13)
                # NSVisualEffectBlendingModeBehindWindow = 0
                effect_view.setBlendingMode_(0)
                # NSVisualEffectStateActive = 1
                effect_view.setState_(1)
                effect_view.setWantsLayer_(True)
                effect_view.layer().setCornerRadius_(PILL_RADIUS)
                effect_view.layer().setMasksToBounds_(True)
                content.addSubview_(effect_view)

            self._pill_view = _PillView.alloc().initWithFrame_(pill_rect)
            self._pill_view.setStyle_(self._style)
            content.addSubview_(self._pill_view)

            self._window.orderFrontRegardless()

        def _fg_color_for_state(self, state):
            """Return the foreground color based on style and state."""
            if self._style == "colored":
                return NSColor.whiteColor()
            # dark / frosted: use the state color as foreground
            if state == "recording":
                return self._recording_color
            return self._transcribing_color

        def show_recording(self):
            """Show pill with waveform animation. Thread-safe."""
            if self._window is None:
                return
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doShowRecording", None, False
            )

        def show_transcribing(self):
            """Show pill with bouncing dots animation. Thread-safe."""
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
            """Main thread: show pill with waveform bars."""
            self._stop_anim()
            self._state = "recording"
            self._pill_view.setBackgroundColor_(self._recording_color)
            self._pill_view.setForegroundColor_(self._fg_color_for_state("recording"))
            self._pill_view.setMode_("recording")
            self._window.setAlphaValue_(1.0)
            self._start_anim()

        def doShowTranscribing(self):
            """Main thread: show pill with bouncing dots."""
            self._stop_anim()
            self._state = "transcribing"
            self._pill_view.setBackgroundColor_(self._transcribing_color)
            self._pill_view.setForegroundColor_(
                self._fg_color_for_state("transcribing")
            )
            self._pill_view.setMode_("transcribing")
            self._start_anim()

        def doHide(self):
            """Main thread: hide the pill."""
            self._stop_anim()
            self._state = "idle"
            self._pill_view.setMode_("idle")
            self._window.setAlphaValue_(0.0)

        def _start_anim(self):
            """Start the animation timer."""
            self._anim_phase = 0.0
            self._anim_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                ANIM_INTERVAL, self, "animTick:", None, True
            )

        def _stop_anim(self):
            """Stop the animation timer."""
            if self._anim_timer:
                self._anim_timer.invalidate()
                self._anim_timer = None

        def animTick_(self, timer):
            """Timer callback: advance animation phase and redraw."""
            self._anim_phase += ANIM_INTERVAL
            self._pill_view.setPhase_(self._anim_phase)


# Module-level singleton
_controller: "OverlayController | None" = None


def init(
    recording_color: str = "#34C759",
    transcribing_color: str = "#A855F7",
    style: str = "dark",
):
    """Initialize the overlay. Must be called on the main thread."""
    global _controller
    if not PYOBJC_AVAILABLE:
        print("Warning: PyObjC not available, overlay disabled")
        return
    _controller = OverlayController.alloc().init()
    _controller.setStyle_(style)
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
