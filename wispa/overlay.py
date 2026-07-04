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
WAVE_POINTS = 48
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
        pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, HEIGHT / 2, HEIGHT / 2
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.92).setFill()
        pill.fill()

        levels = list(self.level_source()) if self.level_source else []
        now = time.monotonic()
        pad = 12.0
        usable = WIDTH - 2 * pad
        cy = HEIGHT / 2

        if self.mode == "recording":
            # Amplitude follows the last few mic levels, smoothed
            recent = levels[-6:] if levels else [0.0]
            lvl = max(0.0, sum(recent) / len(recent) - 0.004)
            amp = 1.5 + min(lvl * 90, cy - 5)
            speed, cycles = 14.0, 2.5
        else:  # processing: calm steady ripple
            amp = 2.2
            speed, cycles = 6.0, 2.5

        wave = NSBezierPath.bezierPath()
        wave.setLineWidth_(1.6)
        wave.setLineCapStyle_(1)  # round
        for i in range(WAVE_POINTS):
            t = i / (WAVE_POINTS - 1)
            envelope = math.sin(t * math.pi)  # pinch the wave at both ends
            y = cy + amp * envelope * math.sin(t * cycles * 2 * math.pi - now * speed)
            x = pad + t * usable
            if i == 0:
                wave.moveToPoint_((x, y))
            else:
                wave.lineToPoint_((x, y))
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.9).setStroke()
        wave.stroke()

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
