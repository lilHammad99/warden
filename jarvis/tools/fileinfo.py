"""Report the exact facts about a single file for Jarvis -- "tell me about this
file".

The file family can already LOCATE a file (``find_files`` / ``search_files`` /
``recent_files``), REARRANGE it (``move_file`` / ``copy_file`` / ...), back it up
and restore it (``zip_files`` / ``unzip_files``), remove it (``recycle_file``),
report how much room a whole FOLDER uses (``folder_size``) and find files stored
twice (``find_duplicates``). The one everyday question still missing was "tell me
about THIS file" -- exactly how big is it, when did I create or last change it,
is it read-only, and what is its checksum. An 8B model cannot answer any of that
by guessing (it makes up sizes and dates, and it certainly cannot compute a
hash), so ``file_info`` reports the EXACT facts instead -- the same philosophy as
``calculate`` (arithmetic), ``convert_units`` (conversions) and ``count_words``
(length): a real number, not a hallucination.

It answers "how big is this file exactly", "when did I create/last change this",
"is this file read-only", "what's the checksum of this download" (so the user can
verify a download matches a published SHA-256). It is read-only and the natural
companion to ``find_files`` (locate the file, then describe it).

Safety model (the strict handling the project asks for, because an 8B local model
WILL eventually pass junk, the wrong type, or point at the wrong thing):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless it
  lives inside the user's home directory (shared with ``find_files`` /
  ``organize``), including a ``..``-escape, so the model can never read a file
  under ``C:\\Windows`` or outside the user's own folders.
- **A single file only.** A folder is refused and the model is steered to
  ``folder_size`` (which measures a whole tree).
- **Bounded.** The checksum is streamed and only computed for files up to a size
  cap (a huge file is reported without a hash rather than hanging the agent); the
  text line/word count reads at most a bounded number of bytes.
- **Pure ASCII out.** The name and every field are sanitised so an odd filename
  can never corrupt the console or the model's context.
- **Read-only + never raises.** Nothing here writes, moves or deletes anything;
  wrong-type args are coerced, and any unexpected error comes back as a friendly
  string.
"""

import hashlib
import os
import stat as stat_mod
import time
from datetime import datetime
from pathlib import Path

from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .recent import _ago
from .registry import tool

MAX_PATH_LEN = 400                    # a path, not an essay
MAX_HASH_BYTES = 400 * 1024 * 1024    # never checksum a file bigger than this (400 MB)
MAX_TEXT_BYTES = 20 * 1024 * 1024     # bytes read when counting lines/words in text
_CHUNK = 1024 * 1024                  # 1 MB read chunk while hashing / counting

# extensions we treat as clearly binary, so we never try to count "lines" in a
# photo or video even if it happens to contain no NUL byte.
_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".ico",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv",
    ".zip", ".gz", ".tar", ".7z", ".rar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".msi", ".iso",
    ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
    ".doc", ".xls", ".ppt", ".ttf", ".otf", ".woff", ".woff2",
    ".db", ".sqlite", ".pyc", ".class", ".o", ".obj",
}

# friendly type labels for the common extensions the user actually has
_TYPE_LABELS = {
    ".txt": "text", ".md": "text", ".log": "text", ".csv": "CSV data",
    ".tsv": "TSV data", ".json": "JSON data", ".jsonl": "JSON Lines data",
    ".xml": "XML", ".yaml": "YAML", ".yml": "YAML", ".ini": "config",
    ".py": "Python code", ".js": "JavaScript code", ".html": "HTML",
    ".css": "CSS", ".pdf": "PDF document", ".docx": "Word document",
    ".doc": "Word document", ".odt": "OpenDocument text",
    ".xlsx": "Excel spreadsheet", ".xls": "Excel spreadsheet",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".bmp": "image", ".webp": "image", ".ico": "image", ".tif": "image",
    ".tiff": "image", ".svg": "image",
    ".mp3": "audio", ".wav": "audio", ".flac": "audio", ".m4a": "audio",
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    ".webm": "video", ".wmv": "video",
    ".zip": "zip archive", ".7z": "7-Zip archive", ".rar": "RAR archive",
    ".gz": "gzip archive", ".tar": "tar archive",
    ".exe": "program", ".msi": "installer", ".dll": "library",
}


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


def _type_label(ext: str) -> str:
    """A short friendly type name from an extension."""
    ext = ext.lower()
    if not ext:
        return "file (no extension)"
    label = _TYPE_LABELS.get(ext)
    if label:
        return f"{label} ({ext})"
    return f"{ext[1:].upper()} file" if len(ext) > 1 else "file"


