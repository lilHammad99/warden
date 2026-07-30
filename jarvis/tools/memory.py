"""Persistent long-term memory for Jarvis.

Lets the model remember durable facts across restarts, backed by a small
JSON file at ``data/memory.json``. This is what makes the assistant feel
continuous — it still knows the user's name, preferences and where things
are after the process is closed and reopened.

Everything here is defensively validated on purpose: an 8B local model can
hallucinate. It may try to save an empty fact, dump an entire essay as a
"fact", call ``remember`` in a loop, pass the wrong argument type, or delete
the whole store. None of that is allowed to crash the agent, fill the disk,
or corrupt the file — bad input comes back as a plain, friendly error string
the model can read and recover from.
"""

import json
import threading
from datetime import datetime

from ..config import PROJECT_ROOT
from .registry import tool

_STORE = PROJECT_ROOT / "data" / "memory.json"
_LOCK = threading.Lock()  # console + voice threads share the store

MAX_FACTS = 200       # hard cap so a looping model can't fill the disk
MAX_FACT_LEN = 500    # a "fact" is a sentence, not an essay dump
MAX_QUERY_LEN = 200
RECALL_LIMIT = 20     # most facts returned / listed in one call


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
            _STORE.rename(_STORE.with_name("memory.corrupt.json"))
        except OSError:
            pass
        return []
    if not isinstance(data, list):
        return []
    facts: list[dict] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"].strip()
            if text:
                facts.append({"text": text, "ts": str(item.get("ts", ""))})
    return facts


def _save(facts: list[dict]) -> None:
    """Atomic write: dump to a temp file then replace, so a crash mid-write
    can't leave a half-written (corrupt) store."""
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
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
    "remember",
    "Save one important, durable fact about the user or their world to "
    "long-term memory so you still know it after a restart. Use it when the "
    "user tells you to remember something, or shares a lasting preference, "
    "name, schedule, or where something is. One short fact per call.",
    {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "One short fact to remember"},
        },
        "required": ["fact"],
    },
)
def remember(fact: str = "") -> str:
    text, truncated = _clean(fact, MAX_FACT_LEN)
    if not text:
        return "Error: nothing to remember — the 'fact' was empty, sir."
    with _LOCK:
        facts = _load()
        for f in facts:
            if f["text"].lower() == text.lower():
                return f'Already in memory: "{text}"'
        if len(facts) >= MAX_FACTS:
            return (f"My memory is full ({MAX_FACTS} facts). Forget something "
                    "first with the forget tool, sir.")
        facts.append({"text": text, "ts": datetime.now().strftime("%Y-%m-%d")})
        _save(facts)
    note = " (shortened to fit)" if truncated else ""
    return f'Remembered{note}: "{text}"'


@tool(
    "recall",
    "Search your long-term memory for facts you saved earlier. Give a short "
    "query of a word or two, or leave it empty to list everything you "
    "remember. Use this when the user refers to something from before.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for (optional)"},
        },
        "required": [],
    },
)
def recall(query: str = "") -> str:
    q, _ = _clean(query, MAX_QUERY_LEN)
    with _LOCK:
        facts = _load()
    if not facts:
        return "I have nothing in long-term memory yet, sir."
    if not q:
        chosen = facts[-RECALL_LIMIT:]
        body = "\n".join(f"- {f['text']}" for f in chosen)
        more = "" if len(facts) <= RECALL_LIMIT else f"\n(and {len(facts) - RECALL_LIMIT} more)"
        return f"Here is everything I remember:\n{body}{more}"
    words = [w for w in q.lower().split() if w]
    scored = []
    for f in facts:
        t = f["text"].lower()
        score = sum(t.count(w) for w in words)
        if score:
            scored.append((score, f["text"]))
    if not scored:
        return f'I have nothing about "{q}" in memory, sir.'
    scored.sort(key=lambda x: -x[0])
    body = "\n".join(f"- {t}" for _, t in scored[:RECALL_LIMIT])
    return f'Here is what I remember about "{q}":\n{body}'


