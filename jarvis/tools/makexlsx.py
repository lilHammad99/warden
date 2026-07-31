"""Create a real Excel (.xlsx) workbook for Jarvis.

The third writer, after create_pdf and create_docx: without an Excel WRITER,
"make me a budget spreadsheet" made the model call write_file with a `.xlsx`
name and dump raw text -- a file Excel can't open. `create_xlsx` writes a real
workbook via openpyxl (already a dependency for read_excel).

The model supplies the table as `content`: rows separated by newlines, cells
separated by commas (or tab/semicolon/pipe -- sniffed). The first row is treated
as a bold header. Numeric-looking cells are stored as numbers so Excel can sum
them. Safety mirrors the other file tools: home-containment, bounded, never
raises.
"""

import csv
import io

from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool
from .spreadsheet import _pick_delimiter

MAX_PATH_LEN = 400
MAX_CONTENT = 400000
MAX_ROWS = 20000
MAX_COLS = 200
MAX_CELL = 32000  # Excel's own per-cell character limit is 32767


def _import_openpyxl():
    try:
        from openpyxl import Workbook
        return Workbook
    except Exception:
        return None


def _as_number(cell: str):
    """Turn a plainly numeric cell into an int/float so Excel can sum it;
    otherwise keep it as (bounded) text. Tolerates thousands separators."""
    s = cell.strip()
    if not s:
        return ""
    cleaned = s.replace(",", "")
    try:
        if cleaned.lstrip("-").isdigit():
            return int(cleaned)
        return float(cleaned)
    except ValueError:
        return s[:MAX_CELL]


@tool(
    "create_xlsx",
    "Create a real, openable Excel spreadsheet (.xlsx) and save it. Use this "
    "WHENEVER the user wants a spreadsheet, workbook, or table 'as excel' / 'as "
    "a spreadsheet' / '.xlsx' ('make me a budget spreadsheet', 'put this in "
    "excel', 'create a spreadsheet of ...'). Do NOT use write_file for a .xlsx -- "
    "that produces a file Excel can't open. Give path (e.g. 'Desktop/budget.xlsx') "
    "and content as the table: one row per line, cells separated by commas; the "
    "first row is the header. Only the user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "Where to save it, e.g. 'Desktop/budget.xlsx'."},
            "content": {"type": "string",
                        "description": "The table: one row per line, cells "
                        "comma-separated. First row = column headers."},
            "title": {"type": "string",
                      "description": "Optional sheet name."},
        },
        "required": ["path", "content"],
    },
)
def create_xlsx(path: str = "", content: str = "", title: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("filename"),
                     extra.get("dest"), extra.get("output"), extra.get("name"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me where to save the spreadsheet, sir (e.g. Desktop/budget.xlsx)."

    body = _first_str(content, extra.get("text"), extra.get("body"),
                      extra.get("data"), extra.get("rows"), extra.get("table"))
    if not isinstance(body, str) or not body.strip():
        return ("Error: tell me what to put in the spreadsheet, sir -- rows of "
                "data, one per line, cells separated by commas.")

    p, err = _resolve_under_home(raw)
    if p is None:
        return err or "Error: that spreadsheet path isn't valid, sir."
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    if p.is_dir():
        return f"Error: '{_ascii(p.name)}' is a folder, sir; give me a file name."

    Workbook = _import_openpyxl()
    if Workbook is None:
        return ("Error: I can't make Excel files yet, sir -- the 'openpyxl' "
                "package isn't installed. Install it with: pip install openpyxl")

    body = body[:MAX_CONTENT]
    delim = _pick_delimiter(body[:4096], "")
    try:
        rows = list(csv.reader(io.StringIO(body), delimiter=delim))
    except Exception:
        rows = [line.split(delim) for line in body.splitlines()]
    rows = [r for r in rows if any(c.strip() for c in r)]  # drop blank lines
    if not rows:
        return "Error: I couldn't read any rows out of that, sir."
    if len(rows) > MAX_ROWS:
        rows = rows[:MAX_ROWS]

    try:
        wb = Workbook()
        ws = wb.active
        sheet = _ascii(_coerce(_first_str(title, extra.get("sheet")), 28)).strip()
        if sheet:
            # Excel forbids these characters in a sheet name and caps it at 31
            for ch in r"[]:*?/\\":
                sheet = sheet.replace(ch, " ")
            ws.title = sheet[:31] or "Sheet1"
        for r in rows:
            ws.append([_as_number(str(c)) for c in r[:MAX_COLS]])
        # bold the header row
        try:
            from openpyxl.styles import Font
            for cell in ws[1]:
                cell.font = Font(bold=True)
        except Exception:
            pass
        p.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(p))
    except Exception as e:
        return f"Error: couldn't create that spreadsheet, sir ({_ascii(str(e))})."

    ncols = max((len(r) for r in rows), default=0)
    return (f"Created an Excel spreadsheet ({len(rows)} rows x {ncols} columns) "
            f"at {_ascii(str(p))}.")
