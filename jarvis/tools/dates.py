"""Date & time calculator for Jarvis.

An 8B local model is unreliable at calendar arithmetic - ask it "how many days
until Christmas", "what day of the week is 2026-12-25", or "what's the date 90
days from now" and it will confidently miscount. This gives Jarvis real,
exact date math so it can answer deadline / birthday / scheduling questions
instead of guessing. It complements the ``calculate`` tool (numbers) with the
same promise: exact answers, never a crash.

Tools:
- ``today`` - the current date, weekday and time (so the model never has to
  guess "what is today").
- ``weekday`` - the day of the week a given date falls on.
- ``days_until`` - signed distance in days from today to a date (deadlines,
  birthdays, "how long until ...").
- ``days_between`` - the number of days between two dates.
- ``date_add`` - the date a number of days/weeks (+/-) from a base date.

Safety model (strict, because the 8B model WILL eventually pass junk):

- **Unambiguous parsing only.** Dates are accepted as ISO ``YYYY-MM-DD`` (the
  documented form) plus month-name forms like "December 25 2026" and the words
  today/tomorrow/yesterday. Ambiguous ``m/d`` vs ``d/m`` slash dates are NOT
  guessed - the model is told to use ``YYYY-MM-DD``.
- **Sizes are bounded.** Input length and numeric offsets are capped, so a
  hallucinated ``date_add(days=99999999999)`` can't overflow or hang; it comes
  back as a friendly out-of-range message.
- **Never raises.** Wrong types are coerced, and every bad input (unparseable
  date, out-of-range year, overflow) returns a plain ASCII message the model
  can read and recover from.
"""

from datetime import date, datetime, timedelta

from .registry import tool

MAX_TEXT_LEN = 40          # a date string, not a paragraph
MAX_OFFSET = 3_000_000     # ~8200 years; keeps us inside datetime's range

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]

# Unambiguous formats only. ISO first, then month-name variants (with and
# without a year). Deliberately NO bare m/d/Y or d/m/Y - too ambiguous for a
# hallucinating model to get right.
_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%B %d %Y", "%B %d, %Y", "%d %B %Y",
    "%b %d %Y", "%b %d, %Y", "%d %b %Y",
    "%B %d", "%b %d", "%d %B", "%d %b",
]
_NO_YEAR = {"%B %d", "%b %d", "%d %B", "%d %b"}


def _coerce(value) -> str:
    """Any model-supplied value -> a bounded, cleaned string."""
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        raw = str(value)
    return raw.replace("\x00", "").strip().strip("`").strip()


def _parse_date(text: str) -> date:
    """Parse a date string to a ``date``. Raises ValueError (friendly message)
    on anything unrecognised. Never returns None."""
    s = _coerce(text)
    if not s:
        raise ValueError("no date was given")
    if len(s) > MAX_TEXT_LEN:
        raise ValueError("that date text is too long")

    low = s.lower()
    if low in ("today", "now", "tonight"):
        return date.today()
    if low in ("tomorrow", "tmr", "tmrw"):
        return date.today() + timedelta(days=1)
    if low == "yesterday":
        return date.today() - timedelta(days=1)

    # normalise commas/whitespace a little for the strptime attempts
    cleaned = " ".join(s.replace(",", " ").split())
    for fmt in _FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if fmt in _NO_YEAR:
            dt = dt.replace(year=date.today().year)
        return dt.date()

    raise ValueError(
        f'I could not read "{s}" as a date, sir. Try YYYY-MM-DD, e.g. 2026-12-25'
    )


def _coerce_int(value) -> int:
    """Any model-supplied value -> an int. Raises ValueError on junk."""
    if isinstance(value, bool):  # bool is an int subclass; treat as junk
        raise ValueError("expected a number of days")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("that is not a whole number")
        return int(value)
    s = _coerce(value)
    if not s:
        raise ValueError("no number was given")
    try:
        return int(s)
    except ValueError:
        # allow "3.0" style floats the model might pass as text
        try:
            f = float(s)
        except ValueError:
            raise ValueError(f'"{s}" is not a whole number of days')
        return int(f)


def _describe(d: date) -> str:
    """'Friday, 25 December 2026' (pure ASCII)."""
    return f"{_WEEKDAYS[d.weekday()]}, {d.day} {d.strftime('%B')} {d.year}"


