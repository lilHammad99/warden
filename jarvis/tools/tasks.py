"""Persistent to-do / task list for Jarvis.

A real autonomy win: the user can just say "add buy milk to my to-do list",
"what's on my list?", or "mark the milk one done", and Jarvis keeps the list
across restarts, backed by a small JSON file at ``data/tasks.json``. Open
tasks are also injected into the agent's system prompt so Jarvis is aware of
what the user still has to do and can bring it up ("you still need to...").

Everything here is defensively validated on purpose: an 8B local model can
hallucinate. It may try to add an empty task, dump an essay as a "task",
call ``add_task`` in a loop, pass the wrong argument type, or point
``complete_task`` at nothing. None of that is allowed to crash the agent,
fill the disk, or corrupt the file — bad input comes back as a plain,
friendly error string the model can read and recover from.
"""

import json
import threading
from datetime import datetime

from ..config import PROJECT_ROOT
from .registry import tool

_STORE = PROJECT_ROOT / "data" / "tasks.json"
_LOCK = threading.Lock()  # console + voice threads share the store

MAX_TASKS = 200       # hard cap so a looping model can't fill the disk
MAX_TASK_LEN = 300    # a task is a short line, not an essay dump
MAX_QUERY_LEN = 200
LIST_LIMIT = 50       # most tasks shown in one call

_WHICH = {
    "open": "open", "todo": "open", "pending": "open", "active": "open",
    "done": "done", "completed": "done", "finished": "done", "complete": "done",
    "all": "all", "everything": "all", "both": "all",
}


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
            _STORE.rename(_STORE.with_name("tasks.corrupt.json"))
        except OSError:
            pass
        return []
    if not isinstance(data, list):
        return []
    tasks: list[dict] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"].strip()
            if text:
                tasks.append({
                    "text": text,
                    "done": bool(item.get("done", False)),
                    "ts": str(item.get("ts", "")),
                })
    return tasks


def _save(tasks: list[dict]) -> None:
    """Atomic write: dump to a temp file then replace, so a crash mid-write
    can't leave a half-written (corrupt) store."""
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_STORE)


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


def _resolve(query: str, pool: list[dict]) -> tuple[list[dict], str]:
    """Find task(s) in ``pool`` that ``query`` refers to.

    A pure number picks the Nth item shown in the list (1-based). Otherwise
    a case-insensitive substring match is used. Returns (matches, note) where
    an empty match list is normal (caller decides the message)."""
    q = query.strip()
    if q.isdigit():
        n = int(q)
        if 1 <= n <= len(pool):
            return [pool[n - 1]], ""
        return [], f'there is no task number {n}, sir'
    ql = q.lower()
    return [t for t in pool if ql in t["text"].lower()], ""


def _render(tasks: list[dict]) -> str:
    """Number tasks 1..N with a [ ] / [x] box (pure ASCII)."""
    lines = []
    for i, t in enumerate(tasks[:LIST_LIMIT], 1):
        box = "[x]" if t["done"] else "[ ]"
        lines.append(f"{i}. {box} {t['text']}")
    if len(tasks) > LIST_LIMIT:
        lines.append(f"...(and {len(tasks) - LIST_LIMIT} more)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# tools exposed to the model
# --------------------------------------------------------------------------
@tool(
    "add_task",
    "Add one item to the user's to-do list so it is remembered across "
    "restarts. Use when the user says 'add ... to my to-do list', 'remind me "
    "to ...', 'I need to ...', or 'put ... on my list'. One short task per call.",
    {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "One short thing to do"},
        },
        "required": ["task"],
    },
)
def add_task(task: str = "") -> str:
    text, truncated = _clean(task, MAX_TASK_LEN)
    if not text:
        return "Error: nothing to add, sir - the task was empty."
    with _LOCK:
        tasks = _load()
        for t in tasks:
            if not t["done"] and t["text"].lower() == text.lower():
                return f'That is already on your list, sir: "{text}"'
        if len(tasks) >= MAX_TASKS:
            return (f"Your to-do list is full ({MAX_TASKS} items), sir. Clear "
                    "some with remove_task or complete_task first.")
        tasks.append({
            "text": text,
            "done": False,
            "ts": datetime.now().strftime("%Y-%m-%d"),
        })
        _save(tasks)
        open_n = sum(1 for t in tasks if not t["done"])
    note = " (shortened to fit)" if truncated else ""
    return f'Added to your to-do list{note}: "{text}". You now have {open_n} open.'


