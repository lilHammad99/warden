"""Find duplicate files for Jarvis -- "what am I storing twice?".

The file family can already LOCATE a file (``find_files`` / ``search_files`` /
``recent_files``), REARRANGE it (``move_file`` / ``copy_file`` / ...), back it up
and restore it (``zip_files`` / ``unzip_files``), remove it (``recycle_file``)
and report how much room a folder uses (``folder_size``). The one tidy-up
question still missing was "am I keeping the same file twice?" -- a real problem
for a cluttered Downloads or a phone-photo dump, and one an 8B model cannot
answer by eyeballing names (two identical photos often have different names).
``find_duplicates`` answers it by CONTENT: it finds files whose bytes are
byte-for-byte identical, groups them, and reports how much space the user could
recover by deleting the extra copies ("find duplicate files", "am I storing
anything twice", "what duplicates are in my Downloads"). It is read-only -- it
never moves, renames or deletes anything; the user can then delete a copy with
``recycle_file``.

How it stays fast AND correct: two files can only be identical if they are the
same size, so files are grouped by size first and only the groups with more than
one file of that size are actually hashed. Hashing is a streamed content hash
(``hashlib.blake2b`` over the whole file), so a match means the bytes really are
identical, not just the size.

Safety model (the strict handling the project asks for, because an 8B local
model WILL eventually pass junk, the wrong type, or try to scan the whole disk):

- **Rooted in the user's home only.** The folder is resolved and REJECTED unless
  it lives inside the user's home directory (shared with ``find_files`` /
  ``organize``), so the model can never scan ``C:\\Windows`` or all of ``C:\\``.
- **System / heavy folders are pruned** (AppData, node_modules, .git, ...), so a
  scan stays relevant and fast.
- **Bounded everywhere.** Max walk depth, max entries visited, max files hashed,
  a per-file size cap, a total-bytes-hashed cap and a hard wall-clock budget -- a
  pathological "de-dupe everything" stops early with a clear note instead of
  hanging the agent or reading the disk to death. Empty (0-byte) files are
  ignored so they can't all pile up as bogus "duplicates".
- **Pure ASCII out.** Paths are sanitised so an odd filename can never corrupt
  the console or the model's context.
- **Read-only + never raises.** Nothing here writes, moves or deletes anything;
  wrong-type args are coerced, un-readable / permission-blocked / vanished files
  are skipped, and any unexpected error comes back as a friendly string.
"""

import hashlib
import os
import time
from pathlib import Path

from ..config import HOME
from .find import _SKIP_DIRS, _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_SCAN = 200000                    # most filesystem entries visited
MAX_DEPTH = 16                       # how deep below the start folder we recurse
TIME_BUDGET = 15.0                   # hard wall-clock cap (seconds)
MAX_FILES_HASHED = 20000             # most files we will actually hash
MAX_FILE_BYTES = 400 * 1024 * 1024   # never hash a single file bigger than this
MAX_HASH_TOTAL = 4 * 1024 ** 3       # total bytes hashed before we stop (4 GB)
MAX_GROUPS = 20                      # most duplicate sets listed
MAX_PER_GROUP = 10                   # most paths listed within one set
MAX_PATH_LEN = 400                   # a path, not an essay
_CHUNK = 1024 * 1024                 # 1 MB read chunk while hashing


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
    """Resolve the folder to scan, kept inside the user's home. Returns
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
        return None, err or "Error: that folder path isn't valid, sir."
    if not p.exists():
        return None, f"Error: I can't find '{_ascii(str(p))}', sir."
    if not p.is_dir():
        return None, (f"Error: '{_ascii(p.name)}' is a file, sir; give me a "
                      "folder to check for duplicates.")
    return p, ""


def _rel(path: Path, home: Path) -> str:
    """A short, ASCII, home-relative label for a file path."""
    try:
        return _ascii(str(path.relative_to(home)).replace("\\", "/"))
    except ValueError:
        return _ascii(path.name)


def _hash_file(path: Path) -> str | None:
    """Streamed content hash of a whole file, or None if it can't be read."""
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


