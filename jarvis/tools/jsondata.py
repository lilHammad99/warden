"""Read / summarise JSON (and JSON Lines) data files for Jarvis.

Structured-data handling, the natural next member of the data family after
``read_csv`` (Phase 30). ``read_file`` only dumps a JSON file's raw text, and an
8B local model is unreliable at eyeballing a wall of braces to answer "what's in
this file", "how many records are in my export", or "what fields does this data
have". ``read_json`` parses the file properly and reports its SHAPE exactly: the
top-level structure (an object with N fields, an array of N items, or a single
value), the field names and their value types, and a small, bounded preview --
the way ``read_csv`` summarises a spreadsheet. A real accuracy/autonomy win, and
the natural partner to ``find_files`` (locate the file, then read it).

Pure standard library: JSON is text, so ``json`` is all it takes -- NO new
dependency. Line-delimited JSON (``.jsonl`` / ``.ndjson``, one record per line --
common for exports and logs) is understood too.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point this at something enormous):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless it
  lives inside the user's home directory (same boundary as ``find_files``), so
  the model can never read a file from ``C:\\Windows``.
- **Bounded everywhere.** The file on disk is capped before reading, the JSONL
  scan is capped, only so many field names are listed, and the preview is capped
  in both characters and lines -- a giant or hostile file can't exhaust memory or
  flood the agent's context. A pathologically deep structure that would overflow
  the parser is caught and reported, not crashed on.
- **Pure ASCII out.** Field names and preview text are forced to single-line /
  bounded ASCII, so the summary can never corrupt the console/context.
- **Never raises.** A binary/Excel/PDF file, invalid JSON, a missing file, a
  folder, an empty file, the wrong type, an empty or missing path -- every one
  comes back as a friendly, pure-ASCII string the model can read and recover
  from.
"""

import json
from pathlib import Path

from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400                    # a path, not an essay
MAX_FILE_BYTES = 25 * 1024 * 1024     # refuse a JSON file bigger than this
MAX_JSONL_ROWS = 200_000             # most JSONL lines scanned before stopping
MAX_KEYS = 40                         # most field names listed
MAX_KEY_LEN = 60                      # truncate a single field name to this
MAX_VAL = 60                          # truncate a single scalar value to this
MAX_PREVIEW_CHARS = 1200              # cap the pretty-printed preview
MAX_PREVIEW_LINES = 30                # cap the preview's line count

# file types that clearly are NOT JSON text -- steer rather than decode the
# binary garbage that reading their bytes would produce.
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif", ".tiff",
    ".zip", ".gz", ".7z", ".rar", ".tar", ".exe", ".dll", ".msi", ".bin",
    ".mp3", ".wav", ".mp4", ".mov", ".avi", ".mkv", ".ttf", ".otf", ".woff",
    ".docx", ".odt", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".pdf",
}


def _typename(v) -> str:
    """A plain-English name for a JSON value's type."""
    if isinstance(v, bool):          # bool is a subclass of int -- check first
        return "true/false"
    if isinstance(v, (int, float)):
        return "number"
    if v is None:
        return "null"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "value"


def _key(name) -> str:
    """One field name, forced to safe single-line ASCII and truncated."""
    k = _ascii(str(name)).strip()
    if len(k) > MAX_KEY_LEN:
        k = k[:MAX_KEY_LEN - 3] + "..."
    return k or "(blank)"


def _scalar(v) -> str:
    """A short, ASCII, truncated inline rendering of a scalar value."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    s = _ascii(str(v)).strip()
    if len(s) > MAX_VAL:
        s = s[:MAX_VAL - 3] + "..."
    return s


def _fields_line(obj: dict) -> str:
    """List up to MAX_KEYS field names of an object with their value types."""
    keys = list(obj.keys())
    shown = keys[:MAX_KEYS]
    parts = [f"{_key(k)} ({_typename(obj[k])})" for k in shown]
    note = "" if len(keys) <= MAX_KEYS else f" (+{len(keys) - MAX_KEYS} more)"
    return ", ".join(parts) + note


def _preview(value) -> str:
    """A pretty-printed, ASCII, char- and line-bounded preview of the value."""
    try:
        text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    text = _ascii(_ascii_multiline(text))
    lines = text.split("\n")
    truncated = False
    if len(lines) > MAX_PREVIEW_LINES:
        lines = lines[:MAX_PREVIEW_LINES]
        truncated = True
    text = "\n".join(lines)
    if len(text) > MAX_PREVIEW_CHARS:
        text = text[:MAX_PREVIEW_CHARS]
        truncated = True
    if truncated:
        text = text.rstrip() + "\n... (preview truncated)"
    return text


def _ascii_multiline(text: str) -> str:
    """Like organize._ascii but KEEPS newlines (the preview is intentionally
    multi-line); non-ASCII bytes still become '?'."""
    return text.encode("ascii", "replace").decode("ascii")


def _parse_jsonl(text: str):
    """Parse line-delimited JSON. Returns (records, scanned, capped) or raises
    ValueError if the first non-blank line isn't valid JSON."""
    records = []
    scanned = 0
    capped = False
    first_seen = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        scanned += 1
        if scanned > MAX_JSONL_ROWS:
            capped = True
            break
        try:
            rec = json.loads(line)
        except ValueError:
            if not first_seen:
                raise
            continue  # tolerate a stray bad line once we know it's JSONL
        first_seen = True
        records.append(rec)
    return records, scanned, capped


