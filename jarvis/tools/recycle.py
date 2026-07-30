"""Send a file or folder to the Recycle Bin for Jarvis -- the safe 'delete'
member of the file tools.

The file family can now locate a file (``find_files`` by name, ``search_files``
by contents, ``recent_files`` by time), rearrange it (``move_file`` /
``copy_file``), back it up (``zip_files``) and restore it (``unzip_files``). The
one everyday action still missing was removing something the user is done with
("delete that draft", "throw the old screenshot in the bin", "delete that whole
folder"). This closes that gap -- WITHOUT ever destroying anything permanently.

Tools:
- ``recycle_file``    -- send a single FILE to the Recycle Bin.
- ``recycle_folder``  -- send a whole FOLDER (and everything in it) to the bin.

Safety model (deletion is the riskiest thing an 8B model can ask for, so this
is deliberately conservative):

- **Never a permanent delete.** The item is sent to the Windows Recycle Bin
  (``FOF_ALLOWUNDO``), so anything Jarvis removes can be restored by the user.
  There is no hard-delete path in this module at all.
- **Rooted in the user's home only.** The path is resolved and REJECTED unless
  it lives inside the user's home directory (same boundary as ``find_files``),
  so Jarvis can never bin something in ``C:\\Windows`` or outside the user's own
  folders. ``recycle_folder`` additionally refuses the home folder itself, so a
  single hallucinated path can never bin the user's entire home.
- **The right tool for the shape.** ``recycle_file`` refuses a folder and points
  the model at ``recycle_folder``; ``recycle_folder`` refuses a file and points
  the model at ``recycle_file`` -- so neither can be tricked into the other's job.
- **Bounded.** An item above a size cap is refused, because Windows permanently
  deletes (no undo) anything too large for the Recycle Bin -- so we simply won't
  touch it and tell the user to remove it themselves. A folder is pre-measured
  (bounded on file count and wall-clock time) and refused if it is too big or too
  large to enumerate, before anything is deleted.
- **Never raises.** Wrong-type / empty / missing args are coerced or rejected,
  and any unexpected error comes back as a friendly, pure-ASCII string the model
  can read and recover from.
"""

import os
import time
from pathlib import Path

from ..config import HOME
from .find import _coerce
from .organize import MAX_PATH_LEN, _ascii, _first_str, _resolve_under_home
from .registry import tool

# Windows permanently deletes items too big for the Recycle Bin (no undo), so we
# refuse anything above this and let the user remove it deliberately instead.
MAX_RECYCLE_BYTES = 1024 * 1024 * 1024  # 1 GB

# A folder with more files than this (or one that takes too long to enumerate) is
# refused before any delete, so a hallucinated "delete everything" can't stall.
MAX_RECYCLE_FILES = 20000
RECYCLE_TIME_BUDGET = 15.0  # wall-clock cap while pre-measuring a folder (seconds)


def _mb(n: int) -> str:
    """Human, pure-ASCII size phrase."""
    gb = n / (1024.0 ** 3)
    if gb >= 1.0:
        return f"{gb:.1f} GB"
    mb = n / (1024.0 * 1024.0)
    if mb >= 1.0:
        return f"{mb:.1f} MB"
    return f"{n / 1024.0:.1f} KB"


def _send_to_recycle_bin(path: str) -> None:
    """Move a single existing file to the Windows Recycle Bin (undoable).

    Raises on any failure so the caller can report it. Kept as a module-level
    function so the smoke test can swap in a hermetic fake instead of touching
    the user's real Recycle Bin. Uses the Win32 shell API via ctypes -- no new
    dependency, mirroring the clipboard tool."""
    import ctypes
    from ctypes import wintypes

    FO_DELETE = 0x0003
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),          # FILEOP_FLAGS is a WORD
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # SHFileOperation wants an absolute path, double-null terminated.
    buf = ctypes.create_unicode_buffer(str(path) + "\x00")  # adds a 2nd NUL
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

    shell32 = ctypes.windll.shell32
    shell32.SHFileOperationW.argtypes = [ctypes.c_void_p]
    shell32.SHFileOperationW.restype = ctypes.c_int
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise OSError(f"shell delete failed (code {rc})")
    if op.fAnyOperationsAborted:
        raise OSError("shell delete was aborted")


