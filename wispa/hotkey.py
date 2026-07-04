"""Global push-to-talk hotkey via a Quartz event tap.

Watches flagsChanged events system-wide (this is how you catch Fn — it's a
modifier flag, not a regular key). Requires the Accessibility / Input
Monitoring permission for the process running Python.
"""

from typing import Callable

import Quartz

# Right Option reports the Alternate flag plus this device-dependent flag bit.
NX_DEVICERALTKEYMASK = 0x0040


def _fn_down(flags: int) -> bool:
    return bool(flags & Quartz.kCGEventFlagMaskSecondaryFn)


def _right_option_down(flags: int) -> bool:
    return bool(flags & Quartz.kCGEventFlagMaskAlternate) and bool(
        flags & NX_DEVICERALTKEYMASK
    )


def _ctrl_option_down(flags: int) -> bool:
    return bool(flags & Quartz.kCGEventFlagMaskControl) and bool(
        flags & Quartz.kCGEventFlagMaskAlternate
    )


_DETECTORS = {
    "fn": _fn_down,
    "right_option": _right_option_down,
    "ctrl_option": _ctrl_option_down,
}


class PushToTalkListener:
    """Calls on_press when the configured hotkey goes down, on_release when it
    comes back up. run() blocks; call it from the main thread."""

    def __init__(self, hotkey: str, on_press: Callable[[], None], on_release: Callable[[], None]):
        if hotkey not in _DETECTORS:
            raise ValueError(f"Unknown hotkey {hotkey!r}; use one of {sorted(_DETECTORS)}")
        self._detect = _DETECTORS[hotkey]
        self._on_press = on_press
        self._on_release = on_release
        self._held = False

    def _callback(self, proxy, event_type, event, refcon):
        # macOS disables a tap that stalls or after a wake; re-enable and move on.
        if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        flags = Quartz.CGEventGetFlags(event)
        down = self._detect(flags)
        if down and not self._held:
            self._held = True
            self._on_press()
        elif not down and self._held:
            self._held = False
            self._on_release()
        return event

    def install(self):
        """Create the tap and attach it to the current (main) run loop.
        Something else — e.g. the AppKit event loop — must then run that loop."""
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
            self._callback,
            None,
        )
        if self._tap is None:
            raise PermissionError(
                "Could not create event tap. Grant Accessibility permission to your "
                "terminal app in System Settings > Privacy & Security > Accessibility, "
                "then restart wispa."
            )
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)

    def run(self):
        """Headless variant: install and block on a plain CFRunLoop."""
        self.install()
        Quartz.CFRunLoopRun()
