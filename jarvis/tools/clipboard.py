"""Windows clipboard access for Jarvis.

A real autonomy win: instead of the user having to retype or paste text into
the console, Jarvis can read whatever was just copied from ANY app ("summarize
what I copied", "translate my clipboard", "what did I just copy?") and can put
its own answer back on the clipboard for the user to paste with Ctrl+V ("copy
that", "put it on my clipboard"). It bridges every other program to Jarvis.

Implemented directly on the Win32 clipboard API through ``ctypes`` — no extra
dependency, and Unicode-correct (``CF_UNICODETEXT``).

Safety model (this file is the strict error handling the project asks for,
because an 8B local model WILL eventually pass junk, the wrong type, or a
novel of text):

- **Never raises.** Every clipboard call is wrapped; a wrong-type arg is
  coerced to text, and any OS failure comes back as a friendly string the
  model can read and recover from — the agent can't crash.
- **Bounded both ways.** Reads are capped (a huge clipboard is truncated with
  a note) and writes over a hard limit are rejected, so the model can't dump a
  megabyte into system memory.
- **Locked-clipboard tolerant.** Another app can hold the clipboard open for a
  moment; open is retried a few times, then a clear message is returned.
- **Non-text tolerant.** If the clipboard holds an image or is empty, Jarvis
  says so instead of erroring.
- **Read-only to the rest of the machine.** It only ever touches the
  clipboard; nothing on disk, no shell, no network.
"""

import ctypes
from ctypes import wintypes

from .registry import tool

MAX_READ = 20000     # chars returned from a read (rest truncated with a note)
MAX_WRITE = 100000   # most chars we'll accept onto the clipboard

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_OPEN_RETRIES = 5    # another app may briefly hold the clipboard

# ---------------------------------------------------------------------------
# Win32 bindings, with 64-bit-safe argtypes/restypes so handles/pointers are
# never truncated to 32 bits (the classic ctypes clipboard bug).
# ---------------------------------------------------------------------------
try:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalSize.restype = ctypes.c_size_t
    _WIN_OK = True
except Exception:  # non-Windows or restricted host — degrade gracefully
    _WIN_OK = False


def _open_clipboard() -> bool:
    """Try to take the clipboard, tolerating another app briefly holding it."""
    import time
    for _ in range(_OPEN_RETRIES):
        if _user32.OpenClipboard(0):
            return True
        time.sleep(0.03)
    return False


def _read_clipboard_text() -> tuple[str | None, str]:
    """Return (text, "") on success, or (None, reason) if unavailable.
    ``text`` may be "" for an empty text clipboard."""
    if not _WIN_OK:
        return None, "the clipboard isn't available on this system, sir"
    if not _user32.IsClipboardFormatAvailable(_CF_UNICODETEXT):
        return None, "there is no text on the clipboard right now, sir"
    if not _open_clipboard():
        return None, "the clipboard is busy right now, sir - try again"
    try:
        handle = _user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return "", ""
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return None, "couldn't read the clipboard, sir"
        try:
            text = ctypes.wstring_at(ptr)
        finally:
            _kernel32.GlobalUnlock(handle)
        return text, ""
    except Exception as e:  # last-resort guard
        return None, f"clipboard read failed ({e})"
    finally:
        _user32.CloseClipboard()


def _write_clipboard_text(text: str) -> str:
    """Put ``text`` on the clipboard. Returns "" on success or an error text."""
    if not _WIN_OK:
        return "the clipboard isn't available on this system, sir"
    if not _open_clipboard():
        return "the clipboard is busy right now, sir - try again"
    try:
        _user32.EmptyClipboard()
        # +1 for the terminating null; 2 bytes per UTF-16 char
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        h_mem = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
        if not h_mem:
            return "the clipboard is out of memory, sir"
        ptr = _kernel32.GlobalLock(h_mem)
        if not ptr:
            return "couldn't lock clipboard memory, sir"
        ctypes.memmove(ptr, buf, size)
        _kernel32.GlobalUnlock(h_mem)
        if not _user32.SetClipboardData(_CF_UNICODETEXT, h_mem):
            return "the clipboard rejected the text, sir"
        return ""
    except Exception as e:  # last-resort guard
        return f"clipboard write failed ({e})"
    finally:
        _user32.CloseClipboard()


def _coerce(value) -> str:
    """Turn any model-supplied value into a plain string (never raises)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)  # model sometimes passes a number / list / dict
    except Exception:
        return ""


@tool(
    "get_clipboard",
    "Read the text the user last copied to the Windows clipboard. Use when "
    "the user refers to something they copied - e.g. 'summarize what I "
    "copied', 'translate my clipboard', 'what did I just copy?' - so you can "
    "act on it without them retyping it.",
)
def get_clipboard() -> str:
    try:
        text, reason = _read_clipboard_text()
    except Exception as e:  # belt-and-braces: never crash the agent
        return f"Sorry sir, I couldn't read the clipboard ({e})."
    if text is None:
        return f"Sorry sir, {reason}."
    if text == "":
        return "The clipboard is empty, sir."
    n = len(text)
    if n > MAX_READ:
        text = text[:MAX_READ] + "\n...[clipboard truncated]"
    return f"Clipboard ({n} characters):\n{text}"


@tool(
    "set_clipboard",
    "Copy text onto the Windows clipboard so the user can paste it anywhere "
    "with Ctrl+V. Use when the user says 'copy that', 'put it on my "
    "clipboard', or wants your answer ready to paste elsewhere.",
    {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The exact text to place on the clipboard.",
            },
        },
        "required": ["text"],
    },
)
def set_clipboard(text: str = "") -> str:
    text = _coerce(text)
    if text == "":
        return ("Error: there's nothing to copy, sir - give me the text to "
                "put on the clipboard.")
    if len(text) > MAX_WRITE:
        return (f"Error: that's too much to copy at once, sir "
                f"({len(text)} characters; my limit is {MAX_WRITE}).")
    err = _write_clipboard_text(text)
    if err:
        return f"Sorry sir, {err}."
    n = len(text)
    return f"Copied {n} character{'s' if n != 1 else ''} to the clipboard, sir."
