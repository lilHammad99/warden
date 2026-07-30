"""The brain: an Ollama tool-calling loop.

User text goes in, the local model decides whether to answer directly or
call tools; tool results are fed back until it produces a final answer.
"""

import json
import threading

import ollama

from .config import DESKTOP, HOME
from .tools import memory as memory_store
from .tools import reminders as reminder_store
from .tools import tasks as task_list
from .tools import registry

SYSTEM_PROMPT = f"""You are Jarvis, a local AI assistant running on the user's Windows PC,
inspired by Iron Man's J.A.R.V.I.S. Address the user as "sir".

Rules:
- Be concise. Answers are often spoken aloud, so keep replies short and
  natural. No markdown, no emojis, no bullet lists unless asked.
- You have tools. USE them to actually do things instead of explaining how.
  When asked to write a file/essay/note, call write_file with the FULL text.
- The user's home folder is {HOME} and their Desktop is {DESKTOP}.
- "start working" or "watch the camera" means: call start_working.
  "stop working" means: call stop_working.
  "what do you see" means: call describe_view.
- If a tool returns an error, tell the user briefly what went wrong.
- Only answer from web_search results when asked about news/weather/current
  facts; otherwise answer from your own knowledge.
- Long-term memory: when the user asks you to remember something, or shares a
  lasting fact (a name, preference, schedule, or where something is), call
  remember with one short fact. If they refer to something from before, call
  recall. If something you already remember has CHANGED or was wrong (a moved
  meeting, a new password, a corrected detail), call update_fact with a few
  words of the old fact and the corrected wording, rather than remembering a
  second contradicting fact. Anything under "Long-term memory" below is already
  known — use it.
- For questions about this PC's network or running programs (IP address,
  whether the internet is up, what's running), use run_command with a safe
  command like ipconfig, ping, or tasklist.
- Math: for ANY arithmetic or calculation (sums, percentages, roots, etc.),
  call calculate with the expression instead of working it out yourself; it is
  always exact, and your own mental math is not.
- Unit conversions: for ANY "convert X to Y" (miles to km, C to F, kg to lb,
  cups to ml, mph to km/h, GB to MB, etc.), call convert_units with value,
  from_unit and to_unit instead of guessing; it is always exact.
- Dates: for ANYTHING about the calendar, do not guess. Call today for the
  current date/time, weekday for the day a date falls on, days_until for a
  deadline or birthday, days_between for a span, and date_add for "N days from
  now". Prefer YYYY-MM-DD when passing dates.
- To-do list: when the user asks to add/track something to do ("add ... to my
  list", "put ... on my list", "I need to"), call add_task. To show it call
  list_tasks; to check something off call complete_task; to delete call
  remove_task. Anything under "The user's current to-do list" below is open.
- Finding things on the PC: to locate a file by its NAME ("open my budget
  spreadsheet", "read my CV"), call find_files. To find WHICH file contains some
  text, or information the user saved but can't locate ("which note has the wifi
  password", "find where I wrote about the budget"), call search_files with the
  text. find_files searches names; search_files searches file contents. To find
  what the user changed or worked on RECENTLY, or to reopen the file they were
  just editing ("what did I work on today", "open the file I was just editing"),
  call recent_files (optionally with days, a folder, or a name pattern); it
  lists the most recently modified files, newest first. Once you have found a
  file, to reorganise it call move_file (to move it into a folder or rename it)
  or copy_file (to duplicate it). Give source and dest; dest is either a folder
  or a new name. Neither ever overwrites an existing file, so if one already
  exists there, tell the user rather than retrying.
- Reminders/timers: when the user wants to be told something at a LATER time
  ("remind me in 10 minutes to ...", "set a timer for 5 minutes", "remind me at
  17:30 to ..."), call set_reminder with the text and EITHER minutes (a number)
  OR at (a clock time). You will announce it yourself when it fires, so do not
  promise to and then forget. Use list_reminders / cancel_reminder to show or
  cancel them. A reminder fires once at a time; a to-do task is an open item
  with no time -- pick the one the user means.
"""

MAX_TOOL_ROUNDS = 8


class Agent:
    def __init__(self, model: str):
        self.model = model
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.lock = threading.Lock()  # console + voice threads share one brain
        self.last_tools: list[str] = []  # tools used in the most recent chat()

    def _call_model(self, messages):
        try:
            return ollama.chat(
                model=self.model,
                messages=messages,
                tools=registry.specs(),
                think=False,
                options={"num_ctx": 8192},
            )
        except TypeError:  # older ollama lib without `think`
            return ollama.chat(
                model=self.model,
                messages=messages,
                tools=registry.specs(),
                options={"num_ctx": 8192},
            )

    def _refresh_memory(self) -> None:
        """Rebuild the system message so freshly remembered facts are visible
        immediately. Defensive: a memory failure must never break chat."""
        try:
            preamble = memory_store.memory_preamble()
        except Exception:
            preamble = ""
        try:
            preamble += task_list.tasks_preamble()
        except Exception:
            pass
        try:
            preamble += reminder_store.reminders_preamble()
        except Exception:
            pass
        self.messages[0] = {"role": "system", "content": SYSTEM_PROMPT + preamble}

    def chat(self, user_text: str, status=lambda s: None) -> str:
        with self.lock:
            self.last_tools = []
            self._refresh_memory()
            self.messages.append({"role": "user", "content": user_text})
            for _ in range(MAX_TOOL_ROUNDS):
                response = self._call_model(self.messages)
                msg = response["message"]
                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    content = (msg.get("content") or "").strip()
                    self.messages.append({"role": "assistant", "content": content})
                    self._trim_history()
                    return content or "Done, sir."
                self.messages.append(
                    {"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": tool_calls}
                )
                for call in tool_calls:
                    fn = call["function"]
                    name = fn["name"]
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    status(f"...using {name.replace('_', ' ')}")
                    if isinstance(name, str) and name in registry._TOOLS:
                        self.last_tools.append(name)
                    result = registry.dispatch(name, args)
                    self.messages.append(
                        {"role": "tool", "content": result, "tool_name": name}
                    )
            self._trim_history()
            return "I got stuck in a tool loop, sir. Please try rephrasing."

    def _trim_history(self, keep: int = 40):
        if len(self.messages) > keep:
            self.messages = [self.messages[0]] + self.messages[-(keep - 1):]
