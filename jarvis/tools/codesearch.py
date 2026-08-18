"""Grep-style regex code search for Jarvis.

This is a developer-grade ``grep``: search the CONTENTS of files in a project
folder for a **regular expression** and return the file, line number and line
for every match. It is the tool Jarvis uses to NAVIGATE a codebase before it
edits it -- "where is this function defined", "find every call to set_volume",
"which file has the TODOs", "find `import requests`". It complements the two
existing finders:

- ``find_files`` matches a file's NAME.
- ``search_files`` matches plain TEXT inside files (a case-insensitive
  substring) -- aimed at notes/documents ("which note has the wifi password").
- ``search_code`` (this tool) matches a **regex** inside files and can be
  limited to a file **glob** (``*.py``, ``src/**/*.js``) -- aimed at code.

Safety model (identical boundaries to the other file tools, because an 8B
local model WILL eventually pass junk, the wrong type, or an evil pattern):

- **Rooted in the user's home only.** The start folder is resolved and REJECTED
  unless it lives inside the user's home, so a search can never read
  ``C:\\Windows`` or the whole drive. (Reuses ``find._resolve_root``.)
- **System / heavy folders are pruned** (``find._SKIP_DIRS``: .git,
  node_modules, venv, AppData, ...), so a code search stays fast and relevant.
- **Text only, bounded everywhere.** Binary files (by extension AND a NUL-byte
  sniff) and files over ``MAX_FILE_BYTES`` are skipped; max depth, files read,
  entries scanned, matches (total and per file) and a wall-clock budget all
  apply -- a pathological pattern stops early with a note instead of hanging.
- **A bad regex never crashes.** An invalid pattern is retried as literal text
  (and the reply says so), so a stray ``(`` is a self-correcting hint, not a
  dead end. A catastrophic-backtracking pattern is bounded by the time budget.
- **Pure ASCII out, never raises.** Matched lines are sanitised to bounded
  single-line ASCII (reused from ``search``); any unexpected error comes back
  as a friendly string the model can read and recover from.
"""

import fnmatch
import os
import re
import time
from pathlib import Path

from ..config import HOME
from .find import _SKIP_DIRS, _coerce, _resolve_root
from .registry import tool
from .search import _BINARY_EXTS, _ascii, _looks_binary

MAX_PATTERN_LEN = 400       # a search pattern, not an essay
MAX_GLOB_LEN = 200
MAX_RESULTS = 60            # most matching lines returned in one call
MAX_MATCHES_PER_FILE = 8    # don't let one noisy file drown the rest
MAX_FILES = 4000            # most files opened + read before giving up
MAX_SCAN = 60000            # most filesystem entries visited
MAX_DEPTH = 12             # code trees run deeper than document trees
TIME_BUDGET = 10.0          # hard wall-clock cap (seconds)
MAX_FILE_BYTES = 2_000_000  # skip files bigger than this (2 MB)
MAX_CONTEXT = 10            # most surrounding lines shown on each side of a match


def _glob_to_regex(pat: str) -> "re.Pattern":
    """Translate a path glob to a regex over a '/'-separated relative path.

    Standard glob semantics: ``*`` matches within one path segment, ``?`` one
    character, and ``**`` (optionally followed by ``/``) matches across
    segments -- so ``src/**/*.py`` matches ``src/a/b/foo.py`` and ``**/*.py``
    matches ``foo.py`` too. Case-insensitive (matched against a lowered path).
    """
    i, n = 0, len(pat)
    out: list[str] = []
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 2] == "**":
                i += 2
                if pat[i:i + 1] == "/":
                    i += 1
                out.append(".*")        # any chars, path separators included
            else:
                out.append("[^/]*")     # any chars within one segment
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("(?s:" + "".join(out) + r")\Z")


