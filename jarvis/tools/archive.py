"""Back up files into a .zip archive for Jarvis -- the backup half of the file
tools.

The navigation family lets Jarvis LOCATE a file (``find_files`` by name,
``search_files`` by contents, ``recent_files`` by time) and the organise family
lets it MOVE or COPY one (``move_file`` / ``copy_file``). This adds the missing
autonomy win: bundling files up so the user can back them up or send them on --
"back up my Documents into a zip", "zip my resume and cv together",
"make an archive of this week's photos". One tool:

- ``zip_files`` -- compress one file, several files, or a whole folder into a
  single ``.zip`` (the originals stay exactly where they are).

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point Jarvis at the whole disk):

- **Rooted in the user's home only.** Every source AND the destination ``.zip``
  are resolved and REJECTED unless they live inside the user's home directory
  (same boundary as ``find_files``), so Jarvis can never read ``C:\\Windows`` or
  drop an archive outside the user's own folders.
- **Never overwrites.** If the destination ``.zip`` already exists it is REFUSED
  -- a hallucination can never clobber an existing archive.
- **Bounded everywhere.** Caps on the number of files, the total uncompressed
  bytes, the folder-walk depth, and a hard wall-clock time budget, plus the
  usual pruning of system/heavy dirs -- a runaway "zip everything" stops early
  with a clear note instead of hanging the agent or filling the disk.
- **Atomic.** The archive is written to a temp file in the destination folder
  and only ``os.replace``-d into place once it is complete, so a crash or an
  error can never leave a half-written ``.zip`` behind.
- **Never raises.** Wrong-type / empty / missing args are coerced or rejected,
  un-readable files are skipped, and any unexpected error comes back as a
  friendly, pure-ASCII string the model can read and recover from.
"""

import os
import re
import time
import zipfile
from pathlib import Path

from ..config import HOME
from .find import _SKIP_DIRS, _coerce
from .organize import _ascii, _resolve_under_home
from .registry import tool

MAX_FILES = 5000                          # most files bundled into one archive
MAX_TOTAL_BYTES = 500 * 1024 * 1024       # most uncompressed bytes (500 MB)
MAX_DEPTH = 12                            # how deep a folder source is walked
TIME_BUDGET = 20.0                        # hard wall-clock cap while collecting
MAX_PATH_LEN = 400                        # a path, not an essay


def _mb(n: int) -> str:
    """Human, pure-ASCII size phrase."""
    mb = n / (1024.0 * 1024.0)
    if mb >= 1.0:
        return f"{mb:.1f} MB"
    return f"{n / 1024.0:.1f} KB"


def _source_list(*values) -> list[str]:
    """Turn whatever the model handed us into a list of source path strings.

    Accepts a real list/tuple, a single string, or a string holding several
    paths separated by commas or newlines -- all common 8B shapes -- so the
    model doesn't dead-end just because it packed the sources differently."""
    for v in values:
        if isinstance(v, (list, tuple)):
            out = [str(x).strip() for x in v if str(x).strip()]
            if out:
                return out[:MAX_FILES]
        elif isinstance(v, str) and v.strip():
            parts = [p.strip() for p in re.split(r"[,\n]", v) if p.strip()]
            if parts:
                return parts[:MAX_FILES]
        elif v is not None and not isinstance(v, (str, list, tuple)):
            s = str(v).strip()
            if s:
                return [s]
    return []


def _walk_folder(root: Path, home: Path, files, seen, started):
    """Add every readable file under ``root`` to ``files``. Bounded on depth,
    file count, total bytes, and wall-clock time. Returns a short note string if
    a limit was hit (else "")."""
    root_depth = len(root.parts)
    total = sum(sz for _, sz in files)
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            depth = len(Path(dirpath).parts) - root_depth
            if depth >= MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames
                               if d.lower() not in _SKIP_DIRS
                               and not d.startswith("$")]
            for fn in filenames:
                fpath = Path(dirpath) / fn
                try:
                    rp = fpath.resolve()
                except OSError:
                    continue
                if str(rp) in seen:
                    continue
                try:
                    size = fpath.stat().st_size
                except OSError:
                    continue  # vanished / permission: skip, never crash
                if len(files) >= MAX_FILES:
                    return "\n(stopped early: too many files; zip a smaller folder)"
                if total + size > MAX_TOTAL_BYTES:
                    return (f"\n(stopped early at {_mb(total)}: that folder is "
                            "too big to zip safely)")
                seen.add(str(rp))
                files.append((fpath, size))
                total += size
            if time.monotonic() - started > TIME_BUDGET:
                return "\n(stopped early: that took too long; zip a smaller folder)"
    except Exception:
        pass  # last-resort guard: keep whatever we gathered, never crash
    return ""


