"""Search INSIDE files for Jarvis (content search), complementing find_files.

``find_files`` locates a file by its NAME; this tool looks at what is INSIDE
files and returns the lines that contain the text you are after ("which note
mentions the wifi password", "find the file where I wrote about the budget",
"which script calls set_volume"). Together they make Jarvis able to actually
locate information on the user's PC, a real autonomy win.

Safety model (the strict handling the project asks for, because an 8B local
model WILL eventually pass junk, the wrong type, or try to grep the whole
disk):

- **Rooted in the user's home only.** The start folder is resolved and then
  REJECTED unless it lives inside the user's home directory, so the model can
  never grep ``C:\\Windows`` or the whole ``C:\\`` drive. (Shared with
  ``find_files``.)
- **System / heavy folders are pruned** (AppData, node_modules, .git, ...).
- **Text only, bounded everywhere.** Binary files and huge files are skipped;
  max search depth, max files opened, max entries scanned, max matches (total
  and per file), and a hard wall-clock time budget all apply — a pathological
  query stops early with a clear note instead of hanging the agent.
- **Pure ASCII out.** Matched lines are sanitised to ASCII and truncated, so a
  file full of odd bytes can never corrupt the console or the model's context.
- **Never raises.** Wrong-type args are coerced, over-long queries are capped,
  unreadable/permission-blocked files are skipped, and any unexpected error
  comes back as a friendly string the model can read and recover from.
"""

import fnmatch
import os
import time
from pathlib import Path

from ..config import HOME
from .find import _SKIP_DIRS, _coerce, _resolve_root
from .registry import tool

# Extensions we never open (binary / huge / none of the user's business as
# text). Everything else is still NUL-byte checked before reading.
_BINARY_EXTS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat", ".class", ".pyc", ".pyd",
    ".o", ".a", ".lib", ".obj", ".msi", ".cab", ".iso", ".img",
    ".zip", ".rar", ".7z", ".gz", ".bz2", ".xz", ".tar", ".jar", ".whl",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".ico", ".webp",
    ".psd", ".svg", ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac",
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".pt", ".onnx", ".pkl",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".sys", ".lock",
}

MAX_QUERY_LEN = 200        # a search term, not an essay
MAX_RESULTS = 40           # most matching lines returned in one call
MAX_MATCHES_PER_FILE = 5   # don't drown one noisy file over the rest
MAX_FILES = 3000           # most files opened+read before giving up
MAX_SCAN = 40000           # most filesystem entries visited
MAX_DEPTH = 8              # how deep below the start folder we recurse
TIME_BUDGET = 8.0          # hard wall-clock cap (seconds)
MAX_FILE_BYTES = 2_000_000  # skip files bigger than this (2 MB)
MAX_LINE_LEN = 160         # each shown line truncated to this many chars


def _ascii(text: str) -> str:
    """Force a snippet to safe, single-line, bounded ASCII for the console."""
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    text = text.encode("ascii", "replace").decode("ascii")
    text = " ".join(text.split())  # collapse runs of whitespace
    if len(text) > MAX_LINE_LEN:
        text = text[:MAX_LINE_LEN] + "..."
    return text


def _looks_binary(path: Path) -> bool:
    """Cheap binary sniff: NUL byte in the first chunk => not text."""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(4096)
    except OSError:
        return True  # unreadable: treat as skip


def _search_file(path: Path, term_lower: str) -> list[str]:
    """Return up to MAX_MATCHES_PER_FILE '<lineno>: <text>' hits, or []."""
    hits: list[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                if term_lower in line.lower():
                    hits.append(f"    {lineno}: {_ascii(line)}")
                    if len(hits) >= MAX_MATCHES_PER_FILE:
                        break
    except (OSError, ValueError):
        return []  # permission / decode / anything: skip this file, never crash
    return hits


@tool(
    "search_files",
    "Search INSIDE the user's files for text and return the files and lines "
    "that contain it. Use this when the user asks WHICH file mentions "
    "something, or to find information they saved but can't locate (e.g. "
    "'which note has the wifi password', 'find where I wrote about the "
    "budget'). This looks at file CONTENTS; use find_files instead to find a "
    "file by its name. Optionally limit to a folder (like 'Documents') and to "
    "a file-name pattern (like '*.txt'). Only the user's home folder is "
    "searched.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The text to look for inside files, e.g. "
                "'wifi password' or 'budget'. Matched case-insensitively.",
            },
            "folder": {
                "type": "string",
                "description": "Optional folder to search under, e.g. "
                "'Documents' or 'Desktop'. Defaults to the whole home folder.",
            },
            "name": {
                "type": "string",
                "description": "Optional file-name pattern to limit which "
                "files are searched, e.g. '*.txt' or '*.py'.",
            },
        },
        "required": ["query"],
    },
)
def search_files(query: str = "", folder: str = "", name: str = "") -> str:
    term = _coerce(query, MAX_QUERY_LEN)
    if not term:
        return "Error: tell me what text to search for inside files, sir."

    root, err = _resolve_root(folder)
    if root is None:
        return err

    name_pat = _coerce(name, MAX_QUERY_LEN).lower()
    # a bare "*" name filter means "any file" -> treat as no filter
    if name_pat.strip("*?[] ") == "":
        name_pat = ""

    term_lower = term.lower()
    results: list[str] = []
    match_lines = 0
    files_read = 0
    scanned = 0
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

            for fn in filenames:
                scanned += 1
                low = fn.lower()
                if name_pat and not fnmatch.fnmatch(low, name_pat):
                    continue
                ext = os.path.splitext(low)[1]
                if ext in _BINARY_EXTS:
                    continue
                fpath = Path(dirpath) / fn
                try:
                    if fpath.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if _looks_binary(fpath):
                    continue

                files_read += 1
                hits = _search_file(fpath, term_lower)
                if hits:
                    room = MAX_RESULTS - match_lines
                    shown = hits[:room]
                    results.append(str(fpath) + "\n" + "\n".join(shown))
                    match_lines += len(shown)
                    if match_lines >= MAX_RESULTS:
                        hit_limit = True
                        break

                if files_read >= MAX_FILES or scanned >= MAX_SCAN:
                    hit_limit = True
                    break
                if time.monotonic() - started > TIME_BUDGET:
                    hit_limit = True
                    break

            if hit_limit:
                break
    except Exception as e:  # last-resort guard — never crash the agent
        if not results:
            return f"Error while searching, sir: {_ascii(str(e))}"

    if not results:
        where = "your home folder" if str(root) == str(Path(HOME).resolve()) \
            else f"'{root}'"
        return (f'No files containing "{_ascii(term)}" found in {where}, sir.')

    n_files = len(results)
    body = "\n".join(f"- {block}" for block in results)
    note = ""
    if hit_limit:
        note = ("\n(stopped early; narrow the text, name a folder, or add a "
                "file pattern like '*.txt' for more)")
    head = (f'Found "{_ascii(term)}" in {n_files} file(s) '
            f"({match_lines} line(s) shown):")
    return f"{head}\n{body}{note}"