def _compile_globs(glob: str):
    """Turn the ``glob`` argument into (basename_patterns, path_matchers).

    Several patterns may be given separated by commas, spaces or pipes. A bare
    extension (``py`` or ``.py``) becomes ``*.py``; a pattern with a path
    separator is matched against the file's relative path (with ``**`` support),
    everything else against the file's name. Returns ``([], [])`` for no filter.
    """
    raw = _coerce(glob, MAX_GLOB_LEN)
    if not raw or raw.strip("*?[]/. ") == "":   # empty or "match anything"
        return [], []
    parts = [p.strip() for p in re.split(r"[,\s|]+", raw) if p.strip()]
    names: list[str] = []
    paths: list = []
    for p in parts:
        low = p.lower().replace("\\", "/")
        has_wild = any(ch in low for ch in "*?[")
        if "/" in low:
            paths.append(_glob_to_regex(low))
        elif not has_wild and "." not in low:
            names.append("*." + low)            # 'py' -> '*.py'
        elif not has_wild and low.startswith("."):
            names.append("*" + low)             # '.py' -> '*.py'
        else:
            names.append(low)
    return names, paths


def _file_matches(rel_posix: str, base: str, names, paths) -> bool:
    """Does this file pass the glob filter? (No filter -> always True.)"""
    if not names and not paths:
        return True
    for pat in names:
        if fnmatch.fnmatch(base, pat):
            return True
    for rx in paths:
        if rx.match(rel_posix):
            return True
    return False


def _compile_pattern(pattern: str, case_sensitive: bool):
    """Compile the pattern as a regex, falling back to a literal search if it
    is not valid regex. Returns (compiled, note) where note is a short string
    telling the model we treated an invalid pattern as literal text (or "")."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return re.compile(pattern, flags), ""
    except re.error:
        return (re.compile(re.escape(pattern), flags),
                " (the pattern wasn't a valid regex, so I searched for it as "
                "plain text)")


def _coerce_context(value, extra) -> int:
    """Read the optional context-lines argument (a small non-negative int).

    Accepts the primary ``context`` plus the arg names an 8B model reaches for
    (``context_lines``/``around``/``C``/``lines``). Junk, a negative or the
    wrong type -> 0 (no context); clamped to MAX_CONTEXT so one hallucinated
    huge value can't blow up the output."""
    raw = value
    if raw in (None, "", 0, "0"):
        for k in ("context_lines", "around", "C", "lines", "before_after"):
            v = extra.get(k)
            if v not in (None, ""):
                raw = v
                break
    try:
        n = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, MAX_CONTEXT))


def _format_with_context(lines: list, match_idx: list, context: int) -> list[str]:
    """Expand each 0-based match index into a window of +/- ``context`` lines.

    Overlapping or adjacent windows are merged; separate groups are divided by a
    ``    --`` line. A matched line is rendered ``    <lineno>: <text>`` and a
    context line ``    <lineno>- <text>`` (grep's ``:`` vs ``-`` convention)."""
    match_set = set(match_idx)
    total = len(lines)
    windows: list[list[int]] = []
    for m in match_idx:
        lo = max(0, m - context)
        hi = min(total - 1, m + context)
        if windows and lo <= windows[-1][1] + 1:
            windows[-1][1] = max(windows[-1][1], hi)
        else:
            windows.append([lo, hi])
    out: list[str] = []
    for gi, (lo, hi) in enumerate(windows):
        if gi > 0:
            out.append("    --")
        for idx in range(lo, hi + 1):
            sep = ":" if idx in match_set else "-"
            out.append(f"    {idx + 1}{sep} {_ascii(lines[idx])}")
    return out


def _search_file(path: Path, rx, context: int = 0) -> list[str]:
    """Return display lines for the matches in this file, or [].

    With ``context == 0`` each match is a single ``    <lineno>: <text>`` line
    (unchanged behaviour). With ``context > 0`` up to ``context`` lines on each
    side of every match are included so the model sees the surrounding code
    before editing. At most MAX_MATCHES_PER_FILE matches are considered."""
    try:
        if context <= 0:
            hits: list[str] = []
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    if rx.search(line):
                        hits.append(f"    {lineno}: {_ascii(line)}")
                        if len(hits) >= MAX_MATCHES_PER_FILE:
                            break
            return hits
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        match_idx: list[int] = []
        for i, line in enumerate(lines):
            if rx.search(line):
                match_idx.append(i)
                if len(match_idx) >= MAX_MATCHES_PER_FILE:
                    break
        if not match_idx:
            return []
        return _format_with_context(lines, match_idx, context)
    except (OSError, ValueError):
        return []   # permission / decode / anything: skip, never crash


