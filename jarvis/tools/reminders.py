"""Reminders / timers for Jarvis.

The biggest autonomy win yet: instead of only reacting to a command, Jarvis
can act on its OWN, later, without being asked again. The user says "remind me
in 10 minutes to check the oven" or "remind me at 17:30 to call mum", and
Jarvis speaks up when the time comes -- across the whole session. Pending
reminders persist across restarts in ``data/reminders.json`` and are injected
into the agent's system prompt so Jarvis stays aware of them.

The firing itself is driven by ``due_reminders(now)`` -- a small, pure function
the app's background thread polls. It is deliberately testable without any
model or real waiting: pass a ``now`` in the future and it returns (and marks
fired) whatever is due, so the smoke test is fully deterministic.

Everything is defensively validated because an 8B local model WILL hallucinate:
it may set an empty reminder, dump an essay, pass ``minutes`` as a string or a
negative/absurd number, give an ambiguous time, or point ``cancel_reminder`` at
nothing. None of that may crash the agent, fill the disk, or corrupt the store
-- bad input comes back as a plain, friendly, pure-ASCII string the model can
read and recover from.
"""

import json
import threading
from datetime import datetime, timedelta

from ..config import PROJECT_ROOT
from .registry import tool

_STORE = PROJECT_ROOT / "data" / "reminders.json"
_LOCK = threading.Lock()  # console + voice + background poller share the store

MAX_REMINDERS = 100          # hard cap so a looping model can't fill the disk
MAX_TEXT_LEN = 300           # a reminder is a short line, not an essay
MAX_QUERY_LEN = 200
MAX_MINUTES = 60 * 24 * 366  # ~a year: refuse absurd offsets (1e12 etc.)
LIST_LIMIT = 50

# Unambiguous absolute-time formats only. Ambiguous slash dates (m/d vs d/m)
# are intentionally NOT accepted -- we refuse rather than guess.
_TIME_FORMATS = ("%H:%M", "%I:%M %p", "%I %p")
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I %p",
)


# --------------------------------------------------------------------------
# store I/O -- never raises
# --------------------------------------------------------------------------
def _load() -> list[dict]:
    """Read the store. A missing file is empty; a corrupt one is set aside
    (renamed) so nothing is silently overwritten, and we start fresh."""
    if not _STORE.exists():
        return []
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError, UnicodeError):
        try:
            _STORE.rename(_STORE.with_name("reminders.corrupt.json"))
        except OSError:
            pass
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        due = item.get("due")
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(due, str) or _parse_iso(due) is None:
            continue
        out.append({
            "text": text.strip(),
            "due": due,
            "created": str(item.get("created", "")),
            "fired": bool(item.get("fired", False)),
        })
    return out


def _save(items: list[dict]) -> None:
    """Atomic write: dump to a temp file then replace, so a crash mid-write
    can't leave a half-written (corrupt) store."""
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_STORE)


def _parse_iso(value: str):
    """Parse an ISO datetime we wrote ourselves. Returns datetime or None."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _clean(value, limit: int) -> tuple[str, bool]:
    """Coerce any model-supplied value to a safe, bounded string.
    Returns (text, was_truncated)."""
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        raw = str(value)  # model sometimes passes a number / dict / list
    raw = raw.replace("\x00", "").strip()
    return raw[:limit], len(raw) > limit


def _coerce_minutes(value):
    """Coerce ``minutes`` to a positive float within bounds.
    Returns (minutes, error). Rejects wrong types, non-finite, <=0, and absurd
    values so ``minutes=1e12`` or ``minutes='soon'`` can't overflow or hang."""
    if value is None:
        return None, "no delay given"
    if isinstance(value, bool):  # bool is an int subclass -- reject it
        return None, "the delay must be a number of minutes"
    try:
        m = float(value)
    except (ValueError, TypeError):
        return None, "the delay must be a number of minutes"
    if m != m or m in (float("inf"), float("-inf")):
        return None, "the delay must be a real number of minutes"
    if m <= 0:
        return None, "the delay must be more than zero minutes"
    if m > MAX_MINUTES:
        return None, "that delay is too far in the future"
    return m, ""


