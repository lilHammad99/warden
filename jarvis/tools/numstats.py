"""Summarise a set of numbers for Jarvis -- exact statistics, not a guess.

The 8B local model is genuinely bad at arithmetic over MANY numbers: ask it for
the average, median, or standard deviation of a column of figures and it makes
one up. ``summarize_numbers`` computes the statistics EXACTLY -- how many values,
their sum, average (mean), minimum, maximum, median, range, and standard
deviation -- the way ``calculate`` handles a single expression. A real
accuracy/autonomy win that rounds out the exact-computation family
(``calculate`` for one expression, ``convert_units`` for conversions,
``count_words`` for length) and pairs with ``read_csv`` (locate the sheet, then
average a column).

It works on EITHER numbers passed directly ("average 4, 8, 15, 16, 23, 42")
OR a file: a plain list of numbers (one per line or free text with numbers in
it), or a CSV/TSV where you name the ``column`` to summarise ("what's the
average in the amount column of sales.csv"). The number extractor understands
negatives, decimals, thousands separators (1,234,567) and scientific notation
(6.02e23); anything that is not a number is ignored, not guessed at.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point this at something enormous):

- **Rooted in the user's home only.** A file path is resolved and REJECTED
  unless it lives inside the user's home directory (same boundary as
  ``find_files``), so it can never read a file from ``C:\\Windows``.
- **Bounded everywhere.** Directly-passed text is capped, an over-large file is
  refused before reading (reusing count_words' bounded, binary-sniffed reader),
  and at most 100000 values are used (the rest are ignored with a note), so a
  giant input can't exhaust memory.
- **Pure ASCII out.** Only the computed numbers plus an ASCII-forced file/column
  name are ever returned, so output can never corrupt the console/context.
- **Never raises.** A binary/PDF file, a missing file, a folder, a column that
  isn't there, no numbers at all, the wrong type, an empty or missing argument --
  every one comes back as a friendly, pure-ASCII string the model can recover
  from.
"""

import csv
import math
import re
import statistics
from pathlib import Path

from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool
from .spreadsheet import _pick_delimiter
from .textstats import MAX_PATH_LEN, _looks_like_path, _read_file_text

MAX_INPUT_LEN = 200_000            # cap directly-passed text
MAX_VALUES = 100_000              # most values used in the statistics
MAX_FILE_BYTES = 25 * 1024 * 1024  # refuse a CSV bigger than this (column path)
_CSV_EXT = (".csv", ".tsv", ".tab")

# a number: optional sign, then either grouped-thousands (1,234,567[.89]), a
# plain/decimal number, or a bare fraction (.5), with optional scientific suffix.
_NUM_RE = re.compile(
    r"[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?"
)


def _as_text(value) -> str:
    """Coerce whatever the model passed (str / number / list / None) into a
    single searchable string. A list of numbers becomes space-separated."""
    if value is None:
        return ""
    if isinstance(value, bool):        # avoid True/False sneaking in as 1/0
        return ""
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    if isinstance(value, str):
        return value
    return ""


def _parse_one(token: str):
    """Parse a single regex-matched number token to a finite float, or None."""
    try:
        x = float(token.replace(",", ""))
    except (ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def _extract_numbers(text: str):
    """Find every number in ``text``. Returns (values, truncated)."""
    values = []
    truncated = False
    for m in _NUM_RE.finditer(text):
        x = _parse_one(m.group(0))
        if x is None:
            continue
        values.append(x)
        if len(values) >= MAX_VALUES:
            truncated = True
            break
    return values, truncated


def _column_values(p: Path, suffix: str, column_raw: str):
    """Pull the numeric values of one named/numbered CSV column.
    Returns (values, truncated, error). Never raises."""
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return [], False, (f"Error: '{_ascii(p.name)}' is too large for me to "
                               "summarise safely, sir.")
    except OSError:
        pass
    try:
        data = p.read_bytes()
    except Exception as e:
        return [], False, f"Error: couldn't read that file, sir ({_ascii(str(e))})."
    if b"\x00" in data:
        return [], False, (f"Error: '{_ascii(p.name)}' doesn't look like a data "
                           "file, sir.")
    text = data.decode("utf-8-sig", "replace")
    delim = _pick_delimiter(text[:65536], suffix)
    try:
        rows = list(csv.reader(text.splitlines(), delimiter=delim))
    except csv.Error:
        rows = []
    rows = [r for r in rows if any(c.strip() for c in r)]  # drop blank rows
    if not rows:
        return [], False, (f"Error: '{_ascii(p.name)}' has no rows to summarise, "
                           "sir.")
    header = rows[0]

    # resolve which column: a 1-based number, or a name (case-insensitive)
    idx = None
    col = column_raw.strip()
    if col.isdigit():
        n = int(col)
        if 1 <= n <= len(header):
            idx = n - 1
    if idx is None:
        for i, name in enumerate(header):
            if name.strip().lower() == col.lower():
                idx = i
                break
    if idx is None:
        names = ", ".join(_ascii(h.strip()) for h in header[:20] if h.strip())
        return [], False, (f"Error: I can't find a column called '{_ascii(col)}' "
                           f"in '{_ascii(p.name)}', sir. Columns are: {names}.")

    values = []
    truncated = False
    for row in rows[1:]:
        if idx >= len(row):
            continue
        m = _NUM_RE.search(row[idx])
        if not m:
            continue
        x = _parse_one(m.group(0))
        if x is None:
            continue
        values.append(x)
        if len(values) >= MAX_VALUES:
            truncated = True
            break
    return values, truncated, ""


def _fmt(x: float) -> str:
    """A number formatted as clean, bounded, pure-ASCII text."""
    if x is None or not math.isfinite(x):
        return "n/a"
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x)}"
    return f"{x:.6g}"