@tool(
    "search_code",
    "Search the CONTENTS of files in a project folder for a regular expression "
    "(regex) and return the file, line number and line for each match -- like "
    "grep. Use this to NAVIGATE code before editing it: find where a function "
    "or class is defined, every place something is called or imported, all the "
    "TODO/FIXME notes, or any pattern across a codebase (e.g. 'def "
    "run_project', 'import requests', 'TODO|FIXME', 'class .*Error'). Optional "
    "'folder' limits where to look (e.g. 'Desktop/myapp'); optional 'glob' "
    "limits which files by name or path pattern (e.g. '*.py', 'src/**/*.js'). "
    "This searches a REGEX in file contents; use find_files to find a file by "
    "name, or search_files for a plain-text substring in notes/documents. Only "
    "the user's home folder is searched.",
    {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regular expression to look for in file "
                "contents, e.g. 'def my_func', 'import requests', "
                "'TODO|FIXME'. Case-insensitive unless case_sensitive is true.",
            },
            "folder": {
                "type": "string",
                "description": "Optional project folder to search under, e.g. "
                "'Desktop/myapp'. Defaults to the whole home folder.",
            },
            "glob": {
                "type": "string",
                "description": "Optional file pattern to limit which files are "
                "searched, e.g. '*.py', '*.js', or a path glob like "
                "'src/**/*.ts'. Several can be given separated by commas.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Match upper/lower case exactly. Default false "
                "(case-insensitive).",
            },
            "context": {
                "type": "integer",
                "description": "Optional number of surrounding lines to show "
                "above and below each match (like grep -C), so you can see the "
                "code around a match before editing it. Default 0 (just the "
                "matching lines).",
            },
        },
        "required": ["pattern"],
    },
)
def search_code(pattern: str = "", folder: str = "", glob: str = "",
                case_sensitive=False, context=0, **extra) -> str:
    # forgiving arg names an 8B model reaches for
    if not pattern:
        pattern = extra.get("regex") or extra.get("query") or \
            extra.get("text") or extra.get("search") or ""
    if not glob:
        glob = extra.get("file") or extra.get("files") or \
            extra.get("name") or extra.get("include") or ""
    if not folder:
        folder = extra.get("dir") or extra.get("directory") or \
            extra.get("project") or extra.get("path") or ""

    glob = _coerce(glob, MAX_GLOB_LEN)   # keep it a string for display + matching
    term = _coerce(pattern, MAX_PATTERN_LEN)
    if not term:
        return ("Error: tell me what to search for in the code, sir (a word or "
                "a regex like 'def my_func' or 'TODO|FIXME').")

    root, err = _resolve_root(folder)
    if root is None:
        return err

    case_sensitive = str(case_sensitive).strip().lower() in ("true", "1", "yes", "on")
    ctx = _coerce_context(context, extra)
    rx, note = _compile_pattern(term, case_sensitive)
    names, paths = _compile_globs(glob)

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
                fpath = Path(dirpath) / fn
                base = fn.lower()
                if names or paths:
                    try:
                        rel = fpath.relative_to(root).as_posix().lower()
                    except ValueError:
                        rel = base
                    if not _file_matches(rel, base, names, paths):
                        continue
                if os.path.splitext(base)[1] in _BINARY_EXTS:
                    continue
                try:
                    if fpath.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if _looks_binary(fpath):
                    continue

                files_read += 1
                hits = _search_file(fpath, rx, ctx)
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
    except Exception as e:   # last-resort guard -- never crash the agent
        if not results:
            return f"Error while searching the code, sir: {_ascii(str(e))}"

    if not results:
        where = "your home folder" if str(root) == str(Path(HOME).resolve()) \
            else f"'{root}'"
        scope = f" matching {_ascii(glob)}" if (names or paths) else ""
        return (f'No code matching "{_ascii(term)}" found in {where}'
                f'{scope}, sir.{note}')

    n_files = len(results)
    body = "\n".join(f"- {block}" for block in results)
    tail = ""
    if hit_limit:
        tail = ("\n(stopped early; narrow the pattern, name a folder, or add a "
                "glob like '*.py' for more)")
    head = (f'Found "{_ascii(term)}" in {n_files} file(s) '
            f"({match_lines} line(s) shown):{note}")
    return f"{head}\n{body}{tail}"
