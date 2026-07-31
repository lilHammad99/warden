"""Convert a data file between CSV and JSON -- text/data transformation.

The data family so far can READ files (``read_csv`` summarises a CSV/TSV,
``read_json`` a JSON/JSONL, ``read_excel`` an .xlsx) but it could never TRANSFORM
one -- and turning a CSV into JSON (or JSON back into a CSV a person can open in
Excel) is a real, everyday chore an 8B local model cannot do reliably by hand:
it would hallucinate rows, drop fields, or mangle quoting. ``convert_data`` does
it exactly and deterministically. The natural next step after the reading family,
and the partner to ``find_files`` (locate the file, then convert it).

- CSV / TSV  ->  JSON : the first row is the header; each later row becomes a
  JSON object keyed by the column names (an array of objects, or one object per
  line if the output is ``.jsonl``).
- JSON / JSONL  ->  CSV : an array of objects (or a single object, or an array
  of scalars) becomes a spreadsheet -- the columns are the union of the object
  keys, one row per record. Written UTF-8 with a BOM so Excel opens accents
  correctly.

Pure standard library (``csv`` + ``json``) -- NO new dependency.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point this at the wrong file):

- **Rooted in the user's home only.** BOTH the source AND the destination are
  resolved and REJECTED unless they live inside the user's home directory (same
  boundary as ``find_files``), so the model can never read from -- or write into
  -- ``C:\\Windows`` or anywhere outside the user's own folders.
- **Never overwrites.** If something already exists at the destination the
  conversion is REFUSED, so a hallucination can never clobber an existing file;
  and the output can never be the source itself.
- **Atomic write.** The output is written to a ``.part`` temp file and only
  ``os.replace``-d into place once complete, so a crash never leaves a
  half-written file (and a failed write cleans the temp up).
- **Bounded everywhere.** The file on disk, the row count, and the column count
  are all capped and the conversion is REFUSED before writing anything if a cap
  is exceeded -- a giant or hostile file can't exhaust memory, fill the disk, or
  produce a misleading partial file.
- **Never raises.** A binary/Excel file, a non-tabular JSON value, a missing
  file, a folder, an empty file, an unknown output type, the wrong type, an empty
  or missing path -- every one comes back as a friendly, pure-ASCII string the
  model can read and recover from. (The tool's reply is pure ASCII; the WRITTEN
  file keeps the real data, UTF-8.)
"""

import csv
import io
import json
import os
from pathlib import Path

from ..config import HOME
from .find import _coerce
from .jsondata import _load_value
from .organize import _ascii, _first_str, _resolve_under_home, _safe_name
from .registry import tool
from .spreadsheet import _pick_delimiter

MAX_PATH_LEN = 400                    # a path, not an essay
MAX_FILE_BYTES = 25 * 1024 * 1024     # refuse a data file bigger than this
MAX_ROWS = 200_000                    # refuse a file with more data rows than this
MAX_COLS = 2000                       # refuse an absurd number of columns/fields

CSV_EXTS = {".csv", ".tsv", ".tab"}
JSON_EXTS = {".json", ".jsonl", ".ndjson"}


def _fmt(suffix: str) -> str:
    """'csv', 'json', or '' for an unrecognised extension."""
    s = suffix.lower()
    if s in CSV_EXTS:
        return "csv"
    if s in JSON_EXTS:
        return "json"
    return ""


# --- CSV -> JSON --------------------------------------------------------------

def _read_csv_rows(p: Path):
    """Read every row of a CSV/TSV as lists of strings. Returns (rows, "") or
    (None, error_string). Bounded on file size, rows and columns; never raises."""
    name = _ascii(p.name)
    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    if size > MAX_FILE_BYTES:
        return None, f"Error: '{name}' is too large for me to convert safely, sir."
    try:
        data = p.read_bytes()
    except Exception as e:
        return None, f"Error: couldn't read that file, sir ({_ascii(str(e))})."
    if b"\x00" in data:  # NUL byte -> almost certainly binary, not delimited text
        return None, (f"Error: '{name}' doesn't look like a text data file, sir, "
                      "so I can't convert it.")

    text = data.decode("utf-8-sig", "replace")  # utf-8-sig strips a BOM if present
    if not text.strip():
        return None, f"'{name}' is empty, sir; there's nothing to convert."

    delimiter = _pick_delimiter(text[:8192], p.suffix.lower())
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[list[str]] = []
    try:
        for row in reader:
            if len(row) > MAX_COLS:
                return None, (f"Error: '{name}' has too many columns to convert "
                              "safely, sir.")
            rows.append(row)
            if len(rows) > MAX_ROWS + 1:  # +1 for the header row
                return None, (f"Error: '{name}' has too many rows to convert "
                              f"safely, sir (limit {MAX_ROWS}).")
    except csv.Error as e:
        if not rows:
            return None, f"Error: '{name}' isn't valid CSV, sir ({_ascii(str(e))})."
        # a malformed field partway through: keep the rows we managed
    return rows, ""


