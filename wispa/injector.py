"""Put text at the cursor of whatever app has focus.

Primary path: direct insertion through the macOS Accessibility API — find the
focused UI element and set its selected text (with an empty selection this
inserts at the caret, exactly what Wispr Flow does).

Fallback: save clipboard -> copy text -> synthetic Cmd+V -> restore clipboard.
"""

import time

import ApplicationServices as AX
import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString

KEYCODE_V = 9

_CFRANGE_TYPE = getattr(AX, "kAXValueTypeCFRange", None) or getattr(AX, "kAXValueCFRangeType", 4)


def _utf16_len(text: str) -> int:
    # AX text ranges count UTF-16 code units, not Python characters
    return len(text.encode("utf-16-le")) // 2


def _caret_position(element):
    """End of the current selection in UTF-16 units, or None if unreadable."""
    err, value = AX.AXUIElementCopyAttributeValue(
        element, AX.kAXSelectedTextRangeAttribute, None
    )
    if err != AX.kAXErrorSuccess or value is None:
        return None
    ok, rng = AX.AXValueGetValue(value, _CFRANGE_TYPE, None)
    if not ok:
        return None
    location, length = rng  # pyobjc hands CFRange back as a (location, length) tuple
    return int(location + length)


def _set_caret(element, location) -> bool:
    value = AX.AXValueCreate(_CFRANGE_TYPE, (location, 0))
    if value is None:
        return False
    err = AX.AXUIElementSetAttributeValue(
        element, AX.kAXSelectedTextRangeAttribute, value
    )
    return err == AX.kAXErrorSuccess


def _focused_element():
    system_wide = AX.AXUIElementCreateSystemWide()
    err, element = AX.AXUIElementCopyAttributeValue(
        system_wide, AX.kAXFocusedUIElementAttribute, None
    )
    if err != AX.kAXErrorSuccess:
        return None
    return element


def insert_via_ax(text: str) -> bool:
    element = _focused_element()
    if element is None:
        return False
    err, settable = AX.AXUIElementIsAttributeSettable(
        element, AX.kAXSelectedTextAttribute, None
    )
    if err != AX.kAXErrorSuccess or not settable:
        return False
    err = AX.AXUIElementSetAttributeValue(element, AX.kAXSelectedTextAttribute, text)
    return err == AX.kAXErrorSuccess


def insert_via_paste(text: str, restore_clipboard: bool = True):
    pb = NSPasteboard.generalPasteboard()
    saved = pb.stringForType_(NSPasteboardTypeString) if restore_clipboard else None

    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)

    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, KEYCODE_V, down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    if saved is not None:
        # Give the target app a beat to read the pasteboard before restoring it
        time.sleep(0.3)
        pb.clearContents()
        pb.setString_forType_(saved, NSPasteboardTypeString)


def insert(text: str, method: str = "ax", restore_clipboard: bool = True) -> str:
    """Returns which path was used: "ax" or "paste"."""
    if method == "ax" and insert_via_ax(text):
        return "ax"
    insert_via_paste(text, restore_clipboard)
    return "paste"


class StreamInserter:
    """Inserts text at the caret as it streams in.

    Each feed() inserts via AX on a target element pinned at the first piece,
    then VERIFIES the caret advanced past what was inserted — some apps
    (notably web/Electron text fields) leave the caret behind, which would
    scramble the order of later pieces. If the caret lags we move it
    ourselves; if the app won't cooperate (or the caret isn't even readable)
    we stop streaming and buffer, and finish() inserts the remainder in one
    ordered shot with the usual paste fallback.
    """

    # An app whose AX round-trips are slower than this isn't worth streaming
    # into — the text would dribble in long after the user stopped talking
    SLOW_FEED_S = 0.20

    def __init__(self, method: str = "ax", restore_clipboard: bool = True):
        self._method = method
        self._restore_clipboard = restore_clipboard
        self._buffering = method != "ax"
        self._pending: list[str] = []
        self._element = None
        self._expected = None  # caret position we left behind, in UTF-16 units
        self._slow_feeds = 0
        self.received = False
        self.streamed = False

    def feed(self, piece: str):
        self.received = True
        if self._buffering:
            self._pending.append(piece)
            return
        t0 = time.perf_counter()
        if self._element is None:
            self._element = _focused_element()
        element = self._element
        before = self._expected
        if before is None:
            before = _caret_position(element) if element is not None else None
        if before is None:
            # Can't verify ordering in this app — don't stream blind
            self._buffering = True
            self._pending.append(piece)
            return
        err = AX.AXUIElementSetAttributeValue(element, AX.kAXSelectedTextAttribute, piece)
        if err != AX.kAXErrorSuccess:
            self._buffering = True
            self._pending.append(piece)
            return
        expected = before + _utf16_len(piece)
        if _caret_position(element) != expected:
            # App left the caret behind; put it after what we just inserted
            if not (_set_caret(element, expected) and _caret_position(element) == expected):
                # Piece is in the document but the caret is untrustworthy:
                # stop streaming so later pieces can't land out of order
                self._buffering = True
                self.streamed = True
                return
        self._expected = expected
        self.streamed = True
        # Electron/web apps can take 100ms+ per AX round-trip; if this target
        # is slow, stop streaming and deliver the rest in one shot instead
        if time.perf_counter() - t0 > self.SLOW_FEED_S:
            self._slow_feeds += 1
            if self._slow_feeds >= 2:
                self._buffering = True

    def finish(self) -> str:
        """Insert anything buffered; returns a label for how text went in."""
        if self._pending:
            path = insert("".join(self._pending), self._method, self._restore_clipboard)
            return f"ax-stream+{path}" if self.streamed else path
        return "ax-stream" if self.streamed else "none"
