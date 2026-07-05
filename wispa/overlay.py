"""Wispr-style pill at the bottom of the screen: live waveform while recording,
a gentle pulse while processing.

The panel is borderless, non-activating, click-through, and floats above
everything (including fullscreen apps) — showing it never steals focus from
the app receiving the dictation.
"""

import math
import time

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSTimer,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)

WIDTH, HEIGHT = 96, 22
MARGIN_BOTTOM = 40
PIXEL = 2.0  # side of one square "pixel"
GAP = 0.8  # spacing between pixels
FPS = 30.0


class _PillView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(_PillView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.mode = "recording"
        self.level_source = None
        return self

    def drawRect_(self, rect):
        bounds = self.bounds()
        pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 5, 5)
        NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.92).setFill()
        pill.fill()

        levels = list(self.level_source()) if self.level_source else []
        now = time.monotonic()
        pad = 12.0
        usable = WIDTH - 2 * pad
        cy = HEIGHT / 2
        step = PIXEL + GAP
        cols = int(usable // step)
        # How many pixels can stack above/below the center row
        max_steps = int((cy - 2) // step)

        if self.mode == "recording":
            # Peak (not average) of the freshest chunks so each syllable lands,
            # with compressive gain so quiet speech still moves the pixels
            recent = levels[-4:] if levels else [0.0]
            lvl = min((max(0.0, max(recent) - 0.003) * 18) ** 0.7, 1.0)
            speed = 18.0
        else:  # processing: calm steady ripple
            lvl = 0.35
            speed = 5.0

        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.9).setFill()
        for i in range(cols):
            t = i / max(cols - 1, 1)
            envelope = math.sin(t * math.pi)  # taper toward the pill's ends
            # Two out-of-sync sines per column so the jitter never looks looped
            bounce = (2 + math.sin(now * speed + i * 1.7) + math.sin(now * speed * 1.6 + i * 3.1)) / 4
            # Level drives the height; bounce only modulates it, so pixels stay
            # tall while you talk instead of collapsing between beats.
            # Quantize to whole pixels — this is what makes it read as 8-bit
            n = round(envelope * lvl * (0.45 + 0.55 * bounce) * max_steps + 0.3)
            x = pad + i * step
            for k in range(-n, n + 1):  # mirrored around the center row
                y = cy - PIXEL / 2 + k * step
                pixel = NSBezierPath.bezierPathWithRect_(NSMakeRect(x, y, PIXEL, PIXEL))
                pixel.fill()

    def tick_(self, timer):
        self.setNeedsDisplay_(True)


class Overlay:
    """Call only from the main thread (use AppHelper.callAfter from workers)."""

    def __init__(self, level_source):
        rect = NSMakeRect(0, 0, WIDTH, HEIGHT)
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setLevel_(NSStatusWindowLevel)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setHasShadow_(True)
        self._panel.setIgnoresMouseEvents_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self._view = _PillView.alloc().initWithFrame_(rect)
        self._view.level_source = level_source
        self._panel.setContentView_(self._view)
        self._timer = None

    def _position(self):
        screen = NSScreen.mainScreen() or NSScreen.screens()[0]
        frame = screen.frame()
        x = frame.origin.x + (frame.size.width - WIDTH) / 2
        y = frame.origin.y + MARGIN_BOTTOM
        self._panel.setFrameOrigin_((x, y))

    def show_recording(self):
        self._view.mode = "recording"
        self._position()
        self._panel.orderFrontRegardless()
        if self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / FPS, self._view, "tick:", None, True
            )

    def show_processing(self):
        self._view.mode = "processing"

    def hide(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        self._panel.orderOut_(None)
