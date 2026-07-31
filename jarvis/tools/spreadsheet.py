"""Read / summarise CSV & TSV data files for Jarvis -- structured-data handling.

``read_file`` dumps a spreadsheet's raw bytes and ``read_document`` only handles
Word/OpenDocument prose, so when the user points Jarvis at a data file ("how
many rows are in my sales data", "what columns are in this spreadsheet",
"summarise my CSV", "show me the first few rows of expenses.csv") the model is
left to eyeball and guess -- and an 8B model is hopeless at counting rows or
columns exactly. ``read_csv`` measures the file EXACTLY: how many data rows,
how many columns, the column names, and a small preview of the first rows -- the
way ``calculate`` handles arithmetic and ``count_words`` handles length. A real
accuracy/autonomy win, and the natural partner to ``find_files`` (locate the
spreadsheet, then read it).

Pure standard library: a CSV/TSV is plain text, so ``csv`` is all it takes -- NO
new dependency. Excel ``.xlsx`` is a binary format and is steered to "export to
CSV" rather than read as garbage.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point this at something enormous):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless
  it lives inside the user's home directory (same boundary as ``find_files``),
  so the model can never read a data file from ``C:\\Windows``.
- **Bounded everywhere.** The file on disk is capped before reading, the row
  scan is capped (a huge sheet stops early with a note), the CSV field-size
  limit is clamped, and every listed column name / preview cell is truncated --
  a giant or hostile file can't exhaust memory or flood the agent's context.
- **Pure ASCII out.** Column names and cell values are forced to single-line
  ASCII, so the summary can never corrupt the console/context.
- **Never raises.** A binary/Excel/PDF file, a missing file, a folder, an empty
  file, a malformed row, the wrong type, an empty or missing path -- every one
  comes back as a friendly, pure-ASCII string the model can read and recover
  from.
"""

import csv
import io
from pathlib import Path

from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400                    # a path, not an essay
MAX_FILE_BYTES = 25 * 1024 * 1024     # refuse a data file bigger than this
MAX_ROWS = 200_000                    # most rows scanned before stopping (with a note)
MAX_FIELD_BYTES = 1024 * 1024         # clamp csv's field-size limit (a lying row can't blow up)
DEFAULT_PREVIEW = 5                   # preview rows shown by default
MAX_PREVIEW_ROWS = 20                 # most preview rows the model may ask for
MAX_COLS_LISTED = 40                  # most column names listed
MAX_CELL = 40                         # truncate any single cell value to this
MAX_COLS_SCAN = 1000                  # ignore absurd column counts in a row

# clamp csv's global field-size limit so one hostile mega-field can't exhaust
# memory (the default is already ~128 KB, but be explicit and defensive).
try:
    csv.field_size_limit(MAX_FIELD_BYTES)
except (OverflowError, ValueError):
    pass

# file types that clearly are NOT delimited text -- steer rather than parse the
# binary garbage that decoding their bytes would produce.
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif", ".tiff",
    ".zip", ".gz", ".7z", ".rar", ".tar", ".exe", ".dll", ".msi", ".bin",
    ".mp3", ".wav", ".mp4", ".mov", ".avi", ".mkv", ".ttf", ".otf", ".woff",
    ".docx", ".odt", ".doc", ".pptx", ".ppt",
}


def _cell(value: str) -> str:
    """One CSV cell, forced to safe single-line ASCII and truncated."""
    v = _ascii(value).strip()
    if len(v) > MAX_CELL:
        v = v[:MAX_CELL - 3] + "..."
    return v


def _preview_int(value) -> int:
    """Coerce the optional 'rows' preview count into 0..MAX_PREVIEW_ROWS."""
    s = _coerce(value, 12)
    if not s:
        return DEFAULT_PREVIEW
    digits = "".join(ch for ch in s if ch.isdigit())  # tolerate "5 rows"
    if not digits:
        return DEFAULT_PREVIEW
    try:
        n = int(digits)
    except ValueError:
        return DEFAULT_PREVIEW
    if n < 0:
        return DEFAULT_PREVIEW
    return min(n, MAX_PREVIEW_ROWS)


def _pick_delimiter(sample: str, suffix: str) -> str:
    """Best-guess field delimiter: tab for .tsv/.tab, otherwise sniff a small
    sample, falling back to a comma. Never raises."""
    if suffix in (".tsv", ".tab"):
        return "\t"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        # count candidate separators on the first line as a cheap fallback
        first = sample.splitlines()[0] if sample.splitlines() else ""
        best = max(",;\t|", key=lambda d: first.count(d))
        return best if first.count(best) else ","