def _make_header(row) -> list[str]:
    """Turn the first CSV row into unique, non-empty JSON object keys."""
    header: list[str] = []
    seen: dict[str, int] = {}
    for i, cell in enumerate(row[:MAX_COLS]):
        name = (cell or "").strip() or f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        header.append(name)
    return header


def _csv_to_records(rows: list[list[str]]):
    """Rows (header first) -> a list of dict records. Values stay strings (CSV is
    untyped, so we never guess a number and corrupt e.g. a zip code)."""
    header = _make_header(rows[0])
    records = []
    for row in rows[1:]:
        if not any((c or "").strip() for c in row):
            continue  # skip a fully blank row so the count stays honest
        rec = {}
        for i, key in enumerate(header):
            rec[key] = row[i] if i < len(row) else ""
        for j in range(len(header), min(len(row), MAX_COLS)):  # stray extra cells
            rec[f"column_{j + 1}"] = row[j]
        records.append(rec)
    return records


# --- JSON -> CSV --------------------------------------------------------------

def _csv_cell(v) -> str:
    """Render one JSON value for a CSV cell (real data preserved, UTF-8)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    return str(v)


def _json_to_table(value, name: str):
    """Normalise a parsed JSON value into (columns, rows, ""), or (None, None,
    error_string) if it isn't table-shaped. Never raises."""
    if isinstance(value, list):
        records = value
    elif isinstance(value, dict):
        records = [value]
    else:
        return None, None, (f"Error: '{name}' is a single value, not a table of "
                            "records, sir, so I can't turn it into a spreadsheet.")
    if not records:
        return None, None, f"'{name}' has no records to convert, sir."

    columns: list[str] = []
    seen = set()
    has_scalar = False
    for rec in records:
        if isinstance(rec, dict):
            for k in rec.keys():
                ks = str(k)
                if ks not in seen:
                    seen.add(ks)
                    columns.append(ks)
                    if len(columns) > MAX_COLS:
                        return None, None, (f"Error: '{name}' has too many fields "
                                            "to convert safely, sir.")
        else:
            has_scalar = True  # an array of plain values -> a single 'value' column
    if has_scalar and "value" not in seen:
        columns.append("value")
    if not columns:
        columns = ["value"]  # e.g. a list of empty objects

    rows = []
    for rec in records:
        if isinstance(rec, dict):
            rows.append([_csv_cell(rec.get(col, "")) for col in columns])
        else:
            rows.append([_csv_cell(rec) if col == "value" else "" for col in columns])
    return columns, rows, ""


# --- atomic write -------------------------------------------------------------

def _atomic_write(dst: Path, do_write) -> str:
    """Run ``do_write(tmp_path)`` then atomically move it onto ``dst``. Returns ""
    on success or a friendly error string; the temp file is cleaned up on failure.
    Never raises."""
    tmp = dst.with_name(dst.name + ".part")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        do_write(tmp)
        os.replace(str(tmp), str(dst))
    except Exception as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return f"Error: couldn't write the converted file, sir ({_ascii(str(e))})."
    return ""


def _write_json(tmp: Path, records, as_jsonl: bool) -> None:
    if as_jsonl:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False))
                f.write("\n")
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)


def _write_csv(tmp: Path, header, rows, delimiter: str) -> None:
    # utf-8-sig so Excel opens accented text correctly; newline="" per csv docs.
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(header)
        for row in rows:
            w.writerow(row)


# --- the tool -----------------------------------------------------------------

