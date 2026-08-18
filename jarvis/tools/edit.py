"""Make a targeted edit to an existing text file for Jarvis -- change one part
of a file without rewriting the whole thing.

The file family can already CREATE or overwrite a file (``write_file``), add to
the end (``append_file``) and READ one (``read_file``), but the only way to
CHANGE something already inside a file was to overwrite the WHOLE file with
``write_file`` -- which forces the model to reproduce every other line exactly
or it silently loses the rest of the file. For an 8B local model editing code or
notes that is a real hazard: a one-line fix should not risk the other 200 lines.
``edit_file`` does what a code editor does -- find an exact piece of text and
replace it, leaving everything else untouched -- so Jarvis can iterate on a file
("change the port to 8080 in my config", "rename that function", "fix that
typo", "update the version number").

Safety model (the strict handling the project asks for, because an 8B local
model WILL eventually pass junk, the wrong type, or aim at the wrong text):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless
  it lives inside the user's home directory (shared with ``find_files`` /
  ``organize``), including a ``..``-escape, so the model can never edit a file
  under ``C:\\Windows`` or outside the user's own folders.
- **Existing text files only.** A missing file is refused and the model is
  steered to ``write_file`` (which creates one); a folder is refused; a binary
  file (by extension OR a NUL-byte sniff) is refused so an edit can never corrupt
  an image, archive or Office document.
- **Never a blind overwrite.** The ``old`` text must appear EXACTLY. If it is
  absent nothing is written and the model is told so; if it appears more than
  once the edit is REFUSED as ambiguous (unless ``replace_all`` is set), so a
  single hallucinated match can never rewrite the wrong line.
- **Newline-preserving.** Matching is done on newline-normalised text (the model
  reads a file with ``\\n`` via ``read_file``), but the file's original line
  endings are restored on write, so an edit doesn't silently reflow a whole file.
- **Atomic + bounded.** The result is written to a ``.part`` temp then
  ``os.replace``-d in, so a failure never leaves a half-written file; the file
  size and the ``old``/``new`` strings are length-capped.
- **Never raises.** Wrong-type / empty / missing args are coerced or rejected,
  and any unexpected error comes back as a friendly, pure-ASCII string.
"""

import os
from pathlib import Path

from .fileinfo import _is_binary
from .organize import _ascii, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400                     # a path, not an essay
MAX_FILE_BYTES = 5 * 1024 * 1024       # refuse to edit a file bigger than this (5 MB)
MAX_STR_LEN = 100000                   # cap on the old/new strings (100k chars each)

# alternate argument names an 8B model reaches for, mapped to old / new
_OLD_KEYS = ("old_string", "old_text", "old_str", "find", "search",
             "target", "from", "original", "search_string")
_NEW_KEYS = ("new_string", "new_text", "new_str", "replace", "replacement",
             "to", "with", "replace_with")
_PATH_KEYS = ("file", "filename", "filepath", "file_path", "source", "document")


def _as_str(value, allow_empty: bool):
    """Coerce a model-supplied value to a string WITHOUT stripping whitespace or
    newlines (they matter for an exact match). Returns (text, error) -- text is
    None on error. Over-long input is refused, not truncated, because a truncated
    match string would edit the wrong text."""
    if value is None:
        return ("" if allow_empty else None), ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\x00", "")
    if len(value) > MAX_STR_LEN:
        return None, (f"Error: that text is too long to match on, sir "
                      f"(over {MAX_STR_LEN:,} characters).")
    if not value and not allow_empty:
        return None, ""
    return value, ""


def _first_present(primary, extra: dict, keys, allow_empty: bool):
    """Pick the old/new value from the primary arg or an alternate name. For
    `old` (allow_empty=False) the first NON-EMPTY candidate wins; for `new`
    (allow_empty=True) an explicit value -- including "" -- from the primary arg
    is honoured, else the first non-empty alternate, else ""."""
    if isinstance(primary, str) and (primary or not allow_empty):
        if primary:
            return primary
        if allow_empty:
            return primary  # explicit empty new = delete the old text
    elif primary is not None and not isinstance(primary, str):
        return primary  # wrong type -> _as_str coerces it
    for k in keys:
        v = extra.get(k)
        if isinstance(v, str) and v:
            return v
        if v is not None and not isinstance(v, str):
            return v
    return "" if allow_empty else None