def _stamp(epoch: float, now: float) -> str:
    """A 'YYYY-MM-DD HH:MM (how long ago)' phrase, pure ASCII. Never raises."""
    try:
        when = datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "unknown"
    delta = now - epoch
    if delta < 0:            # a clock-skewed future timestamp: don't say "-2s ago"
        return when
    return f"{when} ({_ago(delta)})"


def _is_binary(path: Path, ext: str) -> bool:
    """True if the file looks binary (known-binary extension OR a NUL byte in the
    first chunk). Used only to decide whether a line/word count is meaningful."""
    if ext in _BINARY_EXTS:
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return True
    return b"\x00" in head


def _count_text(path: Path):
    """Count (lines, words) over a bounded number of bytes. Returns
    (lines, words, truncated) or None if the file can't be read. Never raises."""
    newlines = 0
    words = 0
    read = 0
    last_byte = b""
    truncated = False
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                read += len(chunk)
                newlines += chunk.count(b"\n")
                words += len(chunk.split())
                last_byte = chunk[-1:]
                if read >= MAX_TEXT_BYTES:
                    truncated = True
                    break
    except OSError:
        return None
    # a file whose last read byte isn't a newline still has a final, uncounted
    # line (e.g. a one-line file with no trailing newline)
    lines = newlines + (1 if read and last_byte != b"\n" else 0)
    return lines, words, truncated


def _checksum(path: Path):
    """Streamed SHA-256 hex digest of the whole file, or None if unreadable."""
    h = hashlib.sha256()
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
    "file_info",
    "Report the exact facts about a single file: its type, its exact size, when "
    "it was created and last changed, whether it is read-only, its line count "
    "(for text files), and its SHA-256 checksum. Use this when the user asks "
    "about ONE specific file ('how big is this file exactly', 'when did I create "
    "this', 'when did I last change my resume', 'is this file read-only', "
    "'what's the checksum of this download'). This is read-only -- it never "
    "changes anything. To measure a whole FOLDER instead, use folder_size. Give "
    "the file path (locate it first with find_files if you don't know it). Only "
    "the user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file to describe, e.g. 'Documents/resume.docx' "
                "or 'Desktop/report.pdf'.",
            },
        },
        "required": ["path"],
    },
)
def file_info(path: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("source"),
                     extra.get("document"), extra.get("doc"), extra.get("name"),
                     extra.get("target"))
    if not raw:
        return "Error: tell me which file to describe, sir."

    p, err = _resolve_under_home(_coerce(raw, MAX_PATH_LEN))
    if p is None:
        return err or "Error: that file path isn't valid, sir."
    if not p.exists():
        return f"Error: I can't find '{_ascii(str(p))}', sir."
    if p.is_dir():
        return (f"Error: '{_ascii(p.name)}' is a folder, sir; use folder_size to "
                "measure a whole folder.")
    if not p.is_file():
        return (f"Error: '{_ascii(p.name)}' isn't an ordinary file, sir.")

    try:
        st = p.stat()
    except OSError as e:
        return f"Error: I couldn't read that file's details, sir ({_ascii(str(e))})."

    now = time.time()
    ext = p.suffix.lower()
    size = st.st_size

    # read-only: prefer the real Windows attribute, fall back to a write probe
    read_only = False
    attrs = getattr(st, "st_file_attributes", None)
    if attrs is not None:
        read_only = bool(attrs & stat_mod.FILE_ATTRIBUTE_READONLY)
    else:
        read_only = not os.access(p, os.W_OK)

    lines = [
        _ascii(p.name),
        f"Type: {_type_label(ext)}",
        f"Size: {_human(size)} ({size:,} bytes)",
        f"Modified: {_stamp(st.st_mtime, now)}",
        f"Created:  {_stamp(st.st_ctime, now)}",
        f"Read-only: {'yes' if read_only else 'no'}",
    ]

    # line/word count only makes sense for text files
    if size > 0 and not _is_binary(p, ext):
        counted = _count_text(p)
        if counted is not None:
            n_lines, n_words, truncated = counted
            more = " (first part only)" if truncated else ""
            lines.append(f"Lines: {n_lines:,}  Words: {n_words:,}{more}")

    # checksum: bounded so a giant file can't hang the agent
    if size == 0:
        lines.append("SHA-256: (empty file)")
    elif size > MAX_HASH_BYTES:
        lines.append(f"SHA-256: (skipped -- file over {_human(MAX_HASH_BYTES)})")
    else:
        digest = _checksum(p)
        lines.append(f"SHA-256: {digest}" if digest
                     else "SHA-256: (couldn't read the file to hash it)")

    return "\n".join(lines)