def _parse_when(minutes, at, now: datetime):
    """Work out the absolute due time from EITHER a relative ``minutes`` offset
    OR an absolute ``at`` time string. Exactly one must be supplied.
    Returns (due_datetime, error_string)."""
    has_min = minutes is not None and not (isinstance(minutes, str) and not minutes.strip())
    at_text, _ = _clean(at, 40)
    has_at = bool(at_text)

    if has_min and has_at:
        return None, ("give me EITHER a delay in minutes OR a clock time, sir, "
                      "not both")
    if not has_min and not has_at:
        return None, ("tell me when, sir -- either in how many minutes, or at "
                      "what time")

    if has_min:
        m, err = _coerce_minutes(minutes)
        if err:
            return None, err
        return now + timedelta(minutes=m), ""

    # absolute time. Try full datetime formats first, then time-only.
    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(at_text, fmt)
            if dt < now:
                return None, "that time is already in the past, sir"
            return dt, ""
        except ValueError:
            pass
    for fmt in _TIME_FORMATS:
        try:
            t = datetime.strptime(at_text.upper() if "%p" in fmt else at_text, fmt)
        except ValueError:
            continue
        dt = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if dt <= now:                       # time already passed today
            dt = dt + timedelta(days=1)     # -> the same time tomorrow
        return dt, ""
    return None, (f'I could not read "{at_text}" as a time, sir -- try "17:30" '
                  'or "2026-12-25 09:00"')


def _describe_due(due: datetime, now: datetime) -> str:
    """Human, pure-ASCII 'in 10 minutes' / 'tomorrow at 09:00' style phrase."""
    delta = due - now
    secs = delta.total_seconds()
    if secs < 0:
        return "now"
    mins = int(round(secs / 60.0))
    if mins < 60:
        return f"in {mins} minute{'s' if mins != 1 else ''}"
    hours = secs / 3600.0
    if due.date() == now.date():
        return f"at {due.strftime('%H:%M')} today"
    if due.date() == (now + timedelta(days=1)).date():
        return f"at {due.strftime('%H:%M')} tomorrow"
    if hours < 24 * 7:
        return f"on {due.strftime('%A')} at {due.strftime('%H:%M')}"
    return f"on {due.strftime('%Y-%m-%d')} at {due.strftime('%H:%M')}"


def _pending(items: list[dict]) -> list[dict]:
    """Not-yet-fired reminders, soonest first."""
    p = [r for r in items if not r["fired"]]
    p.sort(key=lambda r: r["due"])
    return p


# --------------------------------------------------------------------------
# tools exposed to the model
# --------------------------------------------------------------------------
@tool(
    "set_reminder",
    "Set a reminder so you (Jarvis) tell the user something later, all on your "
    "own. Use when the user says 'remind me to ...', 'in N minutes ...', 'set "
    "a timer for ...', or 'at HH:MM ...'. Give EITHER minutes (a number, for a "
    "relative delay) OR at (a clock time like '17:30' or a date-time like "
    "'2026-12-25 09:00'), never both.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string",
                      "description": "What to remind the user about"},
            "minutes": {"type": "number",
                        "description": "Remind this many minutes from now"},
            "at": {"type": "string",
                   "description": "Absolute time, e.g. '17:30' or "
                                  "'2026-12-25 09:00' (24-hour, unambiguous)"},
        },
        "required": ["text"],
    },
)
def set_reminder(text: str = "", minutes=None, at=None) -> str:
    body, truncated = _clean(text, MAX_TEXT_LEN)
    if not body:
        return "Error: what should I remind you about, sir?"
    now = datetime.now()
    due, err = _parse_when(minutes, at, now)
    if err:
        return f"Error: {err}."
    with _LOCK:
        items = _load()
        if len(_pending(items)) >= MAX_REMINDERS:
            return (f"You already have {MAX_REMINDERS} reminders pending, sir. "
                    "Let some fire or cancel one first.")
        items.append({
            "text": body,
            "due": due.isoformat(timespec="minutes"),
            "created": now.isoformat(timespec="minutes"),
            "fired": False,
        })
        _save(items)
        pend = len(_pending(items))
    note = " (shortened to fit)" if truncated else ""
    return (f'Reminder set{note}: "{body}" {_describe_due(due, now)}. '
            f"You have {pend} reminder{'s' if pend != 1 else ''} pending, sir.")


