"""Extract a .zip archive for Jarvis -- the restore/unpack counterpart to
``zip_files``.

``zip_files`` bundles files up into a ``.zip``; this is the missing other half:
opening one back up. Once Jarvis has located an archive (with ``find_files`` /
``recent_files``) the user can say "unzip my backup", "extract downloaded.zip
into Documents", "open that archive" and Jarvis unpacks it into the user's own
folders. One tool:

- ``unzip_files`` -- extract a ``.zip`` into a folder (a new folder named after
  the archive by default). The archive itself is left exactly where it is.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point Jarvis at a hostile archive):

- **Rooted in the user's home only.** Both the source ``.zip`` AND the
  destination folder are resolved and REJECTED unless they live inside the
  user's home directory (same boundary as ``find_files``), so Jarvis can never
  read an archive from ``C:\\Windows`` or write extracted files outside the
  user's own folders.
- **Zip-slip proof.** Every archive entry's target is rebuilt from sanitised
  path parts (``..``, drive letters and leading slashes stripped) and then
  re-checked to be INSIDE the destination folder, so a malicious/hallucinated
  entry like ``..\\..\\Windows\\evil.exe`` can never escape the extract folder.
- **Never overwrites.** An entry whose target file already exists is SKIPPED
  (and counted), never clobbered -- extraction can't destroy existing work.
- **Zip-bomb bounded.** Caps on the number of files, total uncompressed bytes,
  per-entry compression ratio, nested path depth, and a hard wall-clock budget;
  each file is streamed with a running byte cap so a lying size header can't
  blow up memory or fill the disk. A runaway archive stops early with a clear
  note.
- **Atomic per file.** Each entry is written to a ``.part`` temp file and only
  ``os.replace``-d into place once complete, so a crash never leaves a
  half-written file behind.
- **Never raises.** A corrupt archive, wrong-type / empty / missing args, and
  any unexpected error all come back as a friendly, pure-ASCII string the model
  can read and recover from.
"""

import os
import time
import zipfile
from pathlib import Path

from ..config import HOME
from .find import _coerce
from .organize import _ascii, _first_str, _mb, _resolve_under_home
from .registry import tool

MAX_FILES = 5000                          # most entries extracted from one zip
MAX_TOTAL_BYTES = 500 * 1024 * 1024       # most uncompressed bytes (500 MB)
MAX_RATIO = 200                           # zip-bomb: uncompressed/compressed cap
MAX_DEPTH = 16                            # deepest nested path allowed in an entry
TIME_BUDGET = 30.0                        # hard wall-clock cap while extracting
MAX_PATH_LEN = 400                        # a path, not an essay
_CHUNK = 64 * 1024


def _resolve_zip(raw: str):
    """Resolve the source .zip under home. Returns (Path, "") or (None, error)."""
    s = _coerce(raw, MAX_PATH_LEN)
    if not s:
        return None, "Error: tell me which .zip to open, sir."
    src, err = _resolve_under_home(s)
    if src is None:
        return None, err or "Error: that path isn't valid, sir."
    if not src.exists():
        return None, f"Error: I can't find '{_ascii(str(src))}', sir."
    if src.is_dir():
        return None, (f"Error: '{_ascii(src.name)}' is a folder, sir, not a "
                      ".zip archive.")
    return src, ""


def _resolve_dest(raw: str, src: Path):
    """Resolve the destination folder under home. Defaults to a folder named
    after the archive, beside it. Returns (Path, "") or (None, error)."""
    s = _coerce(raw, MAX_PATH_LEN)
    if not s:
        # default: <archive-name>/ next to the zip (its own folder is under home)
        return src.parent / (src.stem or "extracted"), ""
    dest, err = _resolve_under_home(s)
    if dest is None:
        return None, err or "Error: that destination isn't valid, sir."
    if dest.exists() and not dest.is_dir():
        return None, (f"Error: '{_ascii(dest.name)}' is a file, sir; give me a "
                      "folder to extract into.")
    return dest, ""


def _safe_target(dest: Path, member_name: str):
    """Rebuild an archive entry's on-disk target from sanitised parts and confirm
    it stays inside ``dest`` (zip-slip proof). Returns a Path, or None if the
    entry is empty, too deep, or tries to escape the destination."""
    name = str(member_name).replace("\\", "/")
    parts = []
    for part in name.split("/"):
        part = part.strip()
        if part == "..":
            return None                 # a traversal component -> reject (zip-slip)
        if part in ("", "."):
            continue                    # leading slash / '.' segment -> ignore
        part = part.replace(":", "_")   # neutralise a drive letter like 'C:'
        parts.append(part)
    if not parts or len(parts) > MAX_DEPTH:
        return None
    target = dest.joinpath(*parts)
    try:
        rt = target.resolve()
        rd = dest.resolve()
    except OSError:
        return None
    if rt != rd and rd not in rt.parents:
        return None  # escaped the destination folder -> refuse
    return target


