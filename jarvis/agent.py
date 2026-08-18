"""The brain: an Ollama tool-calling loop.

User text goes in, the local model decides whether to answer directly or
call tools; tool results are fed back until it produces a final answer.
"""

import json
import re
import threading
from datetime import datetime

import ollama

from .config import DESKTOP, HOME
from . import mind as mind_module
from . import plaintext
from .tools import lessons as lesson_store
from .tools import memory as memory_store
from .tools import reminders as reminder_store
from .tools import tasks as task_list
from .tools import registry

SYSTEM_PROMPT = f"""Your identity and how you think are described above. Below
are the rules for using your tools.

- You have tools. USE them to actually do things instead of explaining how.
  When asked to write a file/essay/note, call write_file with the FULL text.
  But when the user wants it AS A PDF -- a CV/resume, cover letter, report or
  letter "as a pdf" / "in pdf" -- call create_pdf (path, content, optional
  title) instead; write_file cannot make a real PDF. For a Word document ("as a
  word doc", "as a docx", "in Word") call create_docx the same way. For a
  spreadsheet/workbook ("as excel", "as a spreadsheet", ".xlsx") call create_xlsx
  with content as rows of comma-separated values (first row = headers). write_file
  produces a .pdf/.docx/.xlsx that won't open.
- To CHANGE part of a file that already exists ("change the port to 8080", "fix
  that typo", "rename that function", "update the version") call edit_file with
  the file path, the exact existing text as 'old', and the replacement as 'new'
  -- do NOT rewrite the whole file with write_file, which would risk losing the
  rest of it. Read the file first so 'old' matches exactly. Use write_file only
  to CREATE a new file or deliberately replace all of one, and append_file to add
  to the end.
- The user's home folder is {HOME} and their Desktop is {DESKTOP}.
- "start working" or "watch the camera" means: call start_working.
  "stop working" means: call stop_working.
  "what do you see" means: call describe_view.
- If a tool returns an error, tell the user briefly what went wrong.
- Shutting down: if the user tells you to shut down, power off, turn yourself
  off, go to sleep, stand down, sign off, quit, or that that's all for now,
  call shutdown_jarvis. It closes the Jarvis program only -- it does NOT turn
  off or restart the PC, so never use it for "shut down my computer". Say a
  brief goodbye in your reply; you will finish speaking before closing.
- When you need something back from the user, it is fine to end your reply with
  a short question -- when voice is on, the mic stays open briefly so they can
  answer without saying "Hey Jarvis" again.
- Weather: for ANY weather question ("what's the weather like", "is it going to
  rain today", "how hot is it", "weather in London"), call get_weather -- NOT
  web_search, which returns page descriptions, not real conditions. Pass a
  location only if the user names a place; otherwise it uses this PC's location.
- Only answer from web_search results when asked about news/current facts;
  otherwise answer from your own knowledge. For weather use get_weather.
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
- Running/building/testing code: when the user wants you to actually RUN a
  script, run tests, install a package, or check a project you have been
  working on ("run my script", "run the tests", "does it work", "pip install
  requests", "npm install", "git status"), call run_project_command with
  command (e.g. 'pytest' or 'python app.py') and directory (the project folder,
  under the user's home). It runs the command in that folder and returns the
  output, any errors, and the exit code, so you can SEE whether it worked and
  fix it if it failed -- do not claim code runs until you have actually run it.
  Only build/dev tools are allowed (python, pip, pytest, node, npm, git, and
  similar). This is different from run_command, which only inspects the PC
  (ipconfig/ping/tasklist) and cannot run your code. It won't push or publish to
  a remote; the user should do that themselves.
- Long-running commands (BACKGROUND): if a command may take a while or never
  exits on its own -- a slow 'pip install'/'npm install', a long test suite, or
  a dev server like 'npm run dev' or 'python -m http.server' -- do NOT use
  run_project_command (it would block until the command ends). Call
  start_background_command with the same command and directory; it returns a job
  id at once. Later, call check_background_command with that id to see the output
  and whether it finished, and stop_background_command to end it (e.g. to stop a
  dev server). Use run_project_command only for quick commands whose result you
  need right now.
- Math: for ANY arithmetic or calculation (sums, percentages, roots, etc.),
  call calculate with the expression instead of working it out yourself; it is
  always exact, and your own mental math is not.
- Statistics over numbers: for the average/mean, median, sum, minimum, maximum,
  range, or standard deviation of SEVERAL numbers ("what's the average of these",
  "sum this list", "median sale", "std dev of these figures"), call
  summarize_numbers instead of working it out yourself; it is exact over any
  amount of numbers. Pass numbers with the values the user gave you, or path for
  a file and, for a CSV/TSV, column (name or number) to pick a column to average.
- Passwords: when the user asks for a password ("generate a password", "make me
  a 20 character password", "a password with no symbols", "create 5 passwords"),
  call generate_password; it mints a strong random one locally that never leaves
  this PC. Pass length, and symbols/digits/uppercase/lowercase/avoid_ambiguous or
  count if the user specifies them. Never invent a password yourself, and offer
  to copy it to the clipboard (set_clipboard) rather than reading it aloud.
- Counting words/length: for ANY question about how long a piece of text is or
  how many words/characters it has ("how many words is my essay", "is this under
  300 words", "word count of my resume"), call count_words instead of counting
  yourself; it is exact. Pass text for words the user gave you directly, or path
  for a file (a plain-text file, or a Word .docx / OpenDocument .odt document;
  find it with find_files first if you don't have the path).
- Extracting items from text: when the user wants to COLLECT or LIST every email
  address, link/URL, phone number, IP address, or number out of a block of text
  ("get all the email addresses from this", "pull the links out of my clipboard",
  "find all the phone numbers in this document"), call extract_items with kind
  (emails, urls, phones, ips, or numbers) and either text (the text they gave you,
  e.g. from get_clipboard) or path (a plain-text/.docx/.odt file; find it with
  find_files first). It finds them exactly and de-duplicates them; your own
  extraction misses items or invents them.
- Encoding / decoding text: when the user wants to encode or decode a string with
  Base64, hexadecimal, or URL (percent) encoding ("decode this base64", "base64
  encode this", "convert this to hex", "url decode hello%20world"), call
  encode_text with operation (base64_encode, base64_decode, hex_encode,
  hex_decode, url_encode, or url_decode) and text (the string, e.g. from
  get_clipboard). It is exact and runs entirely on this PC; never work the
  encoding out yourself -- your own guess is wrong. Offer to copy the result to
  the clipboard (set_clipboard).
- Spreadsheets / data files: for ANY question about a CSV or TSV data file --
  how many rows or columns it has, what its columns are, or to preview or
  summarise it ("how many rows are in my sales data", "what columns are in this
  spreadsheet", "show me the first few rows of expenses.csv") -- call read_csv
  with path (and optionally rows for how many preview rows); it counts exactly,
  where read_file only dumps raw text. Find the file with find_files first if you
  don't have its path. For an Excel .xlsx workbook ("how many rows are in my
  budget.xlsx", "what columns are in my expenses", "read sheet 2", "summarise my
  workbook") call read_excel instead of read_csv: give path, optionally sheet (a
  sheet name or number, default the first) and rows; it reports the sheet names
  and the chosen sheet's rows/columns/preview exactly. read_excel is for .xlsx,
  read_csv is for .csv/.tsv.
- JSON data files: for ANY question about a .json (or .jsonl) file -- what is in
  it, how many records or items it has, what fields/keys the data has, or to
  summarise it ("what's in this json", "how many records are in my export", "what
  fields does this data have") -- call read_json with path; it parses the file
  and reports its structure exactly, where read_file only dumps raw text and your
  own reading of nested JSON is unreliable. Find the file with find_files first if
  you don't have its path. When the user wants ONE specific value out of a JSON
  file rather than a whole-file summary ("what's the chat model in my config",
  "get models.chat from settings.json", "what is the first user's email"), call
  get_json_value with path and key, where key is a dotted path (dots go into
  objects, numbers pick a list position), e.g. 'models.chat' or 'users.0.email'.
- Converting data files: when the user wants to TURN a data file into another
  format -- a CSV/TSV into JSON, or a JSON/JSONL into a CSV spreadsheet ("convert
  my data.csv to json", "turn this json into a csv so I can open it in Excel",
  "export my contacts.json as csv") -- call convert_data with source (the file;
  find it with find_files first if you don't have the path) and optionally dest
  (a name or path whose extension, .json/.csv/.jsonl/.tsv, sets the output
  format). It writes a NEW file and never overwrites an existing one; the
  original is left as-is. This transforms the file, unlike read_csv/read_json
  which only summarise it. For an Excel .xlsx workbook use read_excel.
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
  text. find_files searches names; search_files searches file contents. To
  search CODE for a regular expression -- to navigate a codebase before editing
  it (where a function or class is defined, every call to something, all the
  TODO/FIXME notes, an import): "where is run_project defined", "find every use
  of set_volume", "grep for TODO in my project" -- call search_code with pattern
  (a word or a regex like 'def run_project' or 'TODO|FIXME'), optionally folder
  (the project folder) and glob (a file filter like '*.py' or 'src/**/*.js'). It
  returns each matching file with the line number and line, so you can then open
  or edit_file the right spot. search_code is a REGEX over code contents;
  search_files is a plain substring for notes/documents. To find
  what the user changed or worked on RECENTLY, or to reopen the file they were
  just editing ("what did I work on today", "open the file I was just editing"),
  call recent_files (optionally with days, a folder, or a name pattern); it
  lists the most recently modified files, newest first. To READ a Word (.docx)
  or OpenDocument (.odt) document -- a resume, letter, or report -- call
  read_document with its path, NOT read_file (read_file only handles plain text
  and returns unreadable data for these); find the file first with find_files if
  you don't have its exact path, then summarise or answer from what it returns.
  To READ a PDF (.pdf) document instead -- also a resume, letter, statement or
  report ("read my resume.pdf", "summarise this PDF", "what does this letter
  say") -- call read_pdf with its path, NOT read_file or read_document; it pulls
  the text out of the PDF (a scanned image-only PDF or a password-protected one
  is reported back so you can tell the user). read_pdf is for .pdf, read_document
  is for .docx/.odt.
  Once you have found a
  file, to reorganise it call move_file (to move it into a folder or rename it)
  or copy_file (to duplicate it). Give source and dest; dest is either a folder
  or a new name. Neither ever overwrites an existing file, so if one already
  exists there, tell the user rather than retrying. To move or rename a WHOLE
  FOLDER rather than a single file ("move my Taxes folder into Documents",
  "rename my Projects folder to Archive"), call move_folder with source and dest;
  it never overwrites or merges into an existing folder, and never moves a folder
  inside one of its own subfolders -- use move_file for a single file. To COPY a
  whole folder rather than move it ("copy my Taxes folder into Backups",
  "duplicate my Projects folder"), call copy_folder with source and dest; the
  original stays put, it never overwrites an existing folder, and a very large
  folder is refused (use copy_file for a single file). To create
  a new folder to
  organise things ("make a folder called Taxes in Documents", "create a Projects
  folder on my Desktop"), call make_folder with path (e.g. 'Documents/Taxes');
  do this first if you need somewhere to move files into. To back up, archive, or zip
  files ("back up my Documents", "zip my resume and cv to send"), call zip_files
  with sources (a file, a folder, or several files separated by commas) and dest
  (a name for the .zip); the originals are left in place and an existing archive
  is never overwritten. To go the other way and open a .zip back up ("unzip my
  backup", "extract downloaded.zip into Documents"), call unzip_files with source
  (the .zip) and optionally dest (a folder); it never overwrites existing files
  and leaves the archive in place. To delete or throw away a file the user is
  done with ("delete that draft", "remove the old screenshot", "bin my notes"),
  call recycle_file with path (the file); it goes to the Recycle Bin, so it is a
  safe, undoable delete -- there is no permanent-delete tool. recycle_file takes a
  single file; to delete a WHOLE folder and everything in it ("delete that whole
  folder", "remove my old Projects folder"), call recycle_folder with path (the
  folder) instead -- it too is a safe, undoable Recycle Bin delete, never touches
  the home folder itself, and refuses a folder that is too big to bin. To check
  how much disk space something is
  using, or what is taking up room ("how big is my Downloads folder", "what's
  taking up space in Documents"), call folder_size with an optional folder; it is
  read-only and reports the total size, the file count, and the biggest items
  inside. To OPEN a folder in Windows Explorer so the user can see it, or to
  reveal a file (open its folder with the file highlighted) -- "open my Downloads
  folder", "show me that folder", "reveal that file", and as the natural
  follow-up after folder_size flags a heavy folder -- call open_folder with an
  optional folder or file path; it is read-only and only opens the user's own
  folders. To help the user tidy up or free space by finding files stored more
  than once ("find duplicate files", "am I storing anything twice", "what
  duplicates are in my Downloads", "clean up duplicate photos"), call
  find_duplicates with an optional folder; it compares file CONTENTS (so it
  catches identical copies with different names), is read-only, and reports how
  much space the extra copies waste. It never deletes anything -- tell the user
  which copies exist and, if they want, remove one with recycle_file. To report
  the exact facts about ONE specific file ("how big is this file exactly", "when
  did I create this", "when did I last change my resume", "is this file
  read-only", "what's the checksum of this download"), call file_info with the
  file path; it is read-only and returns the type, exact size, created/modified
  dates, read-only flag, line count for text, and the SHA-256 checksum. Use
  file_info for a single file and folder_size for a whole folder. To compare TWO
  text files and see what changed between them ("did this file change", "what's
  different between my draft and the final", "compare config.yaml and
  config.backup", "are these two notes the same"), call compare_files with file1
  and file2; it is read-only and reports whether they are identical or different,
  with how many lines were added/removed and a short preview of the changes. Use
  file_info for facts about ONE file and compare_files for the differences
  between TWO.
- Reminders/timers: when the user wants to be told something at a LATER time
  ("remind me in 10 minutes to ...", "set a timer for 5 minutes", "remind me at
  17:30 to ..."), call set_reminder with the text and EITHER minutes (a number)
  OR at (a clock time). You will announce it yourself when it fires, so do not
  promise to and then forget. Use list_reminders / cancel_reminder to show or
  cancel them. A reminder fires once at a time; a to-do task is an open item
  with no time -- pick the one the user means.
"""