@tool(
    "read_json",
    "Read and summarise a JSON data file: reports its structure (an object with "
    "N fields, or an array of N items), the field names and their types, and a "
    "short preview. Use this whenever the user asks about a .json (or .jsonl) "
    "file ('what's in this json', 'how many records are in my export', 'what "
    "fields does this data have', 'summarise this json'); read_file only dumps "
    "raw text and your own reading of nested JSON is unreliable, this parses it "
    "exactly. Give path (locate it first with find_files if you don't have it). "
    "Only the user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The JSON file to read, e.g. 'Downloads/export.json'.",
            },
        },
        "required": ["path"],
    },
)
def read_json(path: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("document"),
                     extra.get("source"), extra.get("name"),
                     extra.get("filename"), extra.get("json"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me which JSON file to read, sir."

    p, err = _resolve_under_home(raw)
    if p is None:
        return err or "Error: that file path isn't valid, sir."
    if not p.exists():
        return f"Error: I can't find '{_ascii(str(p))}', sir."
    if p.is_dir():
        return (f"Error: '{_ascii(p.name)}' is a folder, sir; give me a JSON file "
                "to read.")

    suffix = p.suffix.lower()
    if suffix in _BINARY_EXT:
        return (f"Error: '{_ascii(p.name)}' isn't a JSON text file, sir, so I "
                "can't read it as JSON.")

    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    if size > MAX_FILE_BYTES:
        return (f"Error: '{_ascii(p.name)}' is too large for me to read safely, "
                "sir.")

    try:
        data = p.read_bytes()
    except Exception as e:
        return f"Error: couldn't read that file, sir ({_ascii(str(e))})."
    if b"\x00" in data:  # NUL byte -> almost certainly binary, not JSON text
        return (f"Error: '{_ascii(p.name)}' doesn't look like a text file, sir, "
                "so I can't read it as JSON.")

    text = data.decode("utf-8-sig", "replace")  # utf-8-sig strips a BOM if present
    if not text.strip():
        return f"'{_ascii(p.name)}' is empty, sir; there's nothing to read."

    jsonl_hint = suffix in (".jsonl", ".ndjson")
    value = None
    scan_note = ""
    is_jsonl = False

    if jsonl_hint:
        try:
            recs, _scanned, capped = _parse_jsonl(text)
        except (ValueError, RecursionError):
            return (f"Error: '{_ascii(p.name)}' isn't valid JSON Lines, sir; the "
                    "first line doesn't parse.")
        value, is_jsonl = recs, True
        scan_note = " (stopped early; more lines remain)" if capped else ""
    else:
        try:
            value = json.loads(text)
        except RecursionError:
            return (f"Error: '{_ascii(p.name)}' is nested too deeply for me to "
                    "read safely, sir.")
        except ValueError as e:
            # maybe it's actually line-delimited JSON without the extension
            try:
                recs, _scanned, capped = _parse_jsonl(text)
            except (ValueError, RecursionError):
                return (f"Error: '{_ascii(p.name)}' isn't valid JSON, sir "
                        f"({_ascii(str(e))}).")
            if len(recs) < 2:
                return (f"Error: '{_ascii(p.name)}' isn't valid JSON, sir "
                        f"({_ascii(str(e))}).")
            value, is_jsonl = recs, True
            scan_note = " (stopped early; more lines remain)" if capped else ""

    return _summarise(p.name, value, is_jsonl, scan_note)


def _summarise(name: str, value, is_jsonl: bool, scan_note: str) -> str:
    """Build the ASCII summary + preview for a parsed JSON value. Never raises."""
    label = _ascii(name)

    def s(n):
        return "" if n == 1 else "s"

    if is_jsonl:
        n = len(value)
        head = (f"{label} -- JSON Lines with {n} record{s(n)}.{scan_note}")
        if value and isinstance(value[0], dict):
            head += f" Fields of the first record: {_fields_line(value[0])}."
        body = _preview(value[:5] if isinstance(value, list) else value)
        return head + "\nPreview:\n" + body

    if isinstance(value, dict):
        nkeys = len(value)
        head = f"{label} -- an object with {nkeys} field{s(nkeys)}."
        if nkeys:
            head += f" Fields: {_fields_line(value)}."
        return head + "\nPreview:\n" + _preview(value)

    if isinstance(value, list):
        n = len(value)
        head = f"{label} -- an array of {n} item{s(n)}."
        if n:
            if isinstance(value[0], dict):
                head += (f" The items are objects; fields of the first: "
                         f"{_fields_line(value[0])}.")
            else:
                head += f" The first item is a {_typename(value[0])}."
        preview_val = value[:5] if n > 5 else value
        return head + "\nPreview:\n" + _preview(preview_val)

    # a top-level scalar (number, text, true/false, null)
    return (f"{label} -- a single {_typename(value)} value: {_scalar(value)}.")
