"""Recently changed files for Jarvis (search by TIME), the third member of the
file-navigation family after find_files (by NAME) and search_files (by
CONTENT).

``find_files`` locates a file by its name and ``search_files`` by what's inside
it; this tool answers "what did I just work on?" -- it lists the user's most
recently modified files, newest first, so Jarvis can reopen the thing they were
last editing or report what changed today ("open the file I was just editing",
"what did I work on today", "what did I change this week"). It then hands the
paths to the other file/app tools.

Safety model (the strict handling the project asks for, because an 8B local
model WILL eventually pass junk, the wrong type, or try to crawl the whole
disk):

- **Rooted in the user's home only.** The start folder is resolved and then
  REJECTED unless it lives inside the user's home directory (shared with
  ``find_files``), so the model can never crawl ``C:\\Windows`` or all of
  ``C:\\``.
- **System / heavy folders are pruned** (AppData, node_modules, .git, ...).
- **Bounded everywhere.** ``days`` is coerced and clamped; max search depth,
  max entries scanned, max results returned, and a hard wall-clock time budget
  all apply -- a pathological query stops early with a clear note instead of
  hanging the agent.
- **Pure ASCII out.** Paths are sanitised to ASCII so an odd filename can never
  corrupt the console or the model's context.
- **Never raises.** Wrong-type args are coerced, un-stat-able / permission-
  blocked files are skipped, and any unexpected error comes back as a friendly
  string the model can read and recover from.
"""

import fnmatch
import math
import os
import re
import time
from pathlib import Path

from ..config import HOME
from .find import _SKIP_DIRS, _coerce, _resolve_root
from .registry import tool

MAX_RESULTS = 30          # most files listed in one call
MAX_SCAN = 40000          # most filesystem entries visited before giving up
MAX_DEPTH = 8             # how deep below the start folder we recurse
TIME_BUDGET = 8.0         # hard wall-clock cap (seconds)
DEFAULT_DAYS = 7          # look back a week unless told otherwise
MAX_DAYS = 3650           # never look back more than ~10 years
MAX_NAME_LEN = 200        # a pattern, not an essay


def _ascii(text: str) -> str:
    """Force a path/string to safe, single-line, bounded ASCII."""
    text = text.replace("\r", " ").replace("\n", " ")
    return text.encode("ascii", "replace").decode("ascii")


def _coerce_days(value) -> float:
    """Turn any model-supplied 'days' into a positive, clamped number of days.
    Unparseable / non-finite / non-positive falls back to DEFAULT_DAYS; a huge
    value is clamped so it can never overflow the cutoff arithmetic."""
    if isinstance(value, bool):        # True/False is not a day count
        return DEFAULT_DAYS
    n = None
    if isinstance(value, (int, float)):
        n = value
    elif isinstance(value, str):
        m = re.search(r"\d+(?:\.\d+)?", value)
        if m:
            n = m.group()
    if n is None:
        return DEFAULT_DAYS
    try:
        n = float(n)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    if not math.isfinite(n) or n <= 0:
        return DEFAULT_DAYS
    return min(n, float(MAX_DAYS))


def _ago(seconds: float) -> str:
    """A short, human, pure-ASCII 'how long ago' phrase."""
    s = int(seconds)
    if s < 0:
        s = 0
    if s < 60:
        return "just now"
    m = s // 60
    if m < 60:
        return f"{m} minute{'s' if m != 1 else ''} ago"
    h = m // 60
    if h < 24:
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = h // 24
    if d == 1:
        return "yesterday"
    if d < 7:
        return f"{d} days ago"
    w = d // 7
    if d < 30:
        return f"{w} week{'s' if w != 1 else ''} ago"
    mo = d // 30
    if mo < 12:
        return f"{mo} month{'s' if mo != 1 else ''} ago"
    y = d // 365
    return f"{y} year{'s' if y != 1 else ''} ago"


def _days_phrase(days: float) -> str:
    """Describe the window for the header, avoiding an ugly '7.0 days'."""
    if float(days).is_integer():
        d = int(days)
        return "day" if d == 1 else f"{d} days"
    return f"{days:g} days"


@tool(
    "recent_files",
    "List the user's most recently changed files, newest first. Use this when "
    "the user refers to something by WHEN they last touched it rather than by "
    "name or contents (e.g. 'open the file I was just editing', 'what did I "
    "work on today', 'what did I change this week'). You can then read or open "
    "a result with the other tools. find_files searches by name and "
    "search_files by contents; this one searches by time. Optionally limit to "
    "the last N days, a folder like 'Documents', and a file-name pattern like "
    "'*.docx'. Only the user's home folder is searched.",
    {
        "type": "object",
        "properties": {
            "days": {
                "type": "number",
                "description": "How many days back to look (default 7). "
                "Use a small number like 1 for 'today', 7 for 'this week'.",
            },
            "folder": {
                "type": "string",
                "description": "Optional folder to look under, e.g. "
                "'Documents' or 'Desktop'. Defaults to the whole home folder.",
            },
            "name": {
                "type": "string",
                "description": "Optional file-name pattern to limit results, "
                "e.g. '*.docx' or '*.py'.",
            },
        },
        "required": [],
    },
)
def recent_files(days=DEFAULT_DAYS, folder: str = "", name: str = "") -> str:
    days = _coerce_days(days)

    root, err = _resolve_root(folder)
    if root is None:
        return err

    name_pat = _coerce(name, MAX_NAME_LEN).lower()
    # a bare "*" name filter means "any file" -> treat as no filter
    if name_pat.strip("*?[] ") == "":
        name_pat = ""

    now = time.time()
    cutoff = now - days * 86400.0
    found: list[tuple[float, str]] = []   # (mtime, path)
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
                if name_pat and not fnmatch.fnmatch(fn.lower(), name_pat):
                    continue
                fpath = Path(dirpath) / fn
                try:
                    mtime = fpath.stat().st_mtime
                except OSError:
                    continue  # permission / vanished: skip, never crash
                if mtime >= cutoff:
                    found.append((mtime, str(fpath)))

            if scanned >= MAX_SCAN:
                hit_limit = True
                break
            if time.monotonic() - started > TIME_BUDGET:
                hit_limit = True
                break
    except Exception as e:  # last-resort guard -- never crash the agent
        if not found:
            return f"Error while looking for recent files, sir: {_ascii(str(e))}"

    window = _days_phrase(days)
    if not found:
        where = "your home folder" if str(root) == str(Path(HOME).resolve()) \
            else f"'{_ascii(str(root))}'"
        extra = f" matching '{_ascii(name_pat)}'" if name_pat else ""
        return (f"No files changed in the last {window} in {where}{extra}, sir.")

    # newest first; keep only the top slice (more scanned than shown is fine)
    found.sort(key=lambda t: t[0], reverse=True)
    more = len(found) > MAX_RESULTS
    top = found[:MAX_RESULTS]

    lines = []
    for mtime, path in top:
        lines.append(f"- {_ascii(path)}  ({_ago(now - mtime)})")
    body = "\n".join(lines)

    note = ""
    if hit_limit:
        note = ("\n(stopped scanning early; name a folder or a file pattern "
                "to narrow it)")
    elif more:
        note = (f"\n(showing the {MAX_RESULTS} most recent of {len(found)}; "
                "narrow with a folder, a pattern, or fewer days)")
    head = f"Most recently changed file(s) in the last {window}:"
    return f"{head}\n{body}{note}"