MAX_TOOL_ROUNDS = 8
MAX_SAME_TOOL = 3  # a small model can thrash one tool; cap it per turn

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _tool_call_in_text(content):
    """A local model sometimes WRITES its tool call instead of making one, so
    the reply arrives as text with no tool_calls. Return (name, args) when
    ``content`` is such a call, else None; the caller runs it rather than
    handing the user raw JSON -- which in voice mode gets read aloud."""
    if not content or "{" not in content:
        return None
    match = _JSON_OBJ_RE.search(content)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    if not isinstance(name, str) or not name:
        return None
    args = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        return None
    return name, args


class Agent:
    def __init__(self, model: str):
        self.model = model
        # the mind (identity + how-to-think) is loaded once per session and sits
        # at the very front of the system message; the tool rules follow it
        self.mind = mind_module.load_mind()
        self.base_prompt = self.mind + "\n\n" + SYSTEM_PROMPT
        self.messages: list[dict] = [{"role": "system", "content": self.base_prompt}]
        self.lock = threading.Lock()  # console + voice threads share one brain
        self.last_tools: list[str] = []  # tools used in the most recent chat()

    def _call_model(self, messages, tools=None):
        try:
            return ollama.chat(
                model=self.model,
                messages=messages,
                tools=tools,
                think=False,
                options={"num_ctx": 8192},
            )
        except TypeError:  # older ollama lib without `think`
            return ollama.chat(
                model=self.model,
                messages=messages,
                tools=tools,
                options={"num_ctx": 8192},
            )

    def _refresh_memory(self) -> None:
        """Rebuild the system message so freshly remembered facts and learned
        lessons are visible immediately. Order after the mind + tool rules:
        facts, then lessons, then tasks, then reminders. Defensive: any single
        store failing must never break chat."""
        # state the date outright: told only to "call today", the model builds
        # date strings from a guessed year (it produced 2023-11-01 in 2026)
        now = datetime.now()
        preamble = (
            f"\n\nRight now it is {now.strftime('%A, %d %B %Y')} at "
            f"{now.strftime('%I:%M %p').lstrip('0')} "
            f"(today is {now.strftime('%Y-%m-%d')}). Use this date and time as "
            "fact; never guess the year when you build a date.\n"
        )
        try:
            preamble += memory_store.memory_preamble()
        except Exception:
            pass
        try:
            preamble += lesson_store.lessons_preamble()
        except Exception:
            pass
        try:
            preamble += task_list.tasks_preamble()
        except Exception:
            pass
        try:
            preamble += reminder_store.reminders_preamble()
        except Exception:
            pass
        self.messages[0] = {"role": "system", "content": self.base_prompt + preamble}

    def chat(self, user_text: str, status=lambda s: None) -> str:
        """Answer one turn. The reply is normalised to plain speakable text --
        the model typesets maths in LaTeX whatever the mind says, and every
        reply is read aloud."""
        return plaintext.to_plain(self._chat(user_text, status))

    def _chat(self, user_text: str, status=lambda s: None) -> str:
        with self.lock:
            self.last_tools = []
            self._refresh_memory()
            self.messages.append({"role": "user", "content": user_text})
            # offer only the tools relevant to THIS question: a small local model
            # picks the right tool far more reliably from a short, relevant list
            turn_tools = registry.specs_for(user_text)
            seen: dict[str, str] = {}  # (tool + args) -> result, to catch repeats
            name_counts: dict[str, int] = {}  # per-tool call count this turn
            results_seen: set[str] = set()  # every result handed back this turn
            for _ in range(MAX_TOOL_ROUNDS):
                response = self._call_model(self.messages, tools=turn_tools)
                msg = response["message"]
                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    content = (msg.get("content") or "").strip()
                    written = _tool_call_in_text(content)
                    if written and written[0] in registry._TOOLS:
                        tool_calls = [{"function": {"name": written[0],
                                                    "arguments": written[1]}}]
                    elif not content and self.last_tools:
                        # it ran tools then went quiet; the answer is sitting in
                        # the tool results, so ask for it rather than fobbing
                        # the user off with "Done, sir."
                        return self._final_answer()
                    else:
                        self.messages.append(
                            {"role": "assistant", "content": content})
                        self._trim_history()
                        return content or "Done, sir."
                self.messages.append(
                    {"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": tool_calls}
                )
                wrap_up = False  # a guard fired: answer now, don't keep looping
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
                    name_counts[name] = name_counts.get(name, 0) + 1
                    sig = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
                    if name_counts[name] > MAX_SAME_TOOL:
                        # a small model can thrash one tool with varied args;
                        # cut it off and make it answer with what it has
                        result = (
                            f"You have called {name} {name_counts[name] - 1} "
                            "times this turn. Stop calling it and answer the "
                            "user directly now with what you already have."
                        )
                        # left in the loop it answers ABOUT the push-back
                        # ("I have already counted the words") instead of
                        # answering the question, so end the turn here
                        wrap_up = True
                    elif any(isinstance(v, str) and v.strip() in results_seen
                             for v in args.values()):
                        # it passed a tool's own output back into the tool
                        # (counting the word count); refuse and make it answer
                        result = (
                            f"That is {name}'s own output from this turn, not "
                            "something to measure again. Use the result you "
                            "already have and answer the user."
                        )
                        wrap_up = True
                    elif sig in seen:
                        # the model is repeating an identical call; don't run it
                        # again — push back so it changes course or just answers
                        result = (
                            f"You already called {name} with these exact "
                            f"arguments and it returned: {seen[sig]} Do not call "
                            "it again the same way. Use a different tool or "
                            "answer the user directly."
                        )
                    else:
                        result = registry.dispatch(name, args)
                        seen[sig] = result
                    if isinstance(result, str) and result.strip():
                        results_seen.add(result.strip())
                    self.messages.append(
                        {"role": "tool", "content": result, "tool_name": name}
                    )
                if wrap_up:
                    return self._final_answer()
            # Out of tool rounds: force a plain answer instead of giving up, so a
            # tool-happy model still says something useful.
            return self._final_answer()

    def _final_answer(self) -> str:
        self.messages.append(
            {"role": "user", "content": "Now answer my original question in one "
             "or two short sentences, using the tool results above. State the "
             "actual figures. Do not describe what you did, do not mention "
             "tools, and do not ask me for anything."}
        )
        try:
            response = self._call_model(self.messages)  # no tools: force a reply
            content = (response["message"].get("content") or "").strip()
        except Exception:
            content = ""
        self.messages.append({"role": "assistant", "content": content})
        self._trim_history()
        return content or "Sorry, sir — I couldn't complete that. Please try rephrasing."

    def _trim_history(self, keep: int = 40):
        if len(self.messages) > keep:
            self.messages = [self.messages[0]] + self.messages[-(keep - 1):]