def _summary_line(values, label: str, notes) -> str:
    """Build the friendly pure-ASCII statistics sentence."""
    n = len(values)
    total = math.fsum(values)
    mean = total / n
    mn, mx = min(values), max(values)
    med = statistics.median(values)
    sd = statistics.stdev(values) if n >= 2 else None
    sd_txt = _fmt(sd) if sd is not None else "n/a (need 2+ values)"
    plural = "" if n == 1 else "s"
    out = (f"{label}: {n} value{plural}. "
           f"Sum {_fmt(total)}, average {_fmt(mean)}, median {_fmt(med)}, "
           f"min {_fmt(mn)}, max {_fmt(mx)}, range {_fmt(mx - mn)}, "
           f"std dev {sd_txt}.")
    tail = " ".join(t for t in notes if t)
    if tail:
        out += " " + tail
    return _ascii(out)


@tool(
    "summarize_numbers",
    "Compute exact statistics for a set of numbers: how many, their sum, average "
    "(mean), minimum, maximum, median, range, and standard deviation. Use this "
    "whenever the user asks for the average/mean/median/sum/min/max/spread of "
    "several numbers ('what's the average of these', 'sum this list', 'median "
    "sale', 'standard deviation of these figures'); your own arithmetic over many "
    "numbers is unreliable, this is exact. Give numbers with the values (e.g. "
    "'4, 8, 15, 16, 23, 42' or a list), OR path to a file to read them from and, "
    "for a CSV/TSV, column to pick which column (its name or 1-based number). "
    "Only the user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "numbers": {
                "type": "string",
                "description": "The numbers to summarise, e.g. '4, 8, 15, 16, "
                "23, 42'. Separators don't matter (commas, spaces, new lines).",
            },
            "path": {
                "type": "string",
                "description": "A file to read the numbers from instead, e.g. "
                "'Documents/sales.csv' or 'Desktop/scores.txt'.",
            },
            "column": {
                "type": "string",
                "description": "For a CSV/TSV file, which column to summarise: "
                "its name (e.g. 'amount') or 1-based number (e.g. '3').",
            },
        },
        "required": [],
    },
)
def summarize_numbers(numbers="", path="", column="", **extra) -> str:
    # --- gather forgiving inputs (alt arg names + wrong shapes) ---------------
    numbers_raw = ""
    for cand in (numbers, extra.get("values"), extra.get("data"),
                 extra.get("list"), extra.get("nums"), extra.get("text")):
        numbers_raw = _as_text(cand)
        if numbers_raw.strip():
            break

    path_raw = _first_str(path, extra.get("file"), extra.get("source"),
                          extra.get("document"), extra.get("filename"))
    path_raw = _coerce(path_raw, MAX_PATH_LEN)

    column_raw = _first_str(column, extra.get("col"), extra.get("field"),
                            extra.get("header"), extra.get("name"))
    column_raw = _coerce(column_raw, 100)

    # a filename dropped into 'numbers' (a common 8B slip) -> treat it as a file
    if not path_raw and numbers_raw and _looks_like_path(numbers_raw):
        path_raw = _coerce(numbers_raw, MAX_PATH_LEN)
        numbers_raw = ""

    notes = []

    # --- from a file ---------------------------------------------------------
    if path_raw:
        p, err = _resolve_under_home(path_raw)
        if p is None:
            return err or "Error: that file path isn't valid, sir."
        if not p.exists():
            return f"Error: I can't find '{_ascii(str(p))}', sir."
        if p.is_dir():
            return (f"Error: '{_ascii(p.name)}' is a folder, sir; give me a file "
                    "or some numbers to summarise.")
        suffix = p.suffix.lower()
        if suffix in _CSV_EXT and column_raw:
            values, truncated, err = _column_values(p, suffix, column_raw)
            if err:
                return err
            label = f"'{_ascii(p.name)}' column '{_ascii(column_raw)}'"
        else:
            if column_raw and suffix not in _CSV_EXT:
                notes.append("(column only applies to CSV/TSV files, so I read "
                             "all the numbers in the file.)")
            body, err = _read_file_text(p)
            if err:
                return err
            values, truncated = _extract_numbers(body)
            label = f"'{_ascii(p.name)}'"
        if truncated:
            notes.append(f"(used the first {MAX_VALUES} numbers; there were more.)")
        if not values:
            return (f"I couldn't find any numbers in '{_ascii(p.name)}', sir.")
        return _summary_line(values, label, notes)

    # --- from directly-passed text -------------------------------------------
    if not numbers_raw.strip():
        return "Error: give me some numbers or a file to summarise, sir."
    if len(numbers_raw) > MAX_INPUT_LEN:
        numbers_raw = numbers_raw[:MAX_INPUT_LEN]
        notes.append("(read the first part; the rest was too long to take in.)")
    values, truncated = _extract_numbers(numbers_raw)
    if truncated:
        notes.append(f"(used the first {MAX_VALUES} numbers; there were more.)")
    if not values:
        return ("I couldn't find any numbers to summarise in that, sir.")
    return _summary_line(values, "Those numbers", notes)
