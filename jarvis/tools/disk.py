"""Folder / disk usage for Jarvis -- "what's taking up space?".

The file family can already LOCATE a file (``find_files`` / ``search_files`` /
``recent_files``), REARRANGE it (``move_file`` / ``copy_file`` / ``make_folder``),
back it up and restore it (``zip_files`` / ``unzip_files``) and remove it
(``recycle_file``). The one everyday question still missing was "how much room is
this using?" -- so Jarvis could tidy files but had no idea which folder was
eating the disk. ``folder_size`` closes that: it reports the total size of a
folder (or a single file), how many files it holds, and the biggest things
inside it, so the user can act ("how big is my Downloads folder", "what's taking
up space in Documents", "how much space is my Desktop using") -- a real autonomy
win, and read-only, so it can never change anything.

Safety model (the strict handling the project asks for, because an 8B local
model WILL eventually pass junk, the wrong type, or try to size the whole disk):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless
  it lives inside the user's home directory (shared with ``find_files`` /
  ``organize``), so the model can never measure ``C:\\Windows`` or all of
  ``C:\\``.
- **System / heavy folders are pruned** (AppData, node_modules, .git, ...), so a
  scan stays relevant and fast.
- **Bounded everywhere.** Max walk depth, max entries visited and a hard
  wall-clock time budget -- a pathological "size everything" stops early with a
  clear note instead of hanging the agent.
- **Pure ASCII out.** Names are sanitised so an odd filename can never corrupt
  the console or the model's context.
- **Read-only + never raises.** Nothing here writes, moves or deletes anything;
  wrong-type args are coerced, un-stat-able / permission-blocked files are
  skipped, and any unexpected error comes back as a friendly string the model
  can read and recover from.
"""

import os
import time
from pathlib import Path

from ..config import HOME
from .find import _SKIP_DIRS, _coerce
from .organize import _first_str, _resolve_under_home
from .registry import tool

MAX_SCAN = 300000       # most filesystem entries visited before giving up
MAX_DEPTH = 16          # how deep below the start folder we recurse
TIME_BUDGET = 12.0      # hard wall-clock cap (seconds)
MAX_ITEMS = 10          # how many "biggest items" to list
MAX_PATH_LEN = 400      # a path, not an essay


def _ascii(text: str) -> str:
    """Force a path/name to safe, single-line, bounded ASCII."""
    text = text.replace("\r", " ").replace("\n", " ")
    return text.encode("ascii", "replace").decode("ascii")


def _human(n: float) -> str:
    """Bytes -> a short, human, pure-ASCII size phrase (B, KB, MB, GB, TB)."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    if n < 0:
        n = 0.0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0:
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _resolve(raw: str):
    """Resolve a file-or-folder path, kept inside the user's home. Returns
    (Path, "") on success or (None, error_message). An empty path means the
    whole home folder. Never raises."""
    s = _coerce(raw, MAX_PATH_LEN)
    if not s:
        try:
            return Path(HOME).resolve(), ""
        except OSError as e:
            return None, f"Error: can't read your home folder, sir ({_ascii(str(e))})."
    p, err = _resolve_under_home(s)
    if p is None:
        return None, err or "Error: that path isn't valid, sir."
    if not p.exists():
        return None, f"Error: I can't find '{_ascii(str(p))}', sir."
    return p, ""


@tool(
    "folder_size",
    "Report how much disk space a folder (or a single file) is using: its total "
    "size, how many files it contains, and the biggest items inside it. Use this "
    "when the user asks about disk space or what is taking up room ('how big is "
    "my Downloads folder', 'what's taking up space in Documents', 'how much space "
    "is my Desktop using'). This is read-only -- it never changes anything. Give "
    "an optional folder like 'Downloads' or 'Documents'; with no folder it "
    "measures the whole home folder. Only the user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "folder": {
                "type": "string",
                "description": "The folder (or file) to measure, e.g. "
                "'Downloads', 'Documents', 'Desktop/big.zip'. Defaults to the "
                "whole home folder.",
            },
        },
        "required": [],
    },
)
def folder_size(folder: str = "", **extra) -> str:
    raw = _first_str(folder, extra.get("path"), extra.get("directory"),
                     extra.get("dir"), extra.get("name"), extra.get("dest"),
                     extra.get("target"), extra.get("file"))

    target, err = _resolve(raw)
    if target is None:
        return err

    # a single file: just report its size, no walk needed
    if target.is_file():
        try:
            size = target.stat().st_size
        except OSError as e:
            return f"Error: couldn't read that file's size, sir ({_ascii(str(e))})."
        return f"{_ascii(target.name)} is {_human(size)}, sir."

    if not target.is_dir():
        # a symlink to nowhere, a device, etc. -- don't guess
        return f"Error: '{_ascii(str(target))}' isn't a normal folder, sir."

    total = 0
    files = 0
    children: dict[str, list] = {}   # first-level name -> [bytes, is_dir]
    scanned = 0
    started = time.monotonic()
    hit_limit = False
    root_depth = len(target.parts)

    try:
        for dirpath, dirnames, filenames in os.walk(target, topdown=True):
            depth = len(Path(dirpath).parts) - root_depth
            if depth >= MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames
                               if d.lower() not in _SKIP_DIRS
                               and not d.startswith("$")]

            here = Path(dirpath)
            for fn in filenames:
                scanned += 1
                try:
                    size = (here / fn).stat().st_size
                except OSError:
                    continue  # permission / vanished / broken link: skip
                total += size
                files += 1
                # attribute the bytes to the top-level item under the target
                try:
                    rel = (here / fn).relative_to(target)
                except ValueError:
                    continue
                first = rel.parts[0]
                is_dir = len(rel.parts) > 1
                bucket = children.get(first)
                if bucket is None:
                    children[first] = [size, is_dir]
                else:
                    bucket[0] += size

            if scanned >= MAX_SCAN:
                hit_limit = True
                break
            if time.monotonic() - started > TIME_BUDGET:
                hit_limit = True
                break
    except Exception as e:  # last-resort guard -- never crash the agent
        if total == 0:
            return f"Error while measuring, sir: {_ascii(str(e))}"
        hit_limit = True

    where = ("your home folder" if str(target) == str(Path(HOME).resolve())
             else f"'{_ascii(target.name)}'")

    if files == 0:
        return f"{where.capitalize()} is empty (0 B), sir."

    head = (f"{where.capitalize()} is {_human(total)} across "
            f"{files} file{'s' if files != 1 else ''}, sir.")

    ranked = sorted(children.items(), key=lambda kv: kv[1][0], reverse=True)
    top = ranked[:MAX_ITEMS]
    lines = []
    for name, (size, is_dir) in top:
        label = _ascii(name) + ("/" if is_dir else "")
        lines.append(f"- {label}  ({_human(size)})")
    body = "\n".join(lines)

    note = ""
    if hit_limit:
        note = ("\n(stopped early; the real total is larger -- name a specific "
                "subfolder to measure it exactly)")
    elif len(ranked) > MAX_ITEMS:
        note = f"\n(showing the {MAX_ITEMS} biggest of {len(ranked)} items)"

    tail = f"\nBiggest inside:\n{body}" if body else ""
    return f"{head}{tail}{note}"