def _dest_zip(raw: str):
    """Resolve the destination .zip path under home. Returns (Path, "") or
    (None, error). Ensures a .zip suffix and stays inside the user's folders."""
    s = _coerce(raw, MAX_PATH_LEN)
    if not s:
        return None, ("Error: tell me what to call the backup, sir -- a name "
                      "like 'backup.zip'.")
    if not s.lower().endswith(".zip"):
        s += ".zip"
    dst, err = _resolve_under_home(s)
    if dst is None:
        return None, err or "Error: that destination isn't valid, sir."
    if dst.is_dir():
        return None, ("Error: the backup needs a file name, sir, not a folder "
                      "(e.g. 'backup.zip').")
    return dst, ""


@tool(
    "zip_files",
    "Bundle one or more files, or a whole folder, into a single .zip archive so "
    "the user can back them up or send them on. The originals are left exactly "
    "where they are. Use this when the user asks to back up, archive, compress, "
    "or zip something ('back up my Documents', 'zip my resume and cv', 'make an "
    "archive of the report'). Give sources (a file, a folder, or several files) "
    "and dest (a name for the .zip). Only the user's own folders are allowed, "
    "and an existing archive is never overwritten. Locate files first with "
    "find_files / search_files / recent_files if you don't know their paths.",
    {
        "type": "object",
        "properties": {
            "sources": {
                "type": "string",
                "description": "What to back up: a single file, a folder to zip "
                "whole (e.g. 'Documents'), or several files separated by commas "
                "(e.g. 'Desktop/cv.pdf, Desktop/resume.pdf').",
            },
            "dest": {
                "type": "string",
                "description": "A name for the .zip archive, e.g. "
                "'backup.zip' or 'Desktop/work_backup.zip'.",
            },
        },
        "required": ["sources", "dest"],
    },
)
def zip_files(sources="", dest: str = "", **extra) -> str:
    src_list = _source_list(sources, extra.get("source"), extra.get("files"),
                            extra.get("paths"), extra.get("from"),
                            extra.get("file"), extra.get("path"),
                            extra.get("folder"))
    dst_raw = ""
    for cand in (dest, extra.get("destination"), extra.get("to"),
                 extra.get("name"), extra.get("zip"), extra.get("output"),
                 extra.get("archive")):
        if isinstance(cand, str) and cand.strip():
            dst_raw = cand
            break
        if cand is not None and not isinstance(cand, str):
            s = str(cand).strip()
            if s:
                dst_raw = s
                break

    if not src_list:
        return "Error: tell me which file(s) or folder to back up, sir."

    dst, err = _dest_zip(dst_raw)
    if dst is None:
        return err
    if dst.exists():
        return (f"Error: '{_ascii(str(dst))}' already exists, sir; I won't "
                "overwrite it. Pick another name.")

    home = Path(HOME).resolve()
    files: list[tuple[Path, int]] = []   # (path, size)
    seen: set[str] = set()
    skipped: list[str] = []
    note = ""
    started = time.monotonic()

    for raw in src_list:
        if len(files) >= MAX_FILES:
            note = note or "\n(stopped early: too many files)"
            break
        src, serr = _resolve_under_home(raw)
        if src is None:
            skipped.append(_ascii(raw))
            continue
        if not src.exists():
            skipped.append(_ascii(str(src)))
            continue
        if src.is_dir():
            note = _walk_folder(src, home, files, seen, started) or note
            continue
        # a single file
        try:
            rp = src.resolve()
        except OSError:
            skipped.append(_ascii(str(src)))
            continue
        if str(rp) in seen:
            continue
        try:
            size = src.stat().st_size
        except OSError:
            skipped.append(_ascii(str(src)))
            continue
        total = sum(sz for _, sz in files)
        if total + size > MAX_TOTAL_BYTES:
            note = note or (f"\n(stopped early at {_mb(total)}: too big to zip "
                            "safely)")
            break
        seen.add(str(rp))
        files.append((src, size))

    if not files:
        extra_note = ""
        if skipped:
            extra_note = " (couldn't find: " + ", ".join(skipped[:5]) + ")"
        return f"Error: nothing to back up, sir{extra_note}."

    # write to a temp file in the destination folder, then atomically swap in,
    # so a failure never leaves a half-written .zip behind.
    tmp = dst.with_name(dst.name + ".part")
    written = 0
    total_bytes = 0
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath, size in files:
                try:
                    arc = fpath.resolve().relative_to(home)
                    arcname = _ascii(str(arc))
                except Exception:
                    arcname = _ascii(fpath.name)
                try:
                    zf.write(fpath, arcname)
                except Exception:
                    skipped.append(_ascii(str(fpath)))
                    continue
                written += 1
                total_bytes += size
        if written == 0:
            tmp.unlink(missing_ok=True)
            return "Error: couldn't add any files to the backup, sir."
        os.replace(tmp, dst)
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"Error: couldn't create the backup, sir ({_ascii(str(e))})."

    head = (f"Backed up {written} file{'s' if written != 1 else ''} "
            f"({_mb(total_bytes)}) into {_ascii(str(dst))}, sir.")
    if skipped:
        head += f" Skipped {len(skipped)} I couldn't read."
    return head + note
