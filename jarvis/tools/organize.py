"""Move, rename and copy files for Jarvis -- the action half of the file tools.

The file-navigation family lets Jarvis FIND a file (``find_files`` by name,
``search_files`` by contents, ``recent_files`` by time), but until now it could
only read or open a result. This closes the loop: once Jarvis has located a
file it can actually organise it -- "move the budget spreadsheet into
Documents", "rename my resume to CV.pdf", "make a copy of my notes" -- a real
autonomy win.

Two tools:
- ``move_file``  -- move a file into a folder, or rename it.
- ``copy_file``  -- duplicate a file (the original stays put).

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or try to clobber the wrong file):

- **Rooted in the user's home only.** Both the source AND the destination are
  resolved and REJECTED unless they live inside the user's home directory
  (same boundary as ``find_files``), so the model can never move a file into
  ``C:\\Windows`` or drag one out of the user's own folders.
- **Never overwrites.** If something already exists at the destination the move
  or copy is REFUSED -- an 8B hallucination can never silently destroy an
  existing file. Deleting is not offered at all.
- **Files only.** A folder source is refused, so a whole tree can't be moved by
  accident.
- **Bounded.** ``copy_file`` refuses a file above a size cap so a hallucinated
  copy of a huge file can't hang or fill the disk. A move is a rename.
- **Never raises.** Wrong-type / empty / missing args are coerced or rejected,
  and any unexpected filesystem error comes back as a friendly, pure-ASCII
  string the model can read and recover from.
"""

import shutil
from pathlib import Path

from ..config import HOME
from .find import _coerce
from .registry import tool

MAX_PATH_LEN = 400                       # a path, not an essay
MAX_NAME_LEN = 200                       # a file name, not a paragraph
MAX_COPY_BYTES = 500 * 1024 * 1024       # refuse to copy anything bigger (500 MB)


def _ascii(text: str) -> str:
    """Force a path/string to safe, single-line, bounded ASCII."""
    text = text.replace("\r", " ").replace("\n", " ")
    return text.encode("ascii", "replace").decode("ascii")


def _first_str(*values) -> str:
    """First value that is a non-empty string once stripped, else ''.
    Lets the model use alternate argument names without dead-ending the call."""
    for v in values:
        if isinstance(v, str) and v.strip():
            return v
        if v is not None and not isinstance(v, str):
            s = str(v).strip()
            if s:
                return s
    return ""


def _safe_name(name: str) -> str:
    """A bare new file name with any path parts stripped out."""
    n = _coerce(name, MAX_NAME_LEN).replace("/", "").replace("\\", "").strip()
    if n in ("", ".", ".."):
        return ""
    return n


def _resolve_under_home(raw: str):
    """Resolve a file/destination path and confirm it stays inside the user's
    home. Returns (Path, "") on success or (None, error_message)."""
    s = _coerce(raw, MAX_PATH_LEN)
    if not s:
        return None, ""  # caller supplies the specific message
    p = Path(s.replace("~", str(HOME)))
    if not p.is_absolute():
        p = Path(HOME) / p  # "Documents/x.txt" -> home\Documents\x.txt
    try:
        rp = p.resolve()
        home = Path(HOME).resolve()
    except OSError as e:
        return None, f"Error: that path isn't usable, sir ({_ascii(str(e))})."
    try:
        if rp != home and home not in rp.parents:
            return None, ("Error: I only work inside your own folders, sir "
                          f"(under {home}).")
    except Exception:
        return None, "Error: that path isn't valid, sir."
    return rp, ""


def _resolve_pair(src_raw: str, dst_raw: str):
    """Work out the concrete (source, target) file paths for a move/copy, or an
    error. Both ends are kept inside the user's home; the destination may be a
    folder to drop the file into or a new name. Never raises."""
    if not src_raw:
        return None, None, "Error: tell me which file to move, sir."
    if not dst_raw:
        return None, None, ("Error: tell me where to put it, sir -- a folder "
                            "or a new name.")

    src, err = _resolve_under_home(src_raw)
    if src is None:
        return None, None, err or "Error: that file path isn't valid, sir."
    if not src.exists():
        return None, None, f"Error: I can't find '{_ascii(str(src))}', sir."
    if src.is_dir():
        return None, None, (f"Error: '{_ascii(src.name)}' is a folder, sir; I "
                            "only move or copy files.")

    dst, err = _resolve_under_home(dst_raw)
    if dst is None:
        return None, None, err or "Error: that destination isn't valid, sir."

    has_sep = ("/" in dst_raw) or ("\\" in dst_raw)
    if dst.exists() and dst.is_dir():
        target = dst / src.name              # drop the file into the folder
    elif not has_sep and not Path(dst_raw).is_absolute():
        name = _safe_name(dst_raw)           # a bare new name -> rename in place
        if not name:
            return None, None, "Error: that new name isn't valid, sir."
        target = src.parent / name
    else:
        target = dst                         # a full new path

    # the final target must ALSO stay inside home (a bare name / new path could
    # otherwise point elsewhere) -- re-check it.
    tgt, err = _resolve_under_home(str(target))
    if tgt is None:
        return None, None, err or "Error: that destination isn't valid, sir."
    return src, tgt, ""


