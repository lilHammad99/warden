"""The brain: an Ollama tool-calling loop.

User text goes in, the local model decides whether to answer directly or
call tools; tool results are fed back until it produces a final answer.
"""

import json
import threading

import ollama

from .config import DESKTOP, HOME
from .tools import memory as memory_store
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
  recall. Anything under "Long-term memory" below is already known — use it.
- For questions about this PC's network or running programs (IP address,
  whether the internet is up, what's running), use run_command with a safe
  command like ipconfig, ping, or tasklist.
- Math: for ANY arithmetic or calculation (sums, percentages, roots, etc.),
  call calculate with the expression instead of working it out yourself; it is
  always exact, and your own mental math is not.
- To-do list: when the user asks to add/track something to do ("remind me to",
  "add ... to my list", "I need to"), call add_task. To show it call
  list_tasks; to check something off call complete_task; to delete call
  remove_task. Anything under "The user's current to-do list" below is open.
"""

MAX_TOOL_ROUNDS = 8


class Agent:
    def __init__(self, model: str):
        self.model = model
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.lock = threading.Lock()  # console + voice threads share one brain

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
        self.messages[0] = {"role": "system", "content": SYSTEM_PROMPT + preamble}

    def chat(self, user_text: str, status=lambda s: None) -> str:
        with self.lock:
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
                    result = registry.dispatch(name, args)
                    self.messages.append(
                        {"role": "tool", "content": result, "tool_name": name}
                    )
            self._trim_history()
            return "I got stuck in a tool loop, sir. Please try rephrasing."

    def _trim_history(self, keep: int = 40):
        if len(self.messages) > keep:
            self.messages = [self.messages[0]] + self.messages[-(keep - 1):]
