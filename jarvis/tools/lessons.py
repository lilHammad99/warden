"""Earned lessons: Jarvis's own memory of how to do its job better.

This is deliberately a SEPARATE store from long-term memory (``memory.py``):
- facts (memory.json) are about the *user* and their world.
- lessons (lessons.json) are about *how Jarvis should work* -- mistakes to
  avoid, ways the user likes things done.

Keeping them apart means a fact about the user is never confused with a lesson
about the job, and each is shown to the model under its own heading.

Like memory, everything here is defensively validated: an 8B local model can
try to save an empty lesson, dump an essay, loop, pass the wrong type, or wipe
the store. None of that may crash the agent, fill the disk, or corrupt the file
-- bad input comes back as a plain, friendly string the model can recover from.
"""

import json
import threading
from datetime import datetime

from ..config import PROJECT_ROOT
from .registry import tool

_STORE = PROJECT_ROOT / "data" / "lessons.json"
_LOCK = threading.Lock()  # console + voice threads share the store

MAX_LESSONS = 200      # hard cap so a looping model can't fill the disk
MAX_LESSON_LEN = 300   # a lesson is one short imperative, not an essay
MAX_QUERY_LEN = 200
LIST_LIMIT = 20        # most lessons returned / listed in one call


# --------------------------------------------------------------------------
# store I/O — never raises
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
            _STORE.rename(_STORE.with_name("lessons.corrupt.json"))
        except OSError:
            pass
        return []
    if not isinstance(data, list):
        return []
    lessons: list[dict] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"].strip()
            if text:
                lessons.append({"text": text, "ts": str(item.get("ts", ""))})
    return lessons


def _save(lessons: list[dict]) -> None:
    """Atomic write: dump to a temp file then replace, so a crash mid-write
    can't leave a half-written (corrupt) store."""
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_STORE)


def _clean(value, limit: int) -> tuple[str, bool]:
    """Coerce any model-supplied value to a safe, bounded string.
    Returns (text, was_truncated)."""
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        raw = str(value)  # model sometimes passes a number / dict
    raw = raw.replace("\x00", "").strip()
    return raw[:limit], len(raw) > limit


# --------------------------------------------------------------------------
# tools exposed to the model
# --------------------------------------------------------------------------
@tool(
    "learn_lesson",
    "Save one short lesson about how to do your job better, so you improve "
    "over time and still know it after a restart. Use it when you notice a "
    "mistake to avoid, a tool that worked well for a kind of request, or a way "
    "the user likes things done. This is for how YOU work -- use remember for a "
    "fact about the user. One short lesson per call.",
    {
        "type": "object",
        "properties": {
            "lesson": {
                "type": "string",
                "description": "One short lesson, phrased as a reminder to yourself",
            },
        },
        "required": ["lesson"],
    },
)
def learn_lesson(lesson: str = "") -> str:
    text, truncated = _clean(lesson, MAX_LESSON_LEN)
    if not text:
        return "Error: nothing to learn — the 'lesson' was empty, sir."
    with _LOCK:
        lessons = _load()
        for l in lessons:
            if l["text"].lower() == text.lower():
                return f'Already learned: "{text}"'
        if len(lessons) >= MAX_LESSONS:
            return (f"I've learned my limit ({MAX_LESSONS} lessons). Drop one "
                    "first with the forget_lesson tool, sir.")
        lessons.append({"text": text, "ts": datetime.now().strftime("%Y-%m-%d")})
        _save(lessons)
    note = " (shortened to fit)" if truncated else ""
    return f'Learned{note}: "{text}"'


@tool(
    "forget_lesson",
    "Remove a lesson you learned earlier, for when a lesson turns out to be "
    "wrong or no longer useful. Give a few words that identify it. For safety, "
    "if several lessons match, nothing is deleted and the matches are listed so "
    "you can be more specific.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Words identifying the lesson to forget",
            },
        },
        "required": ["query"],
    },
)
def forget_lesson(query: str = "") -> str:
    q, _ = _clean(query, MAX_QUERY_LEN)
    if not q:
        return "Error: tell me which lesson to forget, sir."
    ql = q.lower()
    with _LOCK:
        lessons = _load()
        matches = [l for l in lessons if ql in l["text"].lower()]
        if not matches:
            return f'No lesson matches "{q}", sir.'
        if len(matches) > 1:
            listed = "\n".join(f"- {m['text']}" for m in matches[:LIST_LIMIT])
            return (f'That matches {len(matches)} lessons — please be more '
                    f"specific. Matches:\n{listed}")
        lessons.remove(matches[0])
        _save(lessons)
    return f'Forgotten lesson: "{matches[0]["text"]}"'


# --------------------------------------------------------------------------
# used by the agent (not a tool) to inject learned lessons into the prompt
# --------------------------------------------------------------------------
def count() -> int:
    """Number of stored lessons. Never raises (0 on any error)."""
    try:
        with _LOCK:
            return len(_load())
    except Exception:
        return 0


def lessons_preamble() -> str:
    """A formatted block of learned lessons for the agent's system prompt, so
    the model applies what it has learned. Returns '' when empty; never raises."""
    try:
        with _LOCK:
            lessons = _load()
    except Exception:
        return ""
    if not lessons:
        return ""
    lines = "\n".join(f"- {l['text']}" for l in lessons[-MAX_LESSONS:])
    return ("\n\nLessons you have learned — your own experience about how to do "
            "the job well; apply these:\n" + lines)