@tool(
    "convert_data",
    "Convert a data file between CSV and JSON. Use this when the user wants to "
    "turn a spreadsheet into JSON or JSON back into a spreadsheet ('convert my "
    "data.csv to json', 'turn this json into a csv so I can open it in Excel', "
    "'export my contacts.json as csv'). Give source (the file to convert; find it "
    "with find_files first if you don't have the path) and optionally dest (a "
    "name or path for the new file). If you omit dest, the same name with the "
    "other extension is used. It never overwrites an existing file, and only the "
    "user's own folders are allowed. This writes a NEW file; the original stays. "
    "For an Excel .xlsx workbook, read it with read_excel instead.",
    {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "The file to convert, e.g. 'Documents/data.csv' or "
                "'Downloads/contacts.json'.",
            },
            "dest": {
                "type": "string",
                "description": "Optional name or path for the converted file, e.g. "
                "'data.json' or 'Documents/contacts.csv'. Its extension (.json / "
                ".csv / .jsonl / .tsv) decides the output format.",
            },
        },
        "required": ["source"],
    },
)
def convert_data(source: str = "", dest: str = "", **extra) -> str:
    src_raw = _first_str(source, extra.get("file"), extra.get("from"),
                         extra.get("path"), extra.get("input"), extra.get("src"),
                         extra.get("filename"), extra.get("source_path"))
    src_raw = _coerce(src_raw, MAX_PATH_LEN)
    if not src_raw:
        return "Error: tell me which file to convert, sir."

    dst_raw = _first_str(dest, extra.get("to"), extra.get("output"),
                         extra.get("destination"), extra.get("target"),
                         extra.get("out"), extra.get("dest_path"),
                         extra.get("new_name"))
    dst_raw = _coerce(dst_raw, MAX_PATH_LEN)
    fmt_hint = _first_str(extra.get("format"), extra.get("to_format"),
                          extra.get("output_format")).lower()

    # resolve + validate the source (inside home, exists, is a file)
    src, err = _resolve_under_home(src_raw)
    if src is None:
        return err or "Error: that file path isn't valid, sir."
    if not src.exists():
        return f"Error: I can't find '{_ascii(str(src))}', sir."
    if src.is_dir():
        return (f"Error: '{_ascii(src.name)}' is a folder, sir; give me a single "
                "CSV or JSON file to convert.")

    ssuf = src.suffix.lower()
    sfmt = _fmt(ssuf)
    if not sfmt:
        if ssuf in (".xlsx", ".xlsm", ".xls"):
            return (f"Error: '{_ascii(src.name)}' is an Excel workbook, sir; read "
                    "it with read_excel, or save it as CSV in Excel first and then "
                    "I can convert it.")
        return (f"Error: I only convert between CSV and JSON, sir, so I can't "
                f"convert '{_ascii(src.name)}'.")

    # work out the target format: an explicit dest extension wins, then a format
    # hint, otherwise just flip to the other format.
    dsuf = Path(dst_raw).suffix.lower() if dst_raw else ""
    if dsuf and _fmt(dsuf) == "":
        return (f"Error: I don't recognise '{_ascii(dsuf)}' as an output type, "
                "sir; name the output .json or .csv.")
    tfmt = _fmt(dsuf)
    if not tfmt:
        if fmt_hint.startswith("json") or fmt_hint == "ndjson":
            tfmt = "json"
        elif fmt_hint.startswith("csv") or fmt_hint in ("tsv", "tab"):
            tfmt = "csv"
        else:
            tfmt = "json" if sfmt == "csv" else "csv"

    if sfmt == tfmt:
        return (f"Error: '{_ascii(src.name)}' is already a {sfmt.upper()} file, "
                "sir; I convert between CSV and JSON.")

    # work out the destination path (kept inside home, never the source, never an
    # existing file).
    default_ext = ".json" if tfmt == "json" else ".csv"
    if dst_raw:
        has_sep = ("/" in dst_raw) or ("\\" in dst_raw)
        if not has_sep and not Path(dst_raw).is_absolute():
            name = _safe_name(dst_raw)          # a bare name -> beside the source
            if not name:
                return "Error: that output name isn't valid, sir."
            if not Path(name).suffix:
                name += default_ext
            dst_path = src.parent / name
        else:
            raw = dst_raw.replace("~", str(HOME))
            dst_path = Path(raw)
            if not dst_path.is_absolute():
                dst_path = Path(HOME) / dst_path
            if not dst_path.suffix:
                dst_path = dst_path.with_suffix(default_ext)
    else:
        dst_path = src.with_suffix(default_ext)

    dst, err = _resolve_under_home(str(dst_path))
    if dst is None:
        return err or "Error: that output path isn't valid, sir."
    if dst == src:
        return ("Error: the output would be the original file, sir; give the new "
                "file a different name.")
    if dst.exists():
        return (f"Error: '{_ascii(str(dst))}' already exists, sir; I won't "
                "overwrite it. Pick another name.")

    as_jsonl = dst.suffix.lower() in (".jsonl", ".ndjson")

    if sfmt == "csv":  # CSV/TSV -> JSON
        rows, rerr = _read_csv_rows(src)
        if rerr:
            return rerr
        if not rows:
            return f"'{_ascii(src.name)}' has no rows to convert, sir."
        records = _csv_to_records(rows)
        werr = _atomic_write(dst, lambda tmp: _write_json(tmp, records, as_jsonl))
        if werr:
            return werr
        n = len(records)
        return (f"Converted {_ascii(src.name)} ({n} row{'s' if n != 1 else ''}) to "
                f"{_ascii(str(dst))} (JSON), sir.")

    # JSON/JSONL -> CSV
    p, value, _is_jsonl, _note, lerr = _load_value(src_raw)
    if lerr:
        return lerr
    header, rows, terr = _json_to_table(value, _ascii(src.name))
    if terr:
        return terr
    if len(rows) > MAX_ROWS:
        return (f"Error: '{_ascii(src.name)}' has too many records to convert "
                f"safely, sir (limit {MAX_ROWS}).")
    delimiter = "\t" if dst.suffix.lower() in (".tsv", ".tab") else ","
    werr = _atomic_write(dst, lambda tmp: _write_csv(tmp, header, rows, delimiter))
    if werr:
        return werr
    n = len(rows)
    return (f"Converted {_ascii(src.name)} ({n} row{'s' if n != 1 else ''}) to "
            f"{_ascii(str(dst))} (CSV), sir.")