@tool(
    "list_tasks",
    "Show the user's to-do list. Use when they ask 'what's on my to-do list?', "
    "'what do I have to do?', or 'what have I finished?'. By default shows open "
    "(not-yet-done) tasks; pass which='done' or which='all' to change that.",
    {
        "type": "object",
        "properties": {
            "which": {
                "type": "string",
                "description": "open (default), done, or all",
            },
        },
        "required": [],
    },
)
def list_tasks(which: str = "open") -> str:
    key, _ = _clean(which, 20)
    mode = _WHICH.get(key.lower(), "open")
    with _LOCK:
        tasks = _load()
    if not tasks:
        return "Your to-do list is empty, sir."
    if mode == "open":
        chosen = [t for t in tasks if not t["done"]]
        label = "open task"
    elif mode == "done":
        chosen = [t for t in tasks if t["done"]]
        label = "finished task"
    else:
        chosen = tasks
        label = "task"
    if not chosen:
        if mode == "open":
            return "Nothing left to do, sir - your list is all clear."
        return "Nothing finished yet, sir."
    n = len(chosen)
    head = f"You have {n} {label}{'s' if n != 1 else ''}:"
    return f"{head}\n{_render(chosen)}"


@tool(
    "complete_task",
    "Mark one open to-do item as done. Give a few words that identify it, or "
    "the number shown by list_tasks. Use when the user says 'mark ... done', "
    "'I finished ...', or 'check off ...'.",
    {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Words identifying the task, or its list number",
            },
        },
        "required": ["task"],
    },
)
def complete_task(task: str = "") -> str:
    q, _ = _clean(task, MAX_QUERY_LEN)
    if not q:
        return "Error: tell me which task you finished, sir."
    with _LOCK:
        tasks = _load()
        pool = [t for t in tasks if not t["done"]]
        if not pool:
            return "You have no open tasks to complete, sir."
        matches, note = _resolve(q, pool)
        if note:
            return f"Sorry sir, {note}."
        if not matches:
            return f'Nothing open matches "{q}", sir.'
        if len(matches) > 1:
            listed = _render(matches)
            return (f'That matches {len(matches)} open tasks, sir - please be '
                    f"more specific:\n{listed}")
        matches[0]["done"] = True
        matches[0]["ts"] = datetime.now().strftime("%Y-%m-%d")
        _save(tasks)
        left = sum(1 for t in tasks if not t["done"])
    return (f'Marked done: "{matches[0]["text"]}". '
            f"{left} task{'s' if left != 1 else ''} left, sir.")


@tool(
    "remove_task",
    "Delete a task from the list entirely (done or not). Give a few words that "
    "identify it, or the number shown by list_tasks. For safety, if several "
    "tasks match, nothing is deleted and the matches are listed.",
    {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Words identifying the task, or its list number",
            },
        },
        "required": ["task"],
    },
)
def remove_task(task: str = "") -> str:
    q, _ = _clean(task, MAX_QUERY_LEN)
    if not q:
        return "Error: tell me which task to remove, sir."
    with _LOCK:
        tasks = _load()
        if not tasks:
            return "Your to-do list is already empty, sir."
        matches, note = _resolve(q, tasks)
        if note:
            return f"Sorry sir, {note}."
        if not matches:
            return f'Nothing on your list matches "{q}", sir.'
        if len(matches) > 1:
            listed = _render(matches)
            return (f'That matches {len(matches)} tasks, sir - please be more '
                    f"specific:\n{listed}")
        tasks.remove(matches[0])
        _save(tasks)
    return f'Removed from your list: "{matches[0]["text"]}".'


# --------------------------------------------------------------------------
# used by the agent / app (not tools) — never raise
# --------------------------------------------------------------------------
def open_count() -> int:
    """Number of not-yet-done tasks. Never raises (0 on any error)."""
    try:
        with _LOCK:
            return sum(1 for t in _load() if not t["done"])
    except Exception:
        return 0


def tasks_preamble() -> str:
    """A formatted block of open tasks for the agent's system prompt, so Jarvis
    is aware of what the user still has to do. '' when empty; never raises."""
    try:
        with _LOCK:
            tasks = _load()
    except Exception:
        return ""
    open_tasks = [t for t in tasks if not t["done"]][:LIST_LIMIT]
    if not open_tasks:
        return ""
    lines = "\n".join(f"- {t['text']}" for t in open_tasks)
    return ("\n\nThe user's current to-do list (open items you can remind them "
            "about):\n" + lines)