@tool(
    "unzip_files",
    "Extract (unzip) a .zip archive into the user's folders -- the counterpart "
    "to zip_files. Use this when the user asks to unzip, extract, or open an "
    "archive ('unzip my backup', 'extract downloaded.zip into Documents', 'open "
    "that archive'). Give source (the .zip file) and optionally dest (a folder "
    "to extract into; by default a new folder named after the archive is created "
    "beside it). Only the user's own folders are allowed, existing files are "
    "never overwritten, and the archive itself is left in place. Locate the .zip "
    "first with find_files / recent_files if you don't know its path.",
    {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "The .zip archive to extract, e.g. "
                "'Downloads/backup.zip'.",
            },
            "dest": {
                "type": "string",
                "description": "Optional folder to extract into, e.g. "
                "'Documents'. Defaults to a new folder named after the archive.",
            },
        },
        "required": ["source"],
    },
)
def unzip_files(source: str = "", dest: str = "", **extra) -> str:
    src_raw = _first_str(source, extra.get("from"), extra.get("src"),
                         extra.get("path"), extra.get("file"),
                         extra.get("zip"), extra.get("archive"),
                         extra.get("sources"))
    dst_raw = _first_str(dest, extra.get("destination"), extra.get("to"),
                         extra.get("target"), extra.get("folder"),
                         extra.get("into"), extra.get("output"),
                         extra.get("dir"))

    src, err = _resolve_zip(src_raw)
    if src is None:
        return err
    dest_dir, err = _resolve_dest(dst_raw, src)
    if dest_dir is None:
        return err

    try:
        zf = zipfile.ZipFile(src)
    except zipfile.BadZipFile:
        return f"Error: '{_ascii(src.name)}' isn't a valid .zip archive, sir."
    except Exception as e:
        return f"Error: couldn't open that archive, sir ({_ascii(str(e))})."

    written = 0
    skipped_exist = 0
    skipped_unsafe = 0
    total = 0
    note = ""
    started = time.monotonic()

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        zf.close()
        return f"Error: couldn't create the extract folder, sir ({_ascii(str(e))})."

    try:
        with zf:
            for info in zf.infolist():
                if written >= MAX_FILES:
                    note = note or ("\n(stopped early: too many files in that "
                                    "archive)")
                    break
                if time.monotonic() - started > TIME_BUDGET:
                    note = note or "\n(stopped early: that took too long)"
                    break
                if info.is_dir():
                    continue

                target = _safe_target(dest_dir, info.filename)
                if target is None:
                    skipped_unsafe += 1
                    continue
                if target.exists():
                    skipped_exist += 1  # never overwrite
                    continue

                declared = int(getattr(info, "file_size", 0) or 0)
                if total + declared > MAX_TOTAL_BYTES:
                    note = note or (f"\n(stopped early at {_mb(total)}: that "
                                    "archive unpacks to more than I'll extract "
                                    "safely)")
                    break
                comp = int(getattr(info, "compress_size", 0) or 0) or 1
                if declared > 1024 * 1024 and declared / comp > MAX_RATIO:
                    skipped_unsafe += 1  # looks like a zip bomb
                    continue

                tmp = target.with_name(target.name + ".part")
                got = 0
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as srcf, open(tmp, "wb") as out:
                        while True:
                            chunk = srcf.read(_CHUNK)
                            if not chunk:
                                break
                            got += len(chunk)
                            # a lying header can't overrun the cap or the budget
                            if got > declared + _CHUNK or total + got > MAX_TOTAL_BYTES:
                                raise ValueError("size overrun")
                            out.write(chunk)
                    os.replace(tmp, target)
                except Exception:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    skipped_unsafe += 1
                    continue

                written += 1
                total += got
    except Exception as e:  # last-resort guard: never crash the agent
        if written == 0:
            return f"Error: couldn't extract that archive, sir ({_ascii(str(e))})."

    if written == 0:
        if skipped_exist and not skipped_unsafe:
            return (f"Everything in '{_ascii(src.name)}' is already extracted at "
                    f"{_ascii(str(dest_dir))}, sir; I didn't overwrite anything.")
        if skipped_unsafe:
            return (f"Error: I couldn't safely extract '{_ascii(src.name)}', sir "
                    "-- its entries looked unsafe.")
        return f"Error: '{_ascii(src.name)}' had nothing to extract, sir."

    head = (f"Extracted {written} file{'s' if written != 1 else ''} "
            f"({_mb(total)}) into {_ascii(str(dest_dir))}, sir.")
    extras = []
    if skipped_exist:
        extras.append(f"skipped {skipped_exist} that already existed")
    if skipped_unsafe:
        extras.append(f"skipped {skipped_unsafe} I couldn't safely unpack")
    if extras:
        head += " (" + "; ".join(extras) + ")"
    return head + note