@tool(
    "list_reminders",
    "Show the user's pending reminders and when each will fire. Use when they "
    "ask 'what reminders do I have?', 'what are my timers?', or 'when will you "
    "remind me?'.",
    {"type": "object", "properties": {}, "required": []},
)
def list_reminders() -> str:
    now = datetime.now()
    with _LOCK:
        pend = _pending(_load())
    if not pend:
        return "You have no reminders pending, sir."
    lines = []
    for i, r in enumerate(pend[:LIST_LIMIT], 1):
        due = _parse_iso(r["due"]) or now
        lines.append(f"{i}. {r['text']} -- {_describe_due(due, now)}")
    if len(pend) > LIST_LIMIT:
        lines.append(f"...(and {len(pend) - LIST_LIMIT} more)")
    n = len(pend)
    head = f"You have {n} reminder{'s' if n != 1 else ''} pending, sir:"
    return head + "\n" + "\n".join(lines)


@tool(
    "cancel_reminder",
    "Cancel a pending reminder. Give a few words that identify it, or the "
    "number shown by list_reminders. For safety, if several match, nothing is "
    "cancelled and the matches are listed.",
    {
        "type": "object",
        "properties": {
            "which": {"type": "string",
                      "description": "Words identifying the reminder, or its "
                                     "list number"},
        },
        "required": ["which"],
    },
)
def cancel_reminder(which: str = "") -> str:
    q, _ = _clean(which, MAX_QUERY_LEN)
    if not q:
        return "Error: tell me which reminder to cancel, sir."
    now = datetime.now()
    with _LOCK:
        items = _load()
        pend = _pending(items)
        if not pend:
            return "You have no reminders to cancel, sir."
        if q.isdigit():
            n = int(q)
            if not (1 <= n <= len(pend)):
                return f"Sorry sir, there is no reminder number {n}."
            matches = [pend[n - 1]]
        else:
            ql = q.lower()
            matches = [r for r in pend if ql in r["text"].lower()]
        if not matches:
            return f'Nothing pending matches "{q}", sir.'
        if len(matches) > 1:
            listed = "\n".join(f"{i}. {r['text']} -- "
                               f"{_describe_due(_parse_iso(r['due']) or now, now)}"
                               for i, r in enumerate(matches, 1))
            return (f"That matches {len(matches)} reminders, sir -- please be "
                    f"more specific:\n{listed}")
        items.remove(matches[0])
        _save(items)
        left = len(_pending(items))
    return (f'Cancelled: "{matches[0]["text"]}". '
            f"{left} reminder{'s' if left != 1 else ''} left, sir.")


# --------------------------------------------------------------------------
# used by the app / agent (not tools) -- never raise
# --------------------------------------------------------------------------
def due_reminders(now: datetime | None = None) -> list[str]:
    """Return the texts of every reminder due at ``now`` (default: real now),
    marking them fired and saving. This is what the background poller calls to
    fire reminders, and what the smoke test drives with a future ``now`` so it
    is fully deterministic. Never raises."""
    if now is None:
        now = datetime.now()
    try:
        with _LOCK:
            items = _load()
            fired_texts = []
            changed = False
            for r in items:
                if r["fired"]:
                    continue
                due = _parse_iso(r["due"])
                if due is not None and due <= now:
                    r["fired"] = True
                    fired_texts.append(r["text"])
                    changed = True
            if changed:
                # keep the store small: drop already-fired reminders once seen
                _save([r for r in items if not r["fired"]])
            return fired_texts
    except Exception:
        return []


def pending_count() -> int:
    """Number of not-yet-fired reminders. Never raises (0 on any error)."""
    try:
        with _LOCK:
            return len(_pending(_load()))
    except Exception:
        return 0


def next_due_phrase() -> str:
    """Short phrase for the soonest pending reminder ('next in 8 minutes'), or
    '' if none. Pure ASCII; never raises."""
    try:
        now = datetime.now()
        with _LOCK:
            pend = _pending(_load())
        if not pend:
            return ""
        due = _parse_iso(pend[0]["due"]) or now
        return "next " + _describe_due(due, now)
    except Exception:
        return ""


def reminders_preamble() -> str:
    """A formatted block of pending reminders for the agent's system prompt, so
    Jarvis is aware of them. '' when empty; never raises."""
    try:
        now = datetime.now()
        with _LOCK:
            pend = _pending(_load())[:LIST_LIMIT]
    except Exception:
        return ""
    if not pend:
        return ""
    lines = "\n".join(f"- {r['text']} ({_describe_due(_parse_iso(r['due']) or now, now)})"
                      for r in pend)
    return ("\n\nThe user's pending reminders (you will announce these yourself "
            "when due -- do not set duplicates):\n" + lines)
