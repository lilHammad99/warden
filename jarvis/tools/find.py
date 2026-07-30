"""Find files by name for Jarvis.

Makes the assistant more autonomous: instead of the user having to hand over
an exact path, the model can locate a file itself ("open my budget
spreadsheet", "read my CV") and then act on it with the existing file/app
tools. It searches the user's own folders only.

Safety model (this is the strict error handling the project asks for, because
an 8B local model WILL eventually pass junk, the wrong type, or try to crawl
the whole disk):

- **Rooted in the user's home only.** A search folder is resolved and then
  REJECTED unless it lives inside the user's home directory, so the model can
  never point Jarvis at ``C:\\Windows`` or the whole ``C:\\`` drive.
- **System / heavy folders are pruned** (AppData, node_modules, .git, the
  recycle bin, ...), so results are relevant and scans stay fast.
- **Bounded everywhere.** Max search depth, max entries scanned, max results
  returned, and a hard wall-clock time budget — a pathological query stops
  early with a clear note instead of hanging the agent.
- **Never raises.** Wrong-type args are coerced, over-long names are capped,
  missing/permission-blocked folders are skipped, and any unexpected error
  comes back as a friendly string the model can read and recover from.
"""

import fnmatch
import os
import time
from pathlib import Path

from ..config import HOME
from .registry import tool

# folder names we never descend into: noisy, huge, or none of the user's
# business. Compared case-insensitively against each directory name.
_SKIP_DIRS = {
    "appdata", "application data", "node_modules", "__pycache__",
    ".git", ".svn", ".hg", ".venv", "venv", "env", ".cache", ".npm",
    "$recycle.bin", "windows", "program files", "program files (x86)",
    "programdata", ".ollama", "site-packages", "dist-packages",
    ".gradle", ".m2", ".nuget", "temp", "tmp",
}

MAX_RESULTS = 50        # most matches returned in one call
MAX_SCAN = 30000        # most filesystem entries visited before giving up
MAX_DEPTH = 8           # how deep below the start folder we recurse
TIME_BUDGET = 8.0       # hard wall-clock cap (seconds)
MAX_NAME_LEN = 200      # a search term, not an essay


def _coerce(value, limit: int) -> str:
    """Turn any model-supplied value into a safe, bounded, trimmed string."""
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        raw = str(value)  # model sometimes passes a number / list / dict
    return raw.replace("\x00", "").strip().strip('"').strip("'")[:limit]


def _resolve_root(folder: str) -> tuple[Path | None, str]:
    """Resolve a start folder and confirm it is inside the user's home.
    Returns (path, "") on success or (None, error_message)."""
    folder = _coerce(folder, 400)
    if not folder:
        root = Path(HOME)
    else:
        p = Path(folder.replace("~", str(HOME)))
        if not p.is_absolute():
            p = Path(HOME) / p  # "Documents" -> home\Documents
        root = p
    try:
        root = root.resolve()
        home = Path(HOME).resolve()
    except OSError as e:
        return None, f"Error: can't use that folder, sir ({e})."
    # containment check: the search must stay inside the user's home
    try:
        if root != home and home not in root.parents:
            return None, ("Error: I only search inside your own folders, sir "
                          f"(under {home}). '{root}' is outside that.")
    except Exception:
        return None, "Error: that folder path isn't valid, sir."
    if not root.exists():
        return None, f"Error: the folder '{root}' does not exist, sir."
    if not root.is_dir():
        return None, f"Error: '{root}' is a file, not a folder, sir."
    return root, ""


def _matches(filename: str, term: str) -> bool:
    """Case-insensitive match. Wildcards (* ?) use glob semantics; otherwise
    the term is treated as a substring of the file name."""
    name = filename.lower()
    if any(ch in term for ch in "*?[]"):
        pat = term if term.startswith("*") else f"*{term}"
        if not term.endswith(("*", "]")):
            pat = f"{pat}*"
        try:
            return fnmatch.fnmatch(name, pat.lower())
        except Exception:
            return term.lower() in name
    return term.lower() in name


@tool(
    "find_files",
    "Search the user's own folders for files whose name contains the given "
    "text, and return the matching full paths. Use this when the user refers "
    "to a file without giving its exact location (e.g. 'open my budget "
    "spreadsheet', 'read my CV'). You can then read or open a result with the "
    "other tools. Optionally limit the search to a folder like 'Documents'. "
    "Only the user's home folder is searched.",
    {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Text or wildcard the file name should contain, "
                "e.g. 'budget', 'cv', '*.xlsx'",
            },
            "folder": {
                "type": "string",
                "description": "Optional folder to search under, e.g. "
                "'Documents' or 'Desktop'. Defaults to the whole home folder.",
            },
        },
        "required": ["name"],
    },
)
def find_files(name: str = "", folder: str = "") -> str:
    term = _coerce(name, MAX_NAME_LEN)
    if not term:
        return "Error: tell me part of the file name to look for, sir."
    # a bare "*" (or only wildcards) would match everything — refuse it
    if term.strip("*?[] ") == "":
        return ("Error: that search is too broad, sir — give me part of the "
                "file name, like 'budget' or '*.pdf'.")

    root, err = _resolve_root(folder)
    if root is None:
        return err

    results: list[str] = []
    scanned = 0
    started = time.monotonic()
    hit_limit = False
    root_depth = len(root.parts)

    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            # prune noisy/system dirs and enforce depth in-place
            depth = len(Path(dirpath).parts) - root_depth
            if depth >= MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames
                               if d.lower() not in _SKIP_DIRS
                               and not d.startswith("$")]

            for fn in filenames:
                scanned += 1
                if _matches(fn, term):
                    try:
                        results.append(str(Path(dirpath) / fn))
                    except Exception:
                        continue
                    if len(results) >= MAX_RESULTS:
                        hit_limit = True
                        break

            if hit_limit or scanned >= MAX_SCAN:
                hit_limit = hit_limit or scanned >= MAX_SCAN
                break
            if time.monotonic() - started > TIME_BUDGET:
                hit_limit = True
                break
    except Exception as e:  # last-resort guard — never crash the agent
        if not results:
            return f"Error while searching, sir: {e}"

    if not results:
        where = "your home folder" if str(root) == str(Path(HOME).resolve()) \
            else f"'{root}'"
        return f'No files matching "{term}" found in {where}, sir.'

    results.sort(key=str.lower)
    body = "\n".join(f"- {r}" for r in results)
    note = ""
    if hit_limit:
        note = (f"\n(stopped early at {len(results)} matches; narrow the "
                "search or name a folder for more)")
    head = f'Found {len(results)} file(s) matching "{term}":'
    return f"{head}\n{body}{note}"