@tool(
    "read_csv",
    "Read and summarise a CSV or TSV spreadsheet / data file: reports how many "
    "rows of data and columns it has, the column names, and a preview of the "
    "first rows. Use this whenever the user asks about a .csv or .tsv file ('how "
    "many rows are in my data', 'what columns are in this spreadsheet', "
    "'summarise my csv', 'show me the first few rows'); read_file only dumps raw "
    "text and your own counting is unreliable, this is exact. Give path (locate "
    "it first with find_files if you don't have it) and optionally rows (how many "
    "preview rows to show). Only the user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The data file to read, e.g. 'Documents/sales.csv'.",
            },
            "rows": {
                "type": "integer",
                "description": "How many preview rows to show (default 5).",
            },
        },
        "required": ["path"],
    },
)
def read_csv(path: str = "", rows=None, **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("document"),
                     extra.get("source"), extra.get("name"),
                     extra.get("filename"), extra.get("spreadsheet"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me which CSV or data file to read, sir."

    want = _preview_int(rows if rows is not None else extra.get("preview"))

    p, err = _resolve_under_home(raw)
    if p is None:
        return err or "Error: that file path isn't valid, sir."
    if not p.exists():
        return f"Error: I can't find '{_ascii(str(p))}', sir."
    if p.is_dir():
        return (f"Error: '{_ascii(p.name)}' is a folder, sir; give me a CSV or "
                "data file to read.")

    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return (f"Error: '{_ascii(p.name)}' is an Excel workbook, sir; use "
                "read_excel for that. read_csv is for .csv/.tsv text files.")
    if suffix == ".xls":
        return (f"Error: '{_ascii(p.name)}' is an old Excel file, sir; open it "
                "in Excel and save it as .xlsx (then use read_excel) or as CSV.")
    if suffix == ".pdf":
        return "Error: that's a PDF, sir; I can't read those yet."
    if suffix in _BINARY_EXT:
        return (f"Error: '{_ascii(p.name)}' isn't a text data file, sir, so I "
                "can't read it as a spreadsheet.")

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
    if b"\x00" in data:  # NUL byte -> almost certainly binary, not delimited text
        return (f"Error: '{_ascii(p.name)}' doesn't look like a text data file, "
                "sir, so I can't read it as a spreadsheet.")

    text = data.decode("utf-8-sig", "replace")  # utf-8-sig strips a BOM if present
    if not text.strip():
        return f"'{_ascii(p.name)}' is empty, sir; there's nothing to read."

    delimiter = _pick_delimiter(text[:8192], suffix)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    header: list[str] = []
    preview: list[list[str]] = []
    data_rows = 0
    scanned = 0
    capped = False
    try:
        for row in reader:
            scanned += 1
            if scanned > MAX_ROWS:
                capped = True
                break
            if not header:
                header = [_cell(c) for c in row[:MAX_COLS_SCAN]]
                continue
            # skip a fully blank trailing/interior row so counts stay honest
            if not any(cell.strip() for cell in row):
                continue
            data_rows += 1
            if len(preview) < want:
                preview.append([_cell(c) for c in row[:MAX_COLS_SCAN]])
    except csv.Error as e:
        # a malformed field: report what we managed rather than crashing
        if not header:
            return (f"Error: '{_ascii(p.name)}' isn't valid CSV, sir "
                    f"({_ascii(str(e))}).")

    if not header:
        return f"'{_ascii(p.name)}' has no readable rows, sir."

    ncols = len(header)
    delim_name = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}.get(
        delimiter, "delimiter")

    def s(n):
        return "" if n == 1 else "s"

    shown_cols = header[:MAX_COLS_LISTED]
    cols_note = "" if ncols <= MAX_COLS_LISTED else f" (+{ncols - MAX_COLS_LISTED} more)"
    row_note = " (stopped early; more rows remain)" if capped else ""

    head = (f"{_ascii(p.name)} -- {data_rows} data row{s(data_rows)}, "
            f"{ncols} column{s(ncols)} ({delim_name}-separated).{row_note} "
            f"Columns: {', '.join(shown_cols)}{cols_note}.")

    if not preview:
        return head + " No data rows to preview."

    lines = [head, f"First {len(preview)} row{s(len(preview))}:"]
    for i, row in enumerate(preview, 1):
        lines.append(f"{i}: " + " | ".join(row))
    return "\n".join(lines)