@tool(
    "move_file",
    "Move a file into another folder, or rename it. Use this after locating a "
    "file (e.g. with find_files) when the user asks to move, rename, or tidy it "
    "up ('move the budget into Documents', 'rename my resume to CV.pdf'). Give "
    "source (the file to move) and dest: dest can be a folder to move it into, "
    "or a new name/path to rename it to. Only the user's own folders are "
    "allowed, and an existing file is never overwritten.",
    {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "The file to move, e.g. 'Desktop/budget.xlsx'.",
            },
            "dest": {
                "type": "string",
                "description": "A folder to move it into (e.g. 'Documents') or a "
                "new name/path to rename it to (e.g. 'CV.pdf').",
            },
        },
        "required": ["source", "dest"],
    },
)
def move_file(source: str = "", dest: str = "", **extra) -> str:
    src_raw = _first_str(source, extra.get("from"), extra.get("src"),
                         extra.get("path"), extra.get("file"),
                         extra.get("source_path"))
    dst_raw = _first_str(dest, extra.get("destination"), extra.get("to"),
                         extra.get("target"), extra.get("new_path"),
                         extra.get("new_name"), extra.get("dest_path"),
                         extra.get("folder"))

    src, target, err = _resolve_pair(src_raw, dst_raw)
    if err:
        return err
    if src == target:
        return f"'{_ascii(src.name)}' is already there, sir."
    if target.exists():
        return (f"Error: '{_ascii(str(target))}' already exists, sir; I won't "
                "overwrite it. Pick another name.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
    except Exception as e:
        return f"Error: couldn't move it, sir ({_ascii(str(e))})."

    verb = "Renamed" if src.parent == target.parent else "Moved"
    return f"{verb} {_ascii(src.name)} to {_ascii(str(target))}, sir."


@tool(
    "copy_file",
    "Make a copy of a file; the original stays where it is. Use this when the "
    "user asks to duplicate or back up a file ('make a copy of my notes', 'copy "
    "the report into Backups'). Give source (the file to copy) and dest: dest "
    "can be a folder to copy it into, or a new name/path for the copy. Only the "
    "user's own folders are allowed, and an existing file is never overwritten.",
    {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "The file to copy, e.g. 'Desktop/notes.txt'.",
            },
            "dest": {
                "type": "string",
                "description": "A folder to copy it into (e.g. 'Backups') or a "
                "new name/path for the copy (e.g. 'notes_backup.txt').",
            },
        },
        "required": ["source", "dest"],
    },
)
def copy_file(source: str = "", dest: str = "", **extra) -> str:
    src_raw = _first_str(source, extra.get("from"), extra.get("src"),
                         extra.get("path"), extra.get("file"),
                         extra.get("source_path"))
    dst_raw = _first_str(dest, extra.get("destination"), extra.get("to"),
                         extra.get("target"), extra.get("new_path"),
                         extra.get("new_name"), extra.get("dest_path"),
                         extra.get("folder"))

    src, target, err = _resolve_pair(src_raw, dst_raw)
    if err:
        return err
    if src == target:
        return ("Error: give the copy a different name or folder, sir, so it "
                "doesn't clash with the original.")
    if target.exists():
        return (f"Error: '{_ascii(str(target))}' already exists, sir; I won't "
                "overwrite it. Pick another name.")
    try:
        size = src.stat().st_size
    except OSError:
        size = 0
    if size > MAX_COPY_BYTES:
        return (f"Error: that file is {_mb(size)}, too large for me to copy "
                f"safely, sir (limit {_mb(MAX_COPY_BYTES)}).")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(target))
    except Exception as e:
        return f"Error: couldn't copy it, sir ({_ascii(str(e))})."

    return f"Copied {_ascii(src.name)} to {_ascii(str(target))}, sir."


def _mb(n: int) -> str:
    """Human, pure-ASCII size phrase."""
    mb = n / (1024.0 * 1024.0)
    if mb >= 1.0:
        return f"{mb:.1f} MB"
    return f"{n / 1024.0:.1f} KB"