@tool(
    "recycle_file",
    "Send a file to the Recycle Bin (a safe, undoable delete). Use this when the "
    "user asks to delete, remove, or throw away a file they are done with "
    "('delete that draft', 'remove the old screenshot', 'bin my notes'). Give "
    "path: the file to delete (locate it first with find_files if you don't have "
    "the exact path). Only the user's own folders are allowed, only single files "
    "(not whole folders), and nothing is destroyed permanently -- the user can "
    "restore it from the Recycle Bin.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file to send to the Recycle Bin, e.g. "
                "'Desktop/old_draft.txt'.",
            },
        },
        "required": ["path"],
    },
)
def recycle_file(path: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("source"),
                     extra.get("src"), extra.get("target"), extra.get("name"),
                     extra.get("filename"), extra.get("file_path"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me which file to delete, sir."

    src, err = _resolve_under_home(raw)
    if src is None:
        return err or "Error: that file path isn't valid, sir."
    if not src.exists():
        return f"Error: I can't find '{_ascii(str(src))}', sir."
    if src.is_dir():
        return (f"Error: '{_ascii(src.name)}' is a folder, sir; use "
                "recycle_folder for a whole folder, not recycle_file.")

    try:
        size = src.stat().st_size
    except OSError:
        size = 0
    if size > MAX_RECYCLE_BYTES:
        return (f"Error: that file is {_mb(size)}, too large to send to the "
                f"Recycle Bin safely, sir (limit {_mb(MAX_RECYCLE_BYTES)}); "
                "Windows would delete it for good. Remove it yourself if sure.")

    try:
        _send_to_recycle_bin(str(src))
    except Exception as e:
        return f"Error: couldn't delete it, sir ({_ascii(str(e))})."

    # Confirm it actually left its place before claiming success.
    try:
        still_there = src.exists()
    except OSError:
        still_there = False
    if still_there:
        return (f"Error: I couldn't move '{_ascii(src.name)}' to the Recycle "
                "Bin, sir; it is still there.")

    return (f"Sent {_ascii(src.name)} to the Recycle Bin, sir. You can restore "
            "it from there if you need it back.")


def _measure_folder(root: Path):
    """Measure a folder subtree for a recycle: returns (n_files, total_bytes,
    error_or_empty).

    Deleting a whole tree is the riskiest thing the model can ask for, so this
    pre-scan is bounded on file count and wall-clock time and refuses (returns a
    friendly error string) BEFORE anything is deleted if the folder is too big to
    enumerate. Nothing is pruned, so the count is honest. Never raises."""
    n_files = 0
    total = 0
    started = time.monotonic()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                try:
                    total += (Path(dirpath) / fn).stat().st_size
                except OSError:
                    continue  # vanished / permission: skip, never crash
                n_files += 1
                if n_files > MAX_RECYCLE_FILES:
                    return n_files, total, ("Error: that folder has too many "
                                            "files for me to bin safely, sir; "
                                            "remove it yourself if you're sure.")
            if time.monotonic() - started > RECYCLE_TIME_BUDGET:
                return n_files, total, ("Error: that folder took too long to "
                                        "check, sir; remove it yourself if "
                                        "you're sure.")
    except Exception:
        pass  # last-resort guard: use whatever we measured, never crash
    return n_files, total, ""


@tool(
    "recycle_folder",
    "Send a whole folder (and everything in it) to the Recycle Bin (a safe, "
    "undoable delete). Use this when the user asks to delete, remove, or throw "
    "away a FOLDER they are done with ('delete that whole folder', 'remove my old "
    "Projects folder', 'bin the Temp folder'). Give path: the folder to delete "
    "(locate it first with find_files if you don't have the exact path). Only the "
    "user's own folders are allowed (never the home folder itself), and nothing is "
    "destroyed permanently -- the user can restore it from the Recycle Bin. For a "
    "single file use recycle_file instead.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The folder to send to the Recycle Bin, e.g. "
                "'Desktop/Old Projects'.",
            },
        },
        "required": ["path"],
    },
)
def recycle_folder(path: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("folder"), extra.get("source"),
                     extra.get("src"), extra.get("target"), extra.get("name"),
                     extra.get("directory"), extra.get("dir"),
                     extra.get("dir_path"), extra.get("folder_path"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me which folder to delete, sir."

    src, err = _resolve_under_home(raw)
    if src is None:
        return err or "Error: that folder path isn't valid, sir."

    try:
        home = Path(HOME).resolve()
    except OSError:
        home = None
    if home is not None and src == home:
        return ("Error: that is your home folder, sir; I won't bin the whole "
                "thing.")
    if not src.exists():
        return f"Error: I can't find '{_ascii(str(src))}', sir."
    if src.is_file():
        return (f"Error: '{_ascii(src.name)}' is a file, sir; use recycle_file "
                "for a single file, not recycle_folder.")
    if not src.is_dir():
        return f"Error: '{_ascii(str(src))}' isn't a normal folder, sir."

    n_files, total, merr = _measure_folder(src)
    if merr:
        return merr
    if total > MAX_RECYCLE_BYTES:
        return (f"Error: that folder is {_mb(total)}, too large to send to the "
                f"Recycle Bin safely, sir (limit {_mb(MAX_RECYCLE_BYTES)}); "
                "Windows would delete it for good. Remove it yourself if sure.")

    try:
        _send_to_recycle_bin(str(src))
    except Exception as e:
        return f"Error: couldn't delete it, sir ({_ascii(str(e))})."

    # Confirm it actually left its place before claiming success.
    try:
        still_there = src.exists()
    except OSError:
        still_there = False
    if still_there:
        return (f"Error: I couldn't move '{_ascii(src.name)}' to the Recycle "
                "Bin, sir; it is still there.")

    count = (f" ({n_files} file{'s' if n_files != 1 else ''}, {_mb(total)})"
             if n_files else " (empty)")
    return (f"Sent folder {_ascii(src.name)}{count} to the Recycle Bin, sir. "
            "You can restore it from there if you need it back.")