# --------------------------------------------------------------------------
# tools exposed to the model
# --------------------------------------------------------------------------
@tool(
    "today",
    "Return today's date, the current day of the week and the current time. "
    "USE this whenever you need to know what today is (for anything time- or "
    "date-related) instead of guessing, because your own idea of the date may "
    "be wrong.",
    {"type": "object", "properties": {}, "required": []},
)
def today() -> str:
    now = datetime.now()
    return (f"Today is {_describe(now.date())}. "
            f"The time is {now.strftime('%I:%M %p').lstrip('0')}.")


@tool(
    "weekday",
    "Return the day of the week (Monday..Sunday) for a given date. Use for "
    "'what day is 2026-12-25?' or 'what day of the week is my birthday?'. Give "
    "the date as YYYY-MM-DD (or a month name like 'December 25 2026').",
    {
        "type": "object",
        "properties": {
            "date": {"type": "string",
                     "description": "A date, e.g. '2026-12-25' or 'December 25 2026'"},
        },
        "required": ["date"],
    },
)
def weekday(date: str = "") -> str:
    try:
        d = _parse_date(date)
    except ValueError as e:
        return f"Error: {e}, sir."
    return f"{_describe(d)} is a {_WEEKDAYS[d.weekday()]}, sir."


@tool(
    "days_until",
    "Return how many days from today until a given date (deadlines, birthdays, "
    "'how long until ...'). Positive means it is in the future, negative means "
    "it has already passed. Give the date as YYYY-MM-DD (or a month name).",
    {
        "type": "object",
        "properties": {
            "date": {"type": "string",
                     "description": "The target date, e.g. '2026-12-25'"},
        },
        "required": ["date"],
    },
)
def days_until(date: str = "") -> str:
    try:
        d = _parse_date(date)
    except ValueError as e:
        return f"Error: {e}, sir."
    delta = (d - datetime.now().date()).days
    if delta == 0:
        return f"That is today, sir ({_describe(d)})."
    if delta > 0:
        return (f"{delta} day{'s' if delta != 1 else ''} until {_describe(d)}, sir.")
    n = -delta
    return f"{_describe(d)} was {n} day{'s' if n != 1 else ''} ago, sir."


@tool(
    "days_between",
    "Return the number of days between two dates. Use for 'how many days "
    "between 2026-01-01 and 2026-07-30?' or working out an age/duration. Give "
    "both dates as YYYY-MM-DD (or month names).",
    {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "The earlier date"},
            "end": {"type": "string", "description": "The later date"},
        },
        "required": ["start", "end"],
    },
)
def days_between(start: str = "", end: str = "") -> str:
    try:
        a = _parse_date(start)
        b = _parse_date(end)
    except ValueError as e:
        return f"Error: {e}, sir."
    n = abs((b - a).days)
    return (f"{n} day{'s' if n != 1 else ''} between {_describe(a)} "
            f"and {_describe(b)}, sir.")


@tool(
    "date_add",
    "Return the date a number of days from a starting date. Use for 'what's the "
    "date 90 days from now?' or '3 weeks after 2026-01-01'. Positive days go "
    "forward, negative go back. If no base date is given, today is used. Pass "
    "weeks as a shortcut for 7-day steps.",
    {
        "type": "object",
        "properties": {
            "days": {"type": "integer",
                     "description": "Number of days to add (negative to go back)"},
            "weeks": {"type": "integer",
                      "description": "Optional number of weeks to add (7 days each)"},
            "base": {"type": "string",
                     "description": "Optional start date (YYYY-MM-DD); defaults to today"},
        },
        "required": [],
    },
)
def date_add(days=0, weeks=0, base: str = "") -> str:
    try:
        d0 = _parse_date(base) if _coerce(base) else datetime.now().date()
    except ValueError as e:
        return f"Error: {e}, sir."
    try:
        nd = _coerce_int(days) if days not in (None, "") else 0
        nw = _coerce_int(weeks) if weeks not in (None, "") else 0
    except ValueError as e:
        return f"Error: {e}, sir."
    total = nd + nw * 7
    if abs(total) > MAX_OFFSET:
        return (f"Error: that offset is too large, sir (limit "
                f"{MAX_OFFSET:,} days).")
    if total == 0:
        return f"That is {_describe(d0)}, sir."
    try:
        result = d0 + timedelta(days=total)
    except (OverflowError, ValueError):
        return "Error: that date is outside the calendar range, sir."
    direction = "after" if total > 0 else "before"
    n = abs(total)
    return (f"{n} day{'s' if n != 1 else ''} {direction} {_describe(d0)} "
            f"is {_describe(result)}, sir.")
