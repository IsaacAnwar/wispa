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
