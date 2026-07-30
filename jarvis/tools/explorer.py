"""Open / reveal a folder in Windows Explorer for Jarvis -- the "show me that"
member of the file family.

The file family can already LOCATE a file (``find_files`` / ``search_files`` /
``recent_files``), REARRANGE it (``move_file`` / ``copy_file`` / ``make_folder``),
back it up and restore it (``zip_files`` / ``unzip_files``), remove it
(``recycle_file``) and report what is eating the disk (``folder_size``). But once
Jarvis pointed at a heavy folder, or found the file the user wanted, the user
still had to go and open it by hand. ``open_folder`` closes that: it pops the
folder open in Windows Explorer -- and, pointed at a file, opens that file's
folder with the file already highlighted -- so "open my Downloads folder",
"show me that folder in Explorer", "reveal that file" all just work. It is the
natural follow-on to ``folder_size`` (flag the heavy folder, then jump to it).

Safety model (the strict handling the project asks for, because an 8B local
model WILL eventually pass junk, the wrong type, or try to open a system path):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless
  it lives inside the user's home directory (shared with ``find_files`` /
  ``organize``), so the model can never fling open ``C:\\Windows`` or all of
  ``C:\\``. A ``..``-escape is resolved and re-checked, so it can't slip out.
- **Read-only.** Opening a window never moves, writes or deletes anything.
- **The actual launch is isolated** in ``_reveal`` (a fixed-argv, ``shell=False``
  call -- a hallucinated path can never turn into a shell command), so the smoke
  test can swap in a hermetic fake and never actually pop a window open.
- **Pure ASCII out + never raises.** Wrong-type args are coerced, a missing
  target is a friendly message, and any unexpected error comes back as a string
  the model can read and recover from.
"""

import os
from pathlib import Path

from ..config import HOME
from .find import _coerce
from .organize import MAX_PATH_LEN, _ascii, _first_str, _resolve_under_home
from .registry import tool


def _resolve(raw: str):
    """Resolve a file-or-folder path, kept inside the user's home. Returns
    (Path, "") on success or (None, error_message). An empty path means the
    whole home folder. Never raises."""
    s = _coerce(raw, MAX_PATH_LEN)
    if not s:
        try:
            return Path(HOME).resolve(), ""
        except OSError as e:
            return None, f"Error: can't open your home folder, sir ({_ascii(str(e))})."
    p, err = _resolve_under_home(s)
    if p is None:
        return None, err or "Error: that path isn't valid, sir."
    if not p.exists():
        return None, f"Error: I can't find '{_ascii(str(p))}', sir."
    return p, ""


def _reveal(path: Path, is_file: bool) -> None:
    """Actually open the folder (or reveal the file) in Windows Explorer.

    Kept as a module-level function with a fixed, ``shell=False`` argv so the
    smoke test can swap in a hermetic fake instead of popping a real window open,
    and so a hallucinated path can never be interpreted as a shell command.
    Raises on failure so the caller can report it."""
    if is_file:
        # open the file's containing folder with the file highlighted. Explorer
        # returns a non-zero exit code even on success, so we deliberately do
        # NOT check it -- launching without an exception is enough.
        import subprocess
        subprocess.run(["explorer", f"/select,{path}"], shell=False,
                       check=False, timeout=15)
    else:
        os.startfile(str(path))  # opens the folder in a new Explorer window


@tool(
    "open_folder",
    "Open a folder in Windows Explorer so the user can see it, or reveal a file "
    "(open its folder with the file highlighted). Use this when the user asks to "
    "open, show, reveal, or 'take me to' a folder or file ('open my Downloads "
    "folder', 'show me that folder in Explorer', 'reveal that file'), and as the "
    "follow-up after folder_size flags a heavy folder. Give an optional folder "
    "like 'Downloads' or a file path like 'Desktop/report.pdf'; with nothing it "
    "opens the home folder. Read-only -- it never changes anything, and only the "
    "user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "folder": {
                "type": "string",
                "description": "The folder to open, e.g. 'Downloads' or "
                "'Documents/Taxes', or a file to reveal, e.g. "
                "'Desktop/report.pdf'. Defaults to the home folder.",
            },
        },
        "required": [],
    },
)
def open_folder(folder: str = "", **extra) -> str:
    raw = _first_str(folder, extra.get("path"), extra.get("directory"),
                     extra.get("dir"), extra.get("name"), extra.get("file"),
                     extra.get("target"), extra.get("location"),
                     extra.get("dest"))

    target, err = _resolve(raw)
    if target is None:
        return err

    is_file = target.is_file()
    if not is_file and not target.is_dir():
        # a symlink to nowhere, a device, etc. -- don't guess
        return f"Error: '{_ascii(str(target))}' isn't a normal folder, sir."

    try:
        _reveal(target, is_file)
    except Exception as e:
        return f"Error: couldn't open that in Explorer, sir ({_ascii(str(e))})."

    if is_file:
        return (f"Opened the folder holding {_ascii(target.name)} and "
                "highlighted it for you, sir.")
    where = ("your home folder" if str(target) == str(Path(HOME).resolve())
             else f"'{_ascii(target.name)}'")
    return f"Opened {where} in Explorer, sir."
