"""What app is the user dictating into? Fed to the cleanup LLM so it can match tone."""

from AppKit import NSWorkspace


def frontmost_app_name() -> str:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return "unknown"
    return str(app.localizedName() or "unknown")
