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

# Text
FONT_SIZE_LARGE = 18.0   # flash labels, loading text
FONT_SIZE_SMALL = 11.0   # language badge during recording
FONT_WEIGHT = 0.23       # semi-light weight for large text
FLASH_DURATION = 1.0     # seconds before flash auto-fades

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
            self._mode = "idle"  # idle, recording, transcribing, language_flash
            self._phase = 0.0
            self._label = None  # e.g. "AF"
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

        def setLabel_(self, label):
            self._label = label
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
                if self._label:
                    self._draw_label(bounds, large=False)
            elif self._mode == "transcribing":
                self._draw_dots(bounds)
            elif self._mode == "language_flash":
                self._draw_label(bounds, large=True)


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

        def _draw_label(self, bounds, large=False):
            """Draw language code text centered in the pill."""
            from AppKit import NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSString
            text = NSString.stringWithString_(self._label)
            font_size = FONT_SIZE_LARGE if large else FONT_SIZE_SMALL
            font = NSFont.systemFontOfSize_weight_(font_size, FONT_WEIGHT) if large else NSFont.boldSystemFontOfSize_(font_size)
            attrs = {
                NSFontAttributeName: font,
                NSForegroundColorAttributeName: self._fg_color.colorWithAlphaComponent_(0.95),
            }
            text_size = text.sizeWithAttributes_(attrs)
            if large:
                x = (bounds.size.width - text_size.width) / 2
            else:
                x = bounds.size.width - text_size.width - 10
            y = (bounds.size.height - text_size.height) / 2
            text.drawAtPoint_withAttributes_((x, y), attrs)

    class OverlayController(NSObject):
        """Controls the floating overlay window. All public methods are thread-safe."""

        # Fixed accent colors
        RECORDING_COLOR = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0x34 / 255.0, 0xC7 / 255.0, 0x59 / 255.0, 1.0  # #34C759
        )
        TRANSCRIBING_COLOR = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0xA8 / 255.0, 0x55 / 255.0, 0xF7 / 255.0, 1.0  # #A855F7
        )

        def init(self):
            self = objc.super(OverlayController, self).init()
            if self is None:
                return None
            self._window = None
            self._pill_view = None
            self._anim_timer = None
            self._anim_phase = 0.0
            self._state = "idle"  # idle, recording, transcribing, language_flash
            self._style = "dark"
            self._fade_timer = None
            self._effect_view = None
            return self

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
                self._effect_view = self._create_effect_view(pill_rect)
                content.addSubview_(self._effect_view)

            self._pill_view = _PillView.alloc().initWithFrame_(pill_rect)
            self._pill_view.setStyle_(self._style)
            content.addSubview_(self._pill_view)

            self._window.orderFrontRegardless()

        def _fg_color_for_state(self, state):
            """Return the foreground color based on style and state."""
            if self._style == "colored" or state == "transcribing":
                return NSColor.whiteColor()
            # dark / frosted recording: use the recording color as foreground
            return self.RECORDING_COLOR

        def _create_effect_view(self, frame):
            """Create an NSVisualEffectView for frosted glass style."""
            effect_view = NSVisualEffectView.alloc().initWithFrame_(frame)
            effect_view.setMaterial_(13)  # NSVisualEffectMaterialHUDWindow
            effect_view.setBlendingMode_(0)  # NSVisualEffectBlendingModeBehindWindow
            effect_view.setState_(1)  # NSVisualEffectStateActive
            effect_view.setWantsLayer_(True)
            effect_view.layer().setCornerRadius_(PILL_RADIUS)
            effect_view.layer().setMasksToBounds_(True)
            return effect_view

        def update_style(self, style):
            """Update overlay style. Thread-safe."""
            self._style = style
            if self._pill_view:
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "doUpdateStyle:", style, False
                )

        def doUpdateStyle_(self, style):
            """Main thread: update pill view style and manage frosted effect view."""
            if not self._pill_view:
                return
            self._pill_view.setStyle_(style)

            # Remove old frosted effect view if present
            if self._effect_view:
                self._effect_view.removeFromSuperview()
                self._effect_view = None

            # Add frosted effect view if switching to frosted
            if style == "frosted" and self._window:
                content = self._window.contentView()
                self._effect_view = self._create_effect_view(self._pill_view.frame())
                # Insert behind the pill view
                content.addSubview_positioned_relativeTo_(
                    self._effect_view, -1, self._pill_view  # NSWindowBelow = -1
                )

        def show_recording(self, label=None):
            """Show pill with waveform animation. Thread-safe."""
            if self._window is None:
                return
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doShowRecording:", label, False
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

        def doShowRecording_(self, label):
            """Main thread: show pill with waveform bars."""
            self._stop_anim()
            self._cancel_fade()
            self._set_pill_width(PILL_WIDTH)
            self._state = "recording"
            self._pill_view.setLabel_(label)
            self._pill_view.setBackgroundColor_(self.RECORDING_COLOR)
            self._pill_view.setForegroundColor_(self._fg_color_for_state("recording"))
            self._pill_view.setMode_("recording")
            self._window.setAlphaValue_(1.0)
            self._start_anim()

        def doShowTranscribing(self):
            """Main thread: show pill with bouncing dots."""
            self._stop_anim()
            self._cancel_fade()
            self._set_pill_width(PILL_WIDTH)
            self._state = "transcribing"
            self._pill_view.setLabel_(None)
            self._pill_view.setBackgroundColor_(self.TRANSCRIBING_COLOR)
            self._pill_view.setForegroundColor_(
                self._fg_color_for_state("transcribing")
            )
            self._pill_view.setMode_("transcribing")
            self._start_anim()

        def doHide(self):
            """Main thread: hide the pill."""
            self._stop_anim()
            self._cancel_fade()
            self._set_pill_width(PILL_WIDTH)
            self._state = "idle"
            self._pill_view.setLabel_(None)
            self._pill_view.setMode_("idle")
            self._window.setAlphaValue_(0.0)

        def show_flash(self, text):
            """Flash the pill with arbitrary text. Thread-safe."""
            if self._window is None:
                return
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doShowFlash:", text, False
            )

        def show_language_flash(self, lang_code):
            """Flash the pill with a language code. Thread-safe."""
            if self._window is None:
                return
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doShowLanguageFlash:", lang_code.upper(), False
            )

        def doShowFlash_(self, text):
            """Main thread: show pill with arbitrary text, auto-fade after 1.5s."""
            self._stop_anim()
            self._cancel_fade()
            self._state = "language_flash"
            self._pill_view.setLabel_(text)
            self._pill_view.setBackgroundColor_(self.RECORDING_COLOR)
            self._pill_view.setForegroundColor_(NSColor.whiteColor())
            self._pill_view.setMode_("language_flash")
            # Resize pill width to fit text
            self._resize_pill(text)
            self._window.setAlphaValue_(1.0)
            self._fade_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                FLASH_DURATION, self, "fadeOut:", None, False
            )

        def doShowLanguageFlash_(self, lang_code):
            """Main thread: show pill with language code, auto-fade after 1.5s."""
            self._stop_anim()
            self._cancel_fade()
            self._state = "language_flash"
            self._pill_view.setLabel_(lang_code)
            self._pill_view.setBackgroundColor_(self.RECORDING_COLOR)
            self._pill_view.setForegroundColor_(NSColor.whiteColor())
            self._pill_view.setMode_("language_flash")
            self._window.setAlphaValue_(1.0)
            self._fade_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                FLASH_DURATION, self, "fadeOut:", None, False
            )

        def _resize_pill(self, text, font_size=FONT_SIZE_LARGE, padding=40):
            """Resize the pill window width to fit the given text, centered on screen."""
            from AppKit import NSFont, NSFontAttributeName, NSString
            ns_text = NSString.stringWithString_(text)
            font = NSFont.systemFontOfSize_weight_(font_size, FONT_WEIGHT)
            text_width = ns_text.sizeWithAttributes_({NSFontAttributeName: font}).width
            new_width = max(PILL_WIDTH, text_width + padding)
            self._set_pill_width(new_width)

        def _set_pill_width(self, width):
            """Set the pill window to the given width, centered on screen."""
            screen = NSScreen.mainScreen()
            screen_frame = screen.frame()
            x = (screen_frame.size.width - width) / 2
            frame = self._window.frame()
            frame.origin.x = x
            frame.size.width = width
            self._window.setFrame_display_(frame, True)
            pill_rect = NSMakeRect(0, 0, width, PILL_HEIGHT)
            self._pill_view.setFrame_(pill_rect)
            if self._effect_view:
                self._effect_view.setFrame_(pill_rect)

        def fadeOut_(self, timer):
            """Timer callback: hide the pill after flash."""
            self._fade_timer = None
            self._pill_view.setLabel_(None)
            self._pill_view.setMode_("idle")
            self._window.setAlphaValue_(0.0)
            # Restore default pill width
            self._set_pill_width(PILL_WIDTH)

        def _cancel_fade(self):
            """Cancel any pending fade timer."""
            if self._fade_timer:
                self._fade_timer.invalidate()
                self._fade_timer = None

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


def init(style: str = "dark"):
    """Initialize the overlay. Must be called on the main thread."""
    global _controller
    if not PYOBJC_AVAILABLE:
        print("Warning: PyObjC not available, overlay disabled")
        return
    _controller = OverlayController.alloc().init()
    _controller._style = style
    _controller.setup()


def show_recording(label=None):
    if _controller:
        _controller.show_recording(label=label)


def update_style(style="dark"):
    """Update overlay style. Thread-safe (can be called from any thread)."""
    if _controller:
        _controller.update_style(style)


def show_flash(text):
    if _controller:
        _controller.show_flash(text)


def show_language_flash(lang_code):
    if _controller:
        _controller.show_language_flash(lang_code)


def show_transcribing():
    if _controller:
        _controller.show_transcribing()


def hide():
    if _controller:
        _controller.hide()