@tool(
    "forget",
    "Remove a fact from long-term memory. Give a few words that identify the "
    "fact to delete. For safety, if several facts match, nothing is deleted "
    "and the matches are listed so you can be more specific.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words identifying the fact to forget"},
        },
        "required": ["query"],
    },
)
def forget(query: str = "") -> str:
    q, _ = _clean(query, MAX_QUERY_LEN)
    if not q:
        return "Error: tell me what to forget, sir."
    ql = q.lower()
    with _LOCK:
        facts = _load()
        matches = [f for f in facts if ql in f["text"].lower()]
        if not matches:
            return f'Nothing in memory matches "{q}", sir.'
        if len(matches) > 1:
            listed = "\n".join(f"- {m['text']}" for m in matches[:RECALL_LIMIT])
            return (f'That matches {len(matches)} memories — please be more '
                    f"specific. Matches:\n{listed}")
        facts.remove(matches[0])
        _save(facts)
    return f'Forgotten: "{matches[0]["text"]}"'


@tool(
    "update_fact",
    "Correct or replace a fact already in long-term memory, instead of adding "
    "a second one that contradicts it. Give a few words that identify the "
    "existing fact ('old') and the corrected wording ('new'). Use this when "
    "something you remembered has CHANGED (a moved meeting, a new password, a "
    "corrected address). For safety, if several facts match 'old', nothing "
    "changes and the matches are listed so you can be more specific. If nothing "
    "matches, save it with remember instead.",
    {
        "type": "object",
        "properties": {
            "old": {
                "type": "string",
                "description": "A few words identifying the existing fact to change",
            },
            "new": {
                "type": "string",
                "description": "The corrected/updated wording of the fact",
            },
        },
        "required": ["old", "new"],
    },
)
def update_fact(old: str = "", new: str = "") -> str:
    q, _ = _clean(old, MAX_QUERY_LEN)
    text, truncated = _clean(new, MAX_FACT_LEN)
    if not q:
        return "Error: tell me which fact to update, sir."
    if not text:
        return "Error: tell me what the fact should now say, sir."
    ql = q.lower()
    note = " (shortened to fit)" if truncated else ""
    with _LOCK:
        facts = _load()
        matches = [f for f in facts if ql in f["text"].lower()]
        if not matches:
            return (f'Nothing in memory matches "{q}", sir. Use remember to '
                    "save it as a new fact.")
        if len(matches) > 1:
            listed = "\n".join(f"- {m['text']}" for m in matches[:RECALL_LIMIT])
            return (f'That matches {len(matches)} memories — please be more '
                    f"specific about which to update. Matches:\n{listed}")
        target = matches[0]
        old_text = target["text"]
        if text.lower() == old_text.lower():
            return f'That memory already says: "{old_text}"'
        # if the new wording duplicates a DIFFERENT existing fact, don't store a
        # duplicate — drop the old one and keep the wording already remembered
        dup = next((f for f in facts
                    if f is not target and f["text"].lower() == text.lower()), None)
        if dup is not None:
            facts.remove(target)
            _save(facts)
            return (f'Updated{note}: dropped "{old_text}" — I already remember '
                    f'"{dup["text"]}".')
        target["text"] = text
        target["ts"] = datetime.now().strftime("%Y-%m-%d")
        _save(facts)
    return f'Updated{note}: "{old_text}" -> "{text}"'


# --------------------------------------------------------------------------
# used by the agent (not a tool) to inject stored facts into the prompt
# --------------------------------------------------------------------------
def count() -> int:
    """Number of stored facts. Never raises (0 on any error)."""
    try:
        with _LOCK:
            return len(_load())
    except Exception:
        return 0


def memory_preamble() -> str:
    """A formatted block of stored facts for the agent's system prompt, so the
    model acts on what it already knows. Returns '' when empty; never raises."""
    try:
        with _LOCK:
            facts = _load()
    except Exception:
        return ""
    if not facts:
        return ""
    lines = "\n".join(f"- {f['text']}" for f in facts[-MAX_FACTS:])
    return ("\n\nLong-term memory — things you already know about the user "
            "and should treat as true:\n" + lines)