@tool(
    "find_duplicates",
    "Find duplicate files -- files whose contents are byte-for-byte identical "
    "(even if their names differ) -- and report how much space the extra copies "
    "waste. Use this when the user wants to tidy up or free space ('find "
    "duplicate files', 'am I storing anything twice', 'what duplicates are in my "
    "Downloads', 'clean up duplicate photos'). This is read-only -- it never "
    "moves or deletes anything; tell the user which copies exist and let them "
    "delete one with recycle_file. Give an optional folder like 'Downloads' or "
    "'Pictures'; with no folder it checks the whole home folder. Only the user's "
    "own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "folder": {
                "type": "string",
                "description": "The folder to check for duplicates, e.g. "
                "'Downloads', 'Pictures'. Defaults to the whole home folder.",
            },
        },
        "required": [],
    },
)
def find_duplicates(folder: str = "", **extra) -> str:
    raw = _first_str(folder, extra.get("path"), extra.get("directory"),
                     extra.get("dir"), extra.get("name"), extra.get("dest"),
                     extra.get("target"))

    root, err = _resolve(raw)
    if root is None:
        return err
    try:
        home = Path(HOME).resolve()
    except OSError:
        home = Path(HOME)

    # Pass 1: collect (size -> [paths]), pruning + bounded. Only same-size files
    # can possibly be identical, so this groups the candidates cheaply.
    by_size: dict[int, list[Path]] = {}
    scanned = 0
    skipped_large = 0
    started = time.monotonic()
    hit_limit = False
    root_depth = len(root.parts)

    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
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
                p = here / fn
                try:
                    size = p.stat().st_size
                except OSError:
                    continue  # permission / vanished / broken link: skip
                if size <= 0:
                    continue  # ignore empty files -- not meaningful "duplicates"
                if size > MAX_FILE_BYTES:
                    skipped_large += 1
                    continue
                by_size.setdefault(size, []).append(p)

            if scanned >= MAX_SCAN:
                hit_limit = True
                break
            if time.monotonic() - started > TIME_BUDGET:
                hit_limit = True
                break
    except Exception as e:  # last-resort guard -- never crash the agent
        if not by_size:
            return f"Error while scanning for duplicates, sir: {_ascii(str(e))}"
        hit_limit = True

    # Pass 2: only sizes shared by 2+ files are worth hashing.
    groups: dict[tuple[int, str], list[Path]] = {}
    hashed = 0
    hashed_bytes = 0
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        for p in paths:
            if hashed >= MAX_FILES_HASHED or hashed_bytes >= MAX_HASH_TOTAL:
                hit_limit = True
                break
            if time.monotonic() - started > TIME_BUDGET:
                hit_limit = True
                break
            digest = _hash_file(p)
            if digest is None:
                continue  # unreadable now: skip, never crash
            hashed += 1
            hashed_bytes += size
            groups.setdefault((size, digest), []).append(p)
        if hit_limit:
            break

    # keep only real duplicate sets (2+ identical files)
    dupes = [(size, members) for (size, _dig), members in groups.items()
             if len(members) >= 2]

    where = ("your home folder" if str(root) == str(home)
             else f"'{_ascii(root.name)}'")

    if not dupes:
        note = ""
        if hit_limit:
            note = (" (I stopped early, so there may be more -- check a specific "
                    "subfolder to be sure)")
        return (f"No duplicate files found in {where}, sir. Nothing is stored "
                f"twice.{note}")

    # rank by the space that could be reclaimed (copies beyond the first)
    dupes.sort(key=lambda sm: (sm[0] * (len(sm[1]) - 1), sm[0]), reverse=True)
    reclaimable = sum(size * (len(members) - 1) for size, members in dupes)

    total_sets = len(dupes)
    shown = dupes[:MAX_GROUPS]
    head = (f"Found {total_sets} set{'s' if total_sets != 1 else ''} of "
            f"duplicate files in {where}, wasting {_human(reclaimable)} you "
            f"could recover, sir.")

    blocks = []
    for i, (size, members) in enumerate(shown, 1):
        members = sorted(members, key=lambda p: str(p).lower())
        copies = len(members)
        recover = _human(size * (copies - 1))
        listed = members[:MAX_PER_GROUP]
        lines = [f"- {_rel(m, home)}" for m in listed]
        if copies > MAX_PER_GROUP:
            lines.append(f"- (+{copies - MAX_PER_GROUP} more copies)")
        body = "\n".join(lines)
        blocks.append(f"Set {i}: {copies} copies of {_human(size)} each "
                      f"({recover} reclaimable):\n{body}")

    note = ""
    if total_sets > MAX_GROUPS:
        note = f"\n(showing the {MAX_GROUPS} biggest of {total_sets} sets)"
    if hit_limit:
        note += ("\n(I stopped early, so there may be more -- check a specific "
                 "subfolder for the full picture)")
    if skipped_large:
        note += (f"\n(skipped {skipped_large} very large file"
                 f"{'s' if skipped_large != 1 else ''} to stay fast)")

    tip = ("\nTo free the space, delete the extra copies with recycle_file "
           "(they go to the Recycle Bin, so it's undoable).")
    return head + "\n" + "\n\n".join(blocks) + note + tip