def _norm(text: str) -> str:
    """Normalise line endings to \\n for matching (read_file shows the model \\n)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


@tool(
    "edit_file",
    "Change part of an existing text file by replacing an exact piece of text, "
    "without rewriting the whole file. Give the file 'path', the exact existing "
    "text as 'old', and the replacement as 'new' (use an empty 'new' to delete "
    "the old text). The old text must appear exactly once, or set replace_all "
    "to change every occurrence. Best for editing code, config or notes you have "
    "already read. To CREATE a new file use write_file; to add to the end use "
    "append_file.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "File to edit, e.g. Desktop/app.py"},
            "old": {"type": "string",
                    "description": "The exact existing text to replace"},
            "new": {"type": "string",
                    "description": "The replacement text (empty to delete 'old')"},
            "replace_all": {"type": "boolean",
                            "description": "Replace every occurrence, not just one"},
        },
        "required": ["path", "old"],
    },
)
def edit_file(path: str = "", old=None, new="", replace_all=False, **extra) -> str:
    # --- resolve + validate the file path (kept inside the user's home) ---
    raw_path = path
    if not (isinstance(raw_path, str) and raw_path.strip()):
        for k in _PATH_KEYS:
            v = extra.pop(k, None)
            if isinstance(v, str) and v.strip():
                raw_path = v
                break
            if v is not None and not isinstance(v, str) and str(v).strip():
                raw_path = str(v)
                break
    if not (isinstance(raw_path, str) and str(raw_path).strip()):
        return "Error: tell me which file to edit, sir."

    p, err = _resolve_under_home(str(raw_path)[:MAX_PATH_LEN])
    if p is None:
        return err or "Error: that file path isn't valid, sir."
    if p.is_dir():
        return (f"Error: '{_ascii(str(p))}' is a folder, sir -- give me a file "
                "to edit.")
    if not p.exists():
        return (f"Error: I can't find '{_ascii(str(p))}', sir. To create a new "
                "file use write_file.")
    if _is_binary(p, p.suffix.lower()):
        return (f"Error: '{_ascii(str(p))}' looks like a binary file, sir -- I "
                "only edit text files.")
    try:
        size = p.stat().st_size
    except OSError as e:
        return f"Error: I couldn't read that file, sir ({_ascii(str(e))})."
    if size > MAX_FILE_BYTES:
        return (f"Error: '{_ascii(p.name)}' is too big to edit safely, sir "
                f"(over {MAX_FILE_BYTES // (1024 * 1024)} MB).")

    # --- resolve the old / new text (with forgiving alternate arg names) ---
    old_raw = _first_present(old, extra, _OLD_KEYS, allow_empty=False)
    if old_raw is None:
        return ("Error: tell me the exact text to replace, sir (the 'old' "
                "argument). To add text to the end of a file use append_file.")
    old_text, oerr = _as_str(old_raw, allow_empty=False)
    if old_text is None:
        return oerr or ("Error: tell me the exact text to replace, sir.")

    new_raw = _first_present(new, extra, _NEW_KEYS, allow_empty=True)
    new_text, nerr = _as_str(new_raw, allow_empty=True)
    if new_text is None:
        return nerr or "Error: that replacement text isn't usable, sir."

    if old_text == new_text:
        return ("The old and new text are the same, sir, so there's nothing to "
                "change.")

    # --- read the file, match on newline-normalised text ---
    try:
        original = p.read_bytes().decode("utf-8", errors="replace")
    except OSError as e:
        return f"Error: I couldn't read that file, sir ({_ascii(str(e))})."

    uses_crlf = "\r\n" in original
    body = _norm(original)
    needle = _norm(old_text)
    count = body.count(needle)

    if count == 0:
        return ("I couldn't find that exact text in " + _ascii(p.name) + ", sir. "
                "Read the file first so the 'old' text matches exactly "
                "(including spacing).")

    want_all = _as_bool(replace_all) or any(
        _as_bool(extra.get(k)) for k in ("all", "every", "global"))
    if count > 1 and not want_all:
        return (f"That text appears {count} times in {_ascii(p.name)}, sir. Make "
                "'old' more specific so it matches just the part you mean, or set "
                "replace_all to change all of them.")

    updated = body.replace(needle, _norm(new_text), -1 if want_all else 1)
    if uses_crlf:
        updated = updated.replace("\n", "\r\n")

    # --- write it back atomically so a failure never truncates the file ---
    tmp = p.with_name(p.name + ".part")
    try:
        tmp.write_bytes(updated.encode("utf-8"))
        os.replace(tmp, p)
    except OSError as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return f"Error: I couldn't save the edit, sir ({_ascii(str(e))})."

    n = count if want_all else 1
    where = f"{n} occurrences" if n != 1 else "1 occurrence"
    return (f"Edited {_ascii(str(p))}: replaced {where}. The file is now "
            f"{len(updated):,} characters.")


def _as_bool(value) -> bool:
    """Read a boolean from the model's messy input (True / 'yes' / 'all' / 1)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {
            "1", "true", "yes", "y", "on", "all", "every", "everything"}
    return False
