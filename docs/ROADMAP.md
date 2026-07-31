# Jarvis Roadmap

## Done (v1 — 2026-07-29, all smoke-tested)

### Phase 1 — Core agent (text)
- [x] Ollama tool-calling agent loop (`qwen3:8b`)
- [x] Text console (`run.bat`)
- [x] Tools: files (write/append/read/list), apps & websites, system info,
      screenshots, volume, lock, web search + page fetch (23 tools total)

### Phase 2 — Eyes
- [x] Webcam + RTSP camera manager (add IP cams in `config.yaml`)
- [x] "what do you see" — local vision model description (`moondream`)
- [x] "start working" — watch mode: motion gate + YOLOv8n person detection,
      spoken alert + snapshot to `data/snapshots/`
- [x] "stop working", "list cameras"

### Phase 3 — Voice
- [x] "Hey Jarvis" wake word (openWakeWord, onnx)
- [x] Local speech-to-text (faster-whisper small, int8 CPU)
- [x] Talk back (pyttsx3 / SAPI5 on dedicated thread)

### Phase 4 — Hands on the web
- [x] Headed Chromium controlled by the agent (Playwright):
      open, read, click, type, back, close

### Phase 5 — Listening UX (2026-07-30)
- [x] Floating "Jarvis orb" HUD (`jarvis/voice/hud.py`): borderless,
      always-on-top window; orb color = state (idle/listening/thinking/
      speaking), live mic-level bar, drag to move. Fails safe to a no-op.
- [x] Wake sensitivity in `config.yaml` (`voice.wake_threshold`, default 0.4)
- [x] Orb turns green the instant the wake word fires (feels immediate)
- [x] `tests/smoke.py hud` — opens the orb, cycles states + fake mic level

### Phase 6 — Long-term memory (2026-07-30)
- [x] Persistent memory across restarts (`jarvis/tools/memory.py`): tools
      `remember` / `recall` / `forget`, backed by `data/memory.json`
- [x] Saved facts auto-injected into the agent's system prompt each turn, so
      Jarvis acts on what it already knows (name, preferences, schedules)
- [x] Hardened against 8B hallucinations: empty/oversized/wrong-type facts
      rejected or bounded, dedup, per-store cap, atomic writes, corrupt-file
      recovery — none can crash the agent or corrupt the store
- [x] Startup line shows how many facts are remembered
- [x] `tests/smoke.py memory` (in the safe set) covers the guards

### Phase 7 — Safe shell access (2026-07-30)
- [x] `run_command` tool (`jarvis/tools/shell.py`): lets Jarvis answer "what's
      my IP", "is the internet up", "what's running" by running real commands
- [x] Allowlist only (ipconfig, hostname, whoami, ver, tasklist, getmac,
      systeminfo, netstat, ping, nslookup) — nothing destructive is reachable
- [x] Runs with `shell=False` + fixed argv, so an 8B hallucination like
      `ipconfig & del *` can never escape to cmd.exe; ping/nslookup hosts are
      validated against a strict pattern; hard timeout + capped output
- [x] Friendlier tool-activity readout in console/voice ("...using run command")
- [x] `tests/smoke.py shell` (safe set) covers allowlist, injection, host
      validation and wrong-type guards

### Phase 8 — Find files by name (2026-07-30)
- [x] `find_files` tool (`jarvis/tools/find.py`): the model can locate a file
      itself ("open my budget spreadsheet", "read my CV") instead of needing an
      exact path, then act on it with the file/app tools — a real autonomy win
- [x] Searches the user's home folder only; a start folder outside home is
      REJECTED (containment check), so it can never crawl `C:\Windows` or `C:\`
- [x] System/heavy dirs pruned (AppData, node_modules, .git, recycle bin, ...);
      bounded by max depth, max entries scanned, max results, and a hard
      wall-clock time budget — a broad query stops early with a clear note
- [x] Hardened vs 8B hallucinations: wrong-type/empty/bare-`*` args rejected or
      coerced, missing/permission-blocked folders skipped, never raises
- [x] Startup now shows a time-of-day greeting ("Good evening, sir...") and
      suggests "find my resume"; all console output stays pure ASCII
- [x] `tests/smoke.py find` (in the safe set) covers matches, wildcards, dir
      pruning, the containment guard, and the hallucination guards

### Phase 9 — Clipboard access (2026-07-30)
- [x] `get_clipboard` / `set_clipboard` tools (`jarvis/tools/clipboard.py`): the
      model can read whatever the user just copied from ANY app ("summarize what
      I copied", "translate my clipboard") and put its answer back for the user
      to paste with Ctrl+V ("copy that") — bridges every other program to Jarvis
- [x] Implemented on the Win32 clipboard API via `ctypes` (Unicode-correct,
      `CF_UNICODETEXT`), 64-bit-safe handle argtypes; no new dependency
- [x] Hardened vs 8B hallucinations: wrong-type/empty/missing args coerced or
      rejected, reads capped + truncated, oversized writes refused, locked
      clipboard retried then reported, image/empty clipboard handled — never
      raises, never crashes the agent
- [x] Console now shows how long each reply took ("answered in N.Ns") and
      suggests "read my clipboard"; all output stays pure ASCII
- [x] `tests/smoke.py clipboard` (in the safe set) covers the round-trip, the
      hallucination guards, and bounded reads; saves/restores the real
      clipboard so the test is non-invasive

### Phase 10 — To-do list (2026-07-30)
- [x] `add_task` / `list_tasks` / `complete_task` / `remove_task` tools
      (`jarvis/tools/tasks.py`): the 8B model can track what the user has to do
      ("add milk to my list", "what do I have to do?", "mark the milk one done")
      and it persists across restarts in `data/tasks.json` (gitignored)
- [x] Open tasks are injected into the agent's system prompt each turn, so
      Jarvis is aware of them and can bring them up — a real autonomy win
- [x] `complete_task` / `remove_task` accept either a few identifying words OR
      the number shown by `list_tasks`; if several tasks match, nothing changes
      and the matches are listed (no accidental completion/deletion)
- [x] Hardened vs 8B hallucinations: empty/oversized/wrong-type args rejected,
      coerced, or bounded; dedup of open tasks; 200-task cap; atomic writes;
      corrupt-file recovery; out-of-range numbers answered, never crash
- [x] Startup now shows the open-task count and a one-line reminder when the
      list isn't empty; all console output stays pure ASCII
- [x] `tests/smoke.py tasks` (in the safe set) covers add/list/complete/remove,
      dedup, number-vs-text selection, the hallucination guards, and
      corrupt-store recovery

### Phase 11 — Exact calculator (2026-07-30)
- [x] `calculate` tool (`jarvis/tools/calc.py`): the 8B model is unreliable at
      arithmetic, so this lets it compute exactly instead of guessing ("what is
      15% of 240", "(1250 * 1.2) / 3", "sqrt(2)") — an accuracy/autonomy win
- [x] NO eval/exec: the expression is parsed to an AST and walked by hand, so
      only numbers, arithmetic operators, an allowlist of math functions
      (sqrt/sin/cos/log/round/min/max/factorial/...) and the constants pi/e/tau
      are permitted — a hallucinated `__import__('os').system('del *')` is
      refused, never run
- [x] Hardened vs 8B hallucinations: sizes capped (expression length, AST node
      count, power exponent, factorial arg) so `9**9**9` / `factorial(999999)`
      can't hang or exhaust memory; wrong-type args coerced; divide-by-zero,
      domain errors, syntax errors and overflow all return a friendly string —
      never crashes the agent
- [x] Agent system prompt now tells the model to use `calculate` for any math
- [x] Console startup adds a clean ASCII separator rule and a calculator
      example in the "Try:" line (pure ASCII)
- [x] `tests/smoke.py calc` (in the safe set) covers arithmetic, functions,
      constants, code-injection refusal, and the size/overflow guards

### Phase 12 — Date & time calculator (2026-07-30)
- [x] `today` / `weekday` / `days_until` / `days_between` / `date_add` tools
      (`jarvis/tools/dates.py`): the 8B model miscounts calendars, so this lets
      it answer deadlines, birthdays, "what day is X", and "N days from now"
      exactly ("how many days until christmas", "what day of the week is
      2026-12-25", "what's the date 90 days from now") — an accuracy/autonomy win
- [x] Pure stdlib `datetime`, NO new dependency; complements `calculate`
- [x] Unambiguous parsing only: ISO `YYYY-MM-DD`, month-name forms
      ("December 25 2026"), and today/tomorrow/yesterday. Ambiguous `m/d` vs
      `d/m` slash dates are REFUSED, not guessed
- [x] Hardened vs 8B hallucinations: input length + numeric offsets capped
      (so `date_add(days=1e12)` can't overflow/hang), wrong-type args coerced,
      unparseable/empty/missing dates return a friendly ASCII message — never
      crashes the agent
- [x] Agent system prompt now tells the model to use these tools for anything
      calendar-related instead of guessing
- [x] Startup now shows the current time + full date line, and adds a "how many
      days until christmas" example to the "Try:" line (pure ASCII)
- [x] `tests/smoke.py dates` (in the safe set) covers weekday/today, exact
      day math, date_add (days/weeks/negative/no-base), and the hallucination
      guards (unparseable, ambiguous slash date, over-long, offset overflow,
      wrong types)

### Phase 13 — Self-correcting tool dispatch (2026-07-30)
- [x] Hardened `jarvis/tools/registry.py::dispatch` so an 8B hallucination in a
      tool CALL no longer dead-ends the agent — a real autonomy/robustness win,
      not another tool: the model recovers on the next round instead of getting
      stuck
- [x] Hallucinated/misspelled tool name -> no longer a bare "unknown"; it
      fuzzy-matches (difflib) the closest REAL tool and says "Did you mean: X?",
      so the next round self-corrects; a totally bogus name is nudged toward the
      new `list_tools`
- [x] New `list_tools` tool: the model can enumerate exactly which tools exist
      when it is unsure, instead of guessing a name
- [x] Argument shapes coerced: a JSON string, a list, None, or garbage where a
      dict was expected is normalised, never crashes
- [x] Hallucinated EXTRA arguments (a stray "reason"/"confidence"/... key) are
      dropped against the function's real signature so a valid call STILL
      succeeds, with a quiet note naming what was ignored; a genuinely missing
      required argument is reported BY NAME so the model knows what to supply
- [x] Never raises: every path returns a plain ASCII string; clean calls are
      byte-for-byte unchanged (no note), so existing tools are untouched
- [x] UX: the console now shows which tools a reply used
      ("answered in N.Ns using calculate, write_file"), so the autonomy is
      visible; pure ASCII
- [x] `tests/smoke.py dispatch` (in the safe set) covers unknown-tool
      suggestion, bad-name guards, arg-shape normalization, extra-arg dropping,
      missing-required reporting, and list_tools

### Phase 14 — Reminders & timers (2026-07-30)
- [x] `set_reminder` / `list_reminders` / `cancel_reminder` tools
      (`jarvis/tools/reminders.py`): the biggest autonomy win yet — instead of
      only reacting, Jarvis acts on its OWN later, unprompted ("remind me in 10
      minutes to check the oven", "set a timer for 5 minutes", "remind me at
      17:30 to call mum") and announces it out loud when the time comes
- [x] A background daemon thread in `app.py` polls `due_reminders()` every ~15s
      and speaks/prints anything due; reminders persist across restarts in
      `data/reminders.json` (gitignored) and are injected into the agent system
      prompt so Jarvis stays aware of them
- [x] Firing is driven by a pure `due_reminders(now)` function, so the smoke
      test is fully deterministic — no model, no real waiting
- [x] Accepts EITHER a relative `minutes` delay OR an unambiguous absolute `at`
      time ("17:30", "2026-12-25 09:00"); ambiguous slash dates and both-at-once
      are REFUSED, not guessed; a time already passed today rolls to tomorrow
- [x] Hardened vs 8B hallucinations: empty/oversized/wrong-type text bounded,
      `minutes` coerced and rejected if negative/zero/non-finite/absurd (so
      `minutes=1e12` can't overflow), 100-reminder cap, atomic writes,
      corrupt-file recovery — never crashes the agent
- [x] Startup status line now shows pending-reminder count + next-due phrase,
      and the "Try:" line suggests "remind me in 10 minutes to stretch"; all
      console output stays pure ASCII
- [x] `tests/smoke.py reminders` (in the safe set) covers set/list/preamble,
      absolute times, deterministic firing, cancel by text+number, the
      hallucination guards, and corrupt-store recovery

### Phase 15 — Search inside files (2026-07-30)
- [x] `search_files` tool (`jarvis/tools/search.py`): content search INSIDE the
      user's files, complementing `find_files` (which matches names). The 8B
      model can now answer "which note has the wifi password", "find where I
      wrote about the budget", "which script calls set_volume" and get back the
      matching files AND lines with their line numbers — a real autonomy win
- [x] Optional `folder` (like 'Documents') and `name` glob (like '*.txt') to
      narrow the scan; matching is case-insensitive substring (no regex, so no
      catastrophic backtracking)
- [x] Rooted in the user's home only (shares `find_files`' containment check):
      a folder outside home is REJECTED, so it can never grep `C:\Windows` or
      all of `C:\`; system/heavy dirs pruned (AppData, node_modules, .git, ...)
- [x] Text only + bounded everywhere: binary files (by extension AND a NUL-byte
      sniff) and >2 MB files skipped; caps on depth, files opened, entries
      scanned, matches (total + per file), and a hard wall-clock time budget —
      a broad query stops early with a clear note instead of hanging the agent
- [x] Hardened vs 8B hallucinations: wrong-type/empty/missing args coerced or
      rejected, bare-`*` name filter treated as no filter, matched lines forced
      to single-line bounded pure ASCII (a file full of odd bytes can't corrupt
      the console/context), unreadable files skipped — never raises
- [x] Agent system prompt now tells the model when to pick `search_files`
      (contents) vs `find_files` (names); "Try:" line suggests "which file
      mentions the wifi password"; all console output stays pure ASCII
- [x] `tests/smoke.py search` (in the safe set) covers the happy path, line
      numbers, case-insensitive + nested match, the `name` filter, dir pruning,
      binary skipping, ASCII-only output, the containment guard, and the
      hallucination guards

### Phase 16 — Update a remembered fact (2026-07-30)
- [x] `update_fact` tool (`jarvis/tools/memory.py`): the 8B model can now CORRECT
      or replace a fact it already stored, instead of piling up a second one that
      contradicts it ("actually my wifi password changed to ...", "my meeting
      moved to Tuesday", "update my address"). Closes the top memory item in
      Future work — Jarvis's memory stays consistent over time, a real autonomy
      win
- [x] Give a few words of the existing fact (`old`) + the corrected wording
      (`new`); the single matching fact is replaced IN PLACE (count unchanged,
      timestamp refreshed) and the change is reflected immediately in `recall`
      and the injected system-prompt preamble
- [x] Safe by construction, mirroring `forget`: if several facts match `old`,
      NOTHING changes and the matches are listed so the model can be more
      specific; if nothing matches, the model is told to use `remember` instead;
      if `new` duplicates a DIFFERENT existing fact, the old one is dropped
      rather than creating a duplicate
- [x] Hardened vs 8B hallucinations: empty `old`/`new` rejected, over-long `new`
      truncated (bounded, reuses `MAX_FACT_LEN`), wrong-type args coerced,
      no-op update (new == old) reported, atomic writes via the existing
      `_save`, corrupt-store recovery inherited — never raises, never corrupts
- [x] Agent system prompt now steers "something I told you changed/was wrong" to
      `update_fact` rather than a second `remember`; the "Try:" line suggests
      "actually my wifi password changed to hunter2"; all output stays ASCII
- [x] `tests/smoke.py memory` (in the safe set) gains update_fact coverage: the
      in-place replace happy path, no-match-points-at-remember, ambiguous
      multi-match safety, the empty/missing/wrong-type/over-long guards, and
      dedup-on-update

### Phase 17 — Unit converter (2026-07-30)
- [x] `convert_units` tool (`jarvis/tools/convert.py`): the 8B model is
      unreliable at unit conversions, so this lets it answer any "convert X to Y"
      exactly ("how many km is 5 miles", "convert 32 F to C", "how many ml in a
      cup", "60 mph in km/h", "2 GB to MB") instead of guessing -- an
      accuracy/autonomy win that rounds out the exact-computation family
      (`calculate` for numbers, the date tools for the calendar)
- [x] Pure stdlib, NO new dependency: length, mass, volume, temperature, time,
      speed, area and data, via factor maths to a per-category base unit;
      temperature is handled specially as an affine (offset) scale, not a ratio
- [x] Unknown units are REFUSED, not guessed (allowlist of names/symbols/aliases
      with a plural fallback); cross-category conversions ("miles to kilograms",
      temperature vs a linear unit) are refused with a clear note rather than
      producing nonsense
- [x] Forgiving to 8B quirks: wrong-type args coerced, the model may pass the
      units as `from`/`to` (not just `from_unit`/`to_unit`), or dump a whole
      phrase like "5 miles to km" into one field -- all handled instead of
      dead-ending; value magnitude capped (a hallucinated `1e400`/non-finite
      value can't overflow), unit/phrase strings length-bounded; never raises,
      output stays pure ASCII
- [x] Agent system prompt now steers any "convert X to Y" to `convert_units`;
      the console "Try:" line suggests "convert 5 miles to km"
- [x] `tests/smoke.py convert` (in the safe set) covers length/mass/temperature
      conversions, the affine temperature scale, forgiving input (alt arg names,
      phrase, string value), the cross-category + unknown-unit guards, the
      magnitude/overflow guards, wrong-type shapes, and ASCII-only output

### Phase 18 — Recently changed files (2026-07-30)
- [x] `recent_files` tool (`jarvis/tools/recent.py`): the third member of the
      file-navigation family after `find_files` (by NAME) and `search_files` (by
      CONTENT) -- it searches by TIME. The 8B model can now act on what the user
      last touched instead of needing a name or a path ("open the file I was just
      editing", "what did I work on today", "what did I change this week"),
      listing the most recently modified files newest-first -- a real autonomy win
- [x] Optional `days` window (default 7), `folder` (like 'Documents') and `name`
      glob (like '*.docx') to narrow it; results are sorted newest-first with a
      human "how long ago" phrase ("just now", "yesterday", "3 days ago")
- [x] Rooted in the user's home only (shares `find_files`' containment check):
      a folder outside home is REJECTED, so it can never crawl `C:\Windows` or
      all of `C:\`; system/heavy dirs pruned (AppData, node_modules, .git, ...)
- [x] Bounded everywhere: `days` coerced + clamped (a hallucinated `1e400`/
      non-finite/negative value can't overflow the cutoff), caps on depth,
      entries scanned, results shown, and a hard wall-clock time budget -- a
      broad query stops early with a clear note instead of hanging the agent
- [x] Hardened vs 8B hallucinations: no args is valid (whole home, last week),
      wrong-type `days`/`folder`/`name` coerced, a "3 days" phrase parsed to a
      number, bare-`*` name filter treated as no filter, un-stat-able files
      skipped, paths forced to pure ASCII -- never raises, output stays ASCII
- [x] Agent system prompt now steers "what did I work on / the file I was just
      editing" to `recent_files`; the "Try:" line suggests "what did I work on
      today"; all console output stays pure ASCII
- [x] `tests/smoke.py recent` (in the safe set) covers the happy path + newest-
      first ordering, the `days` window, the `name` filter, dir pruning, the
      containment guard, ASCII-only output, the no-match message, and the
      hallucination guards (junk/negative/overflow days, phrase parsing, wrong
      types, bare-`*`, missing folder)

### Phase 19 — Move, rename & copy files (2026-07-30)
- [x] `move_file` / `copy_file` tools (`jarvis/tools/organize.py`): the ACTION
      half of the file tools. The navigation family (`find_files` by name,
      `search_files` by content, `recent_files` by time) let Jarvis LOCATE a
      file but only read/open it; now it can actually organise what it finds
      ("move the budget into Documents", "rename my resume to CV.pdf", "make a
      copy of my notes") -- a real autonomy win that closes the loop
- [x] `move_file` moves a file into a folder OR renames it (a bare new name
      renames it inside its own folder, not off in the home root); `copy_file`
      duplicates it and leaves the original in place. Deleting is deliberately
      NOT offered
- [x] Rooted in the user's home only (shares `find_files`' containment check):
      BOTH the source and the destination are rejected unless they live inside
      the user's home, so Jarvis can never move a file into `C:\Windows` or drag
      one out of the user's own folders
- [x] Never overwrites: if something already exists at the destination the move
      or copy is REFUSED, so an 8B hallucination can never silently destroy an
      existing file. Files only (a folder source is refused); `copy_file` refuses
      a file above a 500 MB cap so a runaway copy can't hang or fill the disk
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`from`/`to`/`path`/`new_name`/...), a
      bare new name sanitised of path parts, missing source and folder source
      reported as friendly messages, all output forced to pure ASCII -- never
      raises, never crashes the agent
- [x] Agent system prompt now steers "move/rename/duplicate that file" to
      move_file/copy_file (and to tell the user rather than retry when a file
      already exists); the "Try:" line suggests "rename that file to
      notes_final.txt"
- [x] `tests/smoke.py organize` (in the safe set) covers move-into-folder,
      rename-in-place, copy-keeps-original, the never-overwrite guard, alt arg
      names, the containment guard, missing-source + folder-source messages, the
      copy size cap, ASCII-only output, and the empty/missing/wrong-type guards

### Phase 20 — Back up / archive files (2026-07-30)
- [x] `zip_files` tool (`jarvis/tools/archive.py`): the backup member of the
      file tools. The navigation family (`find_files` by name, `search_files` by
      content, `recent_files` by time) LOCATES a file and the organise family
      (`move_file`/`copy_file`) REARRANGES it; this bundles files up so the user
      can back them up or send them on ("back up my Documents into a zip", "zip
      my resume and cv to send", "make an archive of the report") -- a real
      autonomy win. The originals are always left exactly where they are
- [x] Zips a single file, several files (a list, or a comma/newline-separated
      string), or a whole folder (walked recursively, system/heavy dirs pruned
      like the rest of the file family); archive entries are stored relative to
      the home folder so the structure is sensible and no absolute path leaks
- [x] Rooted in the user's home only (shares `find_files`' containment via
      `organize._resolve_under_home`): BOTH every source AND the destination
      `.zip` are rejected unless they live inside the user's home, so Jarvis can
      never read `C:\Windows` or drop an archive outside the user's own folders
- [x] Never overwrites an existing `.zip` (a hallucination can't clobber a
      backup); a missing `.zip` suffix is added; the archive is written to a
      `.part` temp file in the destination folder and only `os.replace`-d into
      place once complete, so a crash never leaves a half-written archive
- [x] Bounded everywhere: caps on file count (5000), total uncompressed bytes
      (500 MB), folder-walk depth, and a hard wall-clock time budget -- a runaway
      "zip everything" stops early with a clear note instead of hanging or
      filling the disk; unreadable/vanished files are skipped and counted
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`files`/`paths`/`from`/`to`/`name`/...),
      a list-shaped `sources` handled, sources outside home skipped with a
      friendly note, all output forced to pure ASCII -- never raises, never
      crashes the agent
- [x] Agent system prompt now steers "back up / archive / zip these files" to
      `zip_files`; the console "Try:" line suggests "back up my documents into a
      zip"
- [x] `tests/smoke.py archive` (in the safe set) covers zip-a-folder (with noise
      pruned + originals kept), zip-several-files + auto `.zip` suffix, alt arg
      names, the never-overwrite guard, the containment guard (source AND dest),
      the total-size cap (no partial archive), ASCII-only output, and the
      empty/missing/wrong-type/list-shape guards

### Phase 21 — Unzip / extract archives (2026-07-30)
- [x] `unzip_files` tool (`jarvis/tools/extract.py`): the restore/unpack
      counterpart to `zip_files`. `zip_files` bundles files INTO a `.zip`; this
      opens one back UP. Once Jarvis has located an archive (`find_files` /
      `recent_files`) the user can say "unzip my backup", "extract downloaded.zip
      into Documents", "open that archive" and Jarvis unpacks it into the user's
      own folders -- closes the last file-management loop
- [x] Give `source` (the `.zip`) and optionally `dest` (a folder to extract
      into); by default a new folder named after the archive is created beside
      it. The archive itself is always left exactly where it is
- [x] Rooted in the user's home only (shares `find_files`' containment via
      `organize._resolve_under_home`): BOTH the source `.zip` AND the destination
      folder are rejected unless they live inside the user's home, so Jarvis can
      never read an archive from `C:\Windows` or write extracted files outside
      the user's folders
- [x] **Zip-slip proof.** Every entry's target is rebuilt from sanitised path
      parts -- a `..` traversal component is REJECTED and the entry skipped, drive
      letters/leading slashes neutralised -- then re-checked to be inside the
      destination, so a hostile/hallucinated entry like `..\..\Windows\evil.exe`
      can never escape the extract folder (covered by a real malicious-zip test)
- [x] Never overwrites: an entry whose target already exists is SKIPPED and
      counted, never clobbered, so extraction can't destroy existing work
- [x] Zip-bomb bounded: caps on file count (5000), total uncompressed bytes
      (500 MB), per-entry compression ratio, nested path depth, and a wall-clock
      budget; each file is streamed with a running byte cap so a lying size
      header can't blow up memory or fill the disk. Atomic per file (written to a
      `.part` temp then `os.replace`-d in, so a crash leaves no half-written file)
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`archive`/`into`/`from`/`to`/...), a
      corrupt/non-zip file reported as a friendly message, all output forced to
      pure ASCII -- never raises, never crashes the agent
- [x] Agent system prompt now steers "unzip / extract / open that archive" to
      `unzip_files`; the console "Try:" line suggests "unzip my backup"
- [x] `tests/smoke.py extract` (in the safe set) covers extract-into-default-
      folder (archive kept), named dest, the never-overwrite guard, a REAL
      zip-slip archive staying inside the folder, the containment guard (source
      AND dest), a corrupt/non-zip archive, alt arg names, ASCII-only output, and
      the empty/missing/wrong-type/folder-source guards

### Phase 22 — Delete to Recycle Bin (2026-07-30)
- [x] `recycle_file` tool (`jarvis/tools/recycle.py`): the safe 'delete' member
      of the file tools, completing the family. The navigation tools LOCATE a
      file (`find_files`/`search_files`/`recent_files`), organise REARRANGES it
      (`move_file`/`copy_file`), and archive backs it up / restores it
      (`zip_files`/`unzip_files`); the one everyday action still missing was
      removing a file the user is done with ("delete that draft", "remove the old
      screenshot", "bin my notes"). Now Jarvis can -- WITHOUT destroying anything
- [x] **Never a permanent delete.** The file is sent to the Windows Recycle Bin
      (`FOF_ALLOWUNDO` via the Win32 shell API, ctypes, no new dependency), so
      anything Jarvis removes the user can restore. There is deliberately no
      hard-delete path anywhere in the module
- [x] Rooted in the user's home only (shares `find_files`' containment via
      `organize._resolve_under_home`): a file outside home is REJECTED, so Jarvis
      can never bin something in `C:\Windows` or outside the user's own folders
- [x] Files only (a folder is refused, so a whole tree can't be binned by one
      hallucinated path); bounded by a size cap -- a file too large for the
      Recycle Bin (which Windows would delete for good) is REFUSED rather than
      risking a permanent, un-undoable delete
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`file`/`source`/`path`/...), success only
      claimed after confirming the file actually left its place, an OS-level
      delete failure surfaced as a friendly message, all output pure ASCII --
      never raises, never crashes the agent
- [x] Agent system prompt now steers "delete / remove / bin that file" to
      `recycle_file` (and makes clear it is undoable and single-file only); the
      console "Try:" line suggests "delete that old draft to the recycle bin"
- [x] `tests/smoke.py recycle` (in the safe set) covers the happy path
      (file removed + recoverable), alt arg names, the containment guard, a
      folder refusal, the missing-source message, the size cap, an OS-failure
      guard, ASCII-only output, and the empty/missing/wrong-type guards. The real
      Recycle Bin call is swapped for a hermetic fake, so the test is
      deterministic and never touches the user's real bin

### Phase 23 — Create folders (2026-07-30)
- [x] `make_folder` tool (`jarvis/tools/organize.py`): the missing primitive in
      the file-organisation family. The navigation tools LOCATE a file and
      move/copy REARRANGE it, but move_file/copy_file can only drop a file into a
      folder that already exists -- there was no way to CREATE one. Now Jarvis can
      make somewhere to organise into ("make a folder called Taxes in Documents",
      "create a Projects folder on my Desktop") and then move files into it -- a
      real autonomy win that completes the organise workflow
- [x] Give `path` (the folder to create, e.g. 'Documents/Taxes'); intermediate
      parent folders are created too. The model may instead pass a bare `name`
      plus a separate `parent` folder -- both are handled
- [x] Rooted in the user's home only (shares `find_files`' containment via
      `organize._resolve_under_home`): a path outside home is REJECTED (including
      a `..`-escape, which is resolved and re-checked), so Jarvis can never create
      a folder in `C:\Windows` or outside the user's own folders
- [x] Never destructive: an existing folder is a friendly no-op (not an error),
      and a path that already exists as a FILE is refused rather than overwritten;
      the home folder itself is never "created". Bounded: a path nested deeper
      than `MAX_NEW_DEPTH` (12) is refused so one hallucinated call can't spawn an
      absurdly deep tree
- [x] Hardened vs 8B hallucinations: empty/whitespace/missing args rejected,
      wrong types coerced, alt arg names accepted (`name`/`directory`/`dir`/
      `folder`/`dest`/...), all output forced to pure ASCII -- never raises, never
      crashes the agent
- [x] Agent system prompt now steers "make/create a folder" to `make_folder`
      (and to make one first when it needs somewhere to move files into); the
      console "Try:" line suggests "make a folder called taxes in documents"
- [x] `tests/smoke.py makefolder` (in the safe set) covers creating a nested
      folder (parents too), the parent+bare-name shape, the existing-folder
      no-op, refusing to clobber a file, alt arg names, the containment guard
      (absolute AND `..`-escape), the depth cap, ASCII-only output, and the
      empty/whitespace/missing/wrong-type guards

### Phase 24 — Folder / disk usage (2026-07-30)
- [x] `folder_size` tool (`jarvis/tools/disk.py`): the "how much space is this
      using?" member of the file family. The navigation tools LOCATE a file,
      organise REARRANGES it, archive backs it up / restores it, and recycle
      removes it -- but Jarvis had no idea which folder was eating the disk. Now
      it can answer "how big is my Downloads folder", "what's taking up space in
      Documents", "how much space is my Desktop using" and report the total size,
      the file count, and the biggest items inside -- a real autonomy win, and
      read-only so it can never change anything
- [x] Give an optional `folder` (like 'Downloads'); with no folder it measures
      the whole home folder. Pointed at a single file it just reports that file's
      size. The biggest first-level items (subfolders + files) are listed
      newest-largest-first with human sizes (B/KB/MB/GB/TB)
- [x] Rooted in the user's home only (shares `find_files`' containment via
      `organize._resolve_under_home`): a path outside home -- including a
      `..`-escape, which is resolved and re-checked -- is REJECTED, so Jarvis can
      never measure `C:\Windows` or all of `C:\`; system/heavy dirs pruned
      (AppData, node_modules, .git, ...) so the total is relevant and the scan fast
- [x] Bounded everywhere: caps on walk depth, entries visited, and a hard
      wall-clock time budget -- a pathological "size everything" stops early with a
      clear note instead of hanging the agent; un-stat-able / permission-blocked
      files are skipped, never crash
- [x] Hardened vs 8B hallucinations: no args is valid (whole home), wrong-type
      `folder` coerced, alt arg names accepted (`path`/`directory`/`dir`/...), a
      missing folder reported as a friendly message, all output forced to pure
      ASCII -- never raises, never changes anything
- [x] Agent system prompt now steers "how big / what's taking up space" to
      `folder_size`; the console "Try:" line suggests "how big is my downloads
      folder"
- [x] `tests/smoke.py disk` (in the safe set) covers the happy path (exact total
      + file count with a pruned `node_modules` excluded + biggest-first
      ordering), the whole-home default, a single-file size, an empty folder, alt
      arg names, the containment guard (absolute AND `..`-escape), the missing-
      folder message, ASCII-only output, and the wrong-type / extra-arg guards

### Phase 25 — Open / reveal a folder in Explorer (2026-07-30)
- [x] `open_folder` tool (`jarvis/tools/explorer.py`): the "show me that" member
      of the file family. The navigation tools LOCATE a file, organise REARRANGES
      it, archive backs it up / restores it, recycle removes it and folder_size
      reports what is eating the disk -- but after all that the user still had to
      go and open the folder by hand. Now Jarvis can pop it open ("open my
      Downloads folder", "show me that folder in Explorer", "reveal that file")
      and, pointed at a file, opens the file's folder with the file highlighted --
      a real autonomy win, and the natural follow-up after folder_size flags a
      heavy folder
- [x] Give an optional `folder` (like 'Downloads') or a file path (like
      'Desktop/report.pdf'); with nothing it opens the home folder. A folder is
      opened in a new Explorer window; a file is revealed (its folder opens with
      the file selected)
- [x] Rooted in the user's home only (shares `find_files`' containment via
      `organize._resolve_under_home`): a path outside home -- including a
      `..`-escape, which is resolved and re-checked -- is REJECTED and nothing is
      launched, so Jarvis can never fling open `C:\Windows` or all of `C:\`
- [x] Read-only (opening a window never moves/writes/deletes anything); the
      actual launch is isolated in a fixed-argv, `shell=False` `_reveal` helper so
      a hallucinated path can never become a shell command (and the smoke test can
      swap in a hermetic fake -- no window ever pops up during tests)
- [x] Hardened vs 8B hallucinations: no args is valid (home), wrong-type `folder`
      coerced, alt arg names accepted (`path`/`directory`/`dir`/`file`/...), a
      missing target and an OS launch failure both surface as friendly messages,
      all output forced to pure ASCII -- never raises, never changes anything
- [x] Agent system prompt now steers "open / show / reveal that folder or file"
      to `open_folder` (and to use it after folder_size flags a heavy folder); the
      console "Try:" line suggests "open my downloads folder"
- [x] `tests/smoke.py explorer` (in the safe set) covers opening a folder,
      revealing a file (highlighted), the whole-home default, alt arg names, the
      containment guard (absolute AND `..`-escape, with nothing launched), the
      missing-target message, the OS-launch-failure guard, ASCII-only output, and
      the wrong-type / extra-arg guards. The real Explorer launch is swapped for a
      hermetic fake, so no window ever opens during the test

### Phase 26 — Move / rename a whole folder (2026-07-30)
- [x] `move_folder` tool (`jarvis/tools/organize.py`, alongside move_file/
      copy_file/make_folder): the organise family could move/rename a single FILE
      and CREATE a folder, but not move an existing FOLDER. move_file refuses a
      folder source, so "move my Taxes folder into Documents" or "rename my
      Projects folder to Archive" was impossible. Now Jarvis can relocate or
      rename a whole tree -- a real autonomy win that pairs with make_folder
- [x] Give source (the folder) and dest: dest can be a folder to move it INTO,
      or a bare new name/path to rename it to (a bare name renames it inside its
      own parent). A move within the user's folders is a fast rename
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`):
      BOTH the source folder AND the destination are rejected unless they live
      inside the user's home, so Jarvis can never move a folder into `C:\Windows`
      or drag one out of the user's own folders; the home folder itself is never
      moved
- [x] Never destructive: an existing destination folder is never overwritten OR
      merged into (refused, so no silent clobber). **A folder is never moved into
      one of its own subfolders** (`src in target.parents` is refused) -- the
      classic footgun that would lose or endlessly nest the tree. Files are
      refused (points the model at move_file), destination depth is capped
      (`MAX_NEW_DEPTH`, 12)
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`from`/`to`/`into`/`directory`/...), a
      bare new name sanitised of path parts, missing source and file source
      reported as friendly messages, all output forced to pure ASCII -- never
      raises, never crashes the agent
- [x] Auto-registers via the already-present `organize` import in `app.py`; the
      agent system prompt steers "move/rename a whole FOLDER" to move_folder (vs
      move_file for a single file); the console "Try:" line suggests "move my
      taxes folder into documents"
- [x] `tests/smoke.py movefolder` (in the safe set) covers move-into-folder,
      rename-in-place, the never-overwrite/merge guard, refusing to move a folder
      into its own subfolder, refusing a file source, refusing to move the home
      folder, alt arg names, the containment guard, the missing-source message,
      ASCII-only output, and the empty/missing/wrong-type guards

### Phase 27 — Copy a whole folder (2026-07-30)
- [x] `copy_folder` tool (`jarvis/tools/organize.py`, alongside move_file/
      copy_file/make_folder/move_folder): the organise family could COPY a single
      file (`copy_file`) and MOVE a whole folder (`move_folder`), but not copy a
      whole folder. Now Jarvis can duplicate an entire tree ("copy my Taxes folder
      into Backups", "duplicate my Projects folder", "make a copy of my notes
      folder") -- the natural partner to move_folder and the backup counterpart to
      copy_file
- [x] Give source (the folder) and dest: dest can be a folder to copy it INTO, or
      a bare new name/path for the copy. The original is always left exactly where
      it is
- [x] Rooted in the user's home only (shares `organize._resolve_folder_pair` ->
      `_resolve_under_home`): BOTH the source folder AND the destination are
      rejected unless they live inside the user's home, so Jarvis can never copy a
      folder into `C:\Windows` or out of the user's own folders; the home folder
      itself is never copied
- [x] Never destructive: an existing destination folder is never overwritten OR
      merged into (refused), and **a folder is never copied into one of its own
      subfolders** (`src in target.parents` refused) -- the footgun that would
      recurse and duplicate endlessly. A FILE source is refused and points the
      model at copy_file; destination depth is capped (`MAX_NEW_DEPTH`, 12)
- [x] **Bounded on size/count** (a copy duplicates every byte, unlike a move which
      is a rename): the tree is pre-measured (nothing pruned, so the caps are
      honest) and REFUSED before a single byte is written if it exceeds
      `MAX_COPY_FILES` (5000), `MAX_COPY_TREE_BYTES` (500 MB), a walk-depth cap, or
      a wall-clock budget -- a hallucinated "copy everything" can't fill the disk
      or hang. On any copy error the partial copy is removed (target never existed
      before, so only our own bytes are cleared)
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`from`/`to`/`into`/`directory`/...), a
      bare new name sanitised of path parts, missing source and file source
      reported as friendly messages, the file count + total size reported on
      success, all output forced to pure ASCII -- never raises, never crashes
- [x] Auto-registers via the already-present `organize` import in `app.py`; the
      agent system prompt steers "copy/duplicate a whole FOLDER" to copy_folder (vs
      copy_file for a single file); the console "Try:" line suggests "copy my taxes
      folder into backups"
- [x] `tests/smoke.py copyfolder` (in the safe set) covers copy-into-folder
      (original kept), rename-in-place + file-count/size report, the never-
      overwrite/merge guard, refusing to copy a folder into its own subfolder,
      refusing a file source (points at copy_file), refusing the home folder, alt
      arg names, the containment guard, the missing-source message, the size/count
      cap (nothing written when over cap), ASCII-only output, and the
      empty/missing/wrong-type guards

### Phase 28 — Read Word / OpenDocument documents (2026-07-30)
- [x] `read_document` tool (`jarvis/tools/document.py`): a different category from
      the folder-ops family -- document READING. `read_file` only understands
      plain text, so pointed at a Word document it returns a wall of binary zip
      bytes and Jarvis can say nothing useful. Now the model can actually read,
      summarise, and answer questions about the documents the user really has
      ("read my resume", "what does that letter say", "summarise this report") --
      the natural partner to `find_files` (locate the document, then read it)
- [x] Reads Microsoft Word `.docx` AND OpenDocument `.odt`, both of which are a
      ZIP of XML, so it is pure standard library (`zipfile` + `xml.etree`) with NO
      new dependency; give `path` (locate it first with find_files if unknown)
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      path outside home -- including a `..`-escape, resolved and re-checked -- is
      REJECTED, so Jarvis can never read a document from `C:\Windows`
- [x] Bounded everywhere: the file on disk (25 MB), the UNCOMPRESSED document XML
      (60 MB, a zip-bomb guard that refuses a lying/huge part before reading it),
      the paragraph count, and the returned text (10000 chars, truncated with a
      note) are all capped -- a giant or hostile document can't exhaust memory or
      flood the agent's context
- [x] Pure ASCII out, and readable: Word's curly quotes/dashes are transliterated
      and accents stripped (cafe, not caf?) via a punctuation map + NFKD normalise,
      so real Word text reads cleanly and can never corrupt the console/context
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`file`/`document`/`doc`/`source`/...), a
      corrupt/non-zip file, a PDF (steered to "not yet"), a plain-text file
      (steered to read_file), a folder source, a missing file and an empty
      document all surface as friendly messages -- never raises, never crashes
- [x] Auto-registers via a new `document` import in `app.py`; the agent system
      prompt steers "read/summarise that Word document" to read_document (NOT
      read_file); the console "Try:" line suggests "read my resume.docx"
- [x] `tests/smoke.py document` (in the safe set) builds real `.docx`/`.odt` zips
      and covers reading each, the ASCII transliteration (curly quotes/dash/accent
      -> clean ASCII), an empty document, alt arg names, unsupported types (pdf +
      plain text steered elsewhere), a corrupt/non-zip file, the containment guard
      (absolute AND `..`-escape), folder + missing guards, the xml/size caps, the
      truncation note, and the empty/missing/wrong-type guards

### Phase 29 — Count words / measure text (2026-07-30)
- [x] `count_words` tool (`jarvis/tools/textstats.py`): a productivity & text-
      handling tool, a different category from the folder-ops family. The 8B
      model is genuinely bad at counting -- ask it "how many words is my essay"
      or "is my cover letter under 300 words" and it guesses, usually wrong. This
      measures text EXACTLY -- words, characters, characters-without-spaces,
      lines, a rough sentence count, plus estimated reading and speaking-aloud
      time -- so Jarvis answers length questions the way `calculate` answers
      arithmetic: with a real number, not a hallucination. An accuracy/autonomy
      win that rounds out the exact-computation family and pairs with
      `find_files`/`read_document` (locate the essay, then size it up)
- [x] Measures EITHER text passed directly ("count the words in this: ...") OR a
      file: a plain-text file (.txt/.md/.csv/...) read straight, or a Word (.docx)
      / OpenDocument (.odt) document whose real text is pulled out by REUSING
      `read_document`'s extractor (no duplicated parsing, no new dependency). A
      file name the model drops into the `text` field by mistake is detected and
      read as a file, so "count the words in essay.txt" still works
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      file path outside home -- including a `..`-escape -- is REJECTED, so it can
      never read a file from `C:\Windows`
- [x] Bounded everywhere: directly-passed text is capped (measured in part with a
      note if over), an over-large file is refused before reading, and the
      document extractor is already zip-bomb bounded -- a giant input can't
      exhaust memory. A PDF is steered to "not yet", and a binary file (by
      extension AND a NUL-byte sniff) is refused rather than counting garbage
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`text`/`content`/`string`/`body` and
      `path`/`file`/`document`/`source`/...), a folder source and a missing file
      surface as friendly messages, output forced to pure ASCII (counts + an
      ASCII-forced file name only) -- never raises, never changes anything
- [x] Auto-registers via a new `textstats` import in `app.py`; the agent system
      prompt steers "how many words / how long is this" to `count_words`; the
      console "Try:" line suggests "how many words is my essay.txt"
- [x] `tests/smoke.py textstats` (in the safe set) covers counting text (words,
      lines, sentences, reading time), a plain-text file, a real `.docx`, the
      filename-in-text detection, refusing PDF + binary + NUL-byte files, the
      containment guard, a folder source + missing file, the over-long-text
      truncation, ASCII-only output, and the empty/missing/wrong-type guards

### Phase 30 — Read / summarise CSV & TSV data files (2026-07-30)
- [x] `read_csv` tool (`jarvis/tools/spreadsheet.py`): structured-data handling,
      a different category from the folder-ops family and a step beyond
      `read_document` (Word/ODT prose). `read_file` only dumps a spreadsheet's raw
      text, so the 8B model was left to eyeball a data file and guess -- and it is
      hopeless at counting rows or columns. Now Jarvis measures a CSV/TSV EXACTLY:
      how many data rows, how many columns, the column names, and a preview of the
      first rows ("how many rows are in my sales data", "what columns are in this
      spreadsheet", "summarise my csv", "show me the first few rows of
      expenses.csv") -- an accuracy/autonomy win and the natural partner to
      `find_files` (locate the sheet, then read it)
- [x] Pure standard library (`csv`): a CSV/TSV is plain text, so NO new
      dependency. Give `path` (locate it first with find_files if unknown) and
      optionally `rows` (how many preview rows to show, default 5). The delimiter
      is taken from the extension (.tsv/.tab -> tab) or sniffed (comma / semicolon
      / tab / pipe) with a cheap fallback
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      path outside home -- including a `..`-escape -- is REJECTED, so it can never
      read a data file from `C:\Windows`
- [x] Bounded everywhere: the file on disk is capped before reading (25 MB), the
      row scan is capped (200k rows, stops early with a note), the `csv`
      field-size limit is clamped so a lying mega-field can't exhaust memory, and
      every listed column name / preview cell is truncated -- a giant or hostile
      file can't flood the agent's context. Blank rows aren't counted so the row
      total stays honest
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`file`/`document`/`source`/...), a
      wrong-type `rows` falls back to the default, an Excel `.xlsx`/`.xls` file is
      steered to "save as CSV", a PDF/binary/NUL-byte file is refused, a folder
      source and a missing file surface as friendly messages, output forced to
      pure ASCII -- never raises, never changes anything (read-only)
- [x] Auto-registers via a new `spreadsheet` import in `app.py`; the agent system
      prompt steers "how many rows / what columns / summarise this CSV" to
      `read_csv`; the console "Try:" line suggests "how many rows are in my
      data.csv"
- [x] `tests/smoke.py spreadsheet` (in the safe set) covers summarising a CSV
      (row/column counts, column names, preview), the `rows` preview arg + default,
      blank rows not counted, a tab-separated `.tsv`, a sniffed semicolon
      delimiter, a header-only file (0 data rows), an empty file, refusing
      Excel + NUL-byte files, the containment guard, a folder source + missing
      file, the row-scan cap (stops early), ASCII-only output, and the
      empty/missing/wrong-type guards

### Phase 31 — Read / summarise JSON & JSON Lines data files (2026-07-30)
- [x] `read_json` tool (`jarvis/tools/jsondata.py`): the next member of the
      structured-data family after Phase 30's `read_csv`. `read_file` only dumps a
      JSON file's raw text and the 8B model is unreliable at eyeballing a wall of
      braces, so Jarvis now parses a JSON file properly and reports its SHAPE
      exactly: the top-level structure (an object with N fields, an array of N
      items, or a single value), the field names and their value types, and a
      short bounded preview ("what's in this json", "how many records are in my
      export", "what fields does this data have", "summarise this json") -- an
      accuracy/autonomy win and the natural partner to `find_files` (locate the
      file, then read it)
- [x] Pure standard library (`json`): JSON is text, so NO new dependency. Give
      `path` (locate it first with find_files if unknown). Line-delimited JSON
      (`.jsonl` / `.ndjson`, one record per line -- common for exports and logs)
      is understood too, and is even detected when a `.json` file turns out to be
      line-delimited
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      path outside home -- including a `..`-escape -- is REJECTED, so it can never
      read a data file from `C:\Windows`
- [x] Bounded everywhere: the file on disk is capped before reading (25 MB), the
      JSONL scan is capped (200k lines, stops early with a note), only so many
      field names are listed (40), and the preview is capped in both characters
      (1200) and lines (30) -- a giant or hostile file can't exhaust memory or
      flood the agent's context. A pathologically deep structure that would
      overflow the parser (`RecursionError`) is caught and reported, not crashed on
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`file`/`document`/`source`/`json`/...), a
      binary/Excel/PDF/image file (by extension) or a NUL-byte file is refused,
      invalid JSON, a folder source and a missing file surface as friendly
      messages, output forced to pure ASCII -- never raises, never changes anything
      (read-only)
- [x] Auto-registers via a new `jsondata` import in `app.py`; the agent system
      prompt steers "what's in / how many records / what fields / summarise this
      JSON" to `read_json`; the console "Try:" line suggests "what's in my
      export.json"
- [x] `tests/smoke.py jsondata` (in the safe set) covers summarising an object
      (fields + types + preview), an array of objects, an array of scalars, a
      top-level scalar, a `.jsonl` file (blank line skipped), the JSONL fallback
      for a line-delimited `.json`, an empty file, invalid JSON, the deep-nesting
      guard, refusing binary + NUL-byte files, the containment guard, a folder
      source + missing file, the JSONL scan cap, ASCII-only output, and the
      empty/missing/wrong-type guards

### Phase 32 — Delete a whole folder to the Recycle Bin (2026-07-30)
- [x] `recycle_folder` tool (`jarvis/tools/recycle.py`, alongside `recycle_file`):
      the delete member of the file family was files-only -- `recycle_file` refuses
      a folder -- so "delete that whole folder", "remove my old Projects folder",
      "bin the Temp folder" was impossible. Now Jarvis can bin a whole tree the same
      safe way it bins a file, completing the delete family and pairing with
      move_folder/copy_folder. Closes the "recycling whole folders" item in Future
      work
- [x] **Never a permanent delete.** The folder (and everything in it) is sent to
      the Windows Recycle Bin (`FOF_ALLOWUNDO`, reusing `recycle_file`'s
      `_send_to_recycle_bin` -- ctypes, no new dependency), so the whole tree can be
      restored. There is still no hard-delete path anywhere in the module
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      folder outside home -- including a `..`-escape, resolved and re-checked -- is
      REJECTED, and the **home folder itself is refused**, so one hallucinated path
      can never bin the user's entire home or anything in `C:\Windows`
- [x] The right tool for the shape: `recycle_folder` refuses a FILE and points the
      model at `recycle_file` (and `recycle_file` now refuses a folder and points at
      `recycle_folder`), so neither can be tricked into the other's job
- [x] Bounded before any delete: the tree is pre-measured (`_measure_folder`,
      bounded on file count (20000) and a wall-clock budget) and REFUSED if it holds
      too many files or is over the Recycle-Bin size cap (`MAX_RECYCLE_BYTES`, 1 GB)
      -- Windows permanently deletes items too big for the bin, so an oversized
      folder is left untouched rather than risking an un-undoable delete. Success
      only claimed after confirming the folder actually left its place; the file
      count + total size are reported
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`folder`/`source`/`directory`/`dir`/...), a
      missing folder and an OS-level failure surface as friendly messages, all
      output forced to pure ASCII -- never raises, never crashes the agent
- [x] Auto-registers via the already-present `recycle` import in `app.py`; the
      agent system prompt steers "delete a whole FOLDER" to `recycle_folder` (vs
      `recycle_file` for a single file); the console "Try:" line suggests "delete my
      old projects folder"
- [x] `tests/smoke.py recycle` (in the safe set) gains recycle_folder coverage:
      the happy path (whole tree binned + recoverable + honest file count), an empty
      folder, alt arg names, refusing a file (steered to recycle_file), refusing the
      home folder, the containment guard, the missing-folder message, the size cap
      and file-count cap (folder kept when over cap), the OS-failure guard,
      ASCII-only output, and the empty/missing/wrong-type guards. The real Recycle
      Bin call stays swapped for the hermetic fake, so the test is deterministic and
      never touches the user's real bin

### Phase 33 — Find duplicate files (2026-07-31)
- [x] `find_duplicates` tool (`jarvis/tools/duplicates.py`): a tidy-up / free-space
      member of the file family. The family can LOCATE a file, REARRANGE it, back it
      up / restore it, remove it and report folder usage (`folder_size`) -- but the
      everyday "am I keeping the same file twice?" question was unanswerable, and an
      8B model can't spot it by name (two identical photos often have different
      names). Now Jarvis finds files whose CONTENTS are byte-for-byte identical,
      groups them, and reports how much space the extra copies waste ("find
      duplicate files", "am I storing anything twice", "what duplicates are in my
      Downloads", "clean up duplicate photos") -- a real autonomy win, read-only, and
      the natural companion to `folder_size` (what's big) and `recycle_file` (remove
      a copy)
- [x] Fast AND correct: two files can only be identical if they are the same size,
      so files are grouped by size first and only same-size groups are actually
      hashed; a match is a streamed content hash (`hashlib.blake2b` over the whole
      file), so identical means the bytes really are identical, not just the size.
      Pure standard library -- NO new dependency
- [x] Give an optional `folder` (like 'Downloads' or 'Pictures'); with no folder it
      checks the whole home folder. Duplicate sets are ranked by the space that
      could be reclaimed (the copies beyond the first), and each set lists the copies
      by their home-relative paths
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      folder outside home -- including a `..`-escape, resolved and re-checked -- is
      REJECTED, so Jarvis can never scan `C:\Windows` or all of `C:\`; system/heavy
      dirs pruned (AppData, node_modules, .git, ...)
- [x] Read-only -- it never moves, renames or deletes anything; it points the user
      at `recycle_file` to remove a copy (an undoable Recycle-Bin delete)
- [x] Bounded everywhere: caps on walk depth, entries visited, files hashed, a
      per-file size cap, a total-bytes-hashed cap and a hard wall-clock budget -- a
      pathological "de-dupe everything" stops early with a clear note instead of
      hanging the agent or reading the disk to death; empty (0-byte) files are
      ignored so they can't pile up as bogus "duplicates"; un-readable / vanished
      files are skipped
- [x] Hardened vs 8B hallucinations: no args is valid (whole home), wrong-type
      `folder` coerced, alt arg names accepted (`path`/`directory`/`dir`/...), a file
      source and a missing folder surface as friendly messages, all output forced to
      pure ASCII -- never raises, never changes anything
- [x] Auto-registers via a new `duplicates` import in `app.py`; the agent system
      prompt steers "find duplicates / am I storing anything twice / clean up
      duplicate photos" to `find_duplicates`; the console "Try:" line suggests "find
      duplicate files in my downloads"
- [x] `tests/smoke.py duplicates` (in the safe set) covers finding content
      duplicates across different names/folders (with reclaimable-space total +
      biggest-set-first ordering), ignoring a same-size-but-different-content pair
      and empty files, dir pruning, the whole-home default, the no-duplicates
      message, alt arg names, the containment guard (absolute AND `..`-escape), a
      file source + missing folder, ASCII-only output, and the wrong-type / extra-arg
      guards

### Phase 34 — Facts about a single file (2026-07-31)
- [x] `file_info` tool (`jarvis/tools/fileinfo.py`): the file family could LOCATE a
      file, REARRANGE it, back it up / restore it, remove it, measure a whole
      FOLDER (`folder_size`) and find files stored twice (`find_duplicates`) -- but
      "tell me about THIS file" was unanswerable. An 8B model guesses (wrongly) at a
      file's size and dates and cannot compute a checksum at all, so `file_info`
      reports the EXACT facts instead ("how big is this file exactly", "when did I
      create this", "when did I last change my resume", "is this file read-only",
      "what's the checksum of this download"). Same philosophy as `calculate` /
      `convert_units` / `count_words`: a real number, not a hallucination. Read-only,
      the natural companion to `find_files` (locate, then describe)
- [x] Reports the type (friendly label from the extension), the exact size (human
      size + byte count), the created and last-modified dates (each with a human
      "how long ago" phrase, reusing `recent_files`' `_ago`), the read-only flag
      (real Windows attribute, falling back to a write probe), a line + word count
      for text files, and the SHA-256 checksum so the user can verify a download
- [x] Pure standard library (`hashlib`, `os.stat`), NO new dependency
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      path outside home -- including a `..`-escape, resolved and re-checked -- is
      REJECTED, so Jarvis can never read a file under `C:\Windows`. A FOLDER is
      refused and the model is steered to `folder_size`
- [x] Bounded: the checksum is streamed and skipped (with a note) for a file over
      `MAX_HASH_BYTES` (400 MB) so a giant file can't hang the agent; the line/word
      count reads at most `MAX_TEXT_BYTES` (20 MB) and notes a partial count;
      line/word counts are only attempted for text (binary by extension OR a
      NUL-byte sniff is not counted)
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`file`/`source`/`document`/`doc`/...), a
      missing file surfaced as a friendly message, all output forced to pure ASCII
      -- never raises, never changes anything (read-only)
- [x] Auto-registers via a new `fileinfo` import in `app.py`; the agent system
      prompt steers "facts about ONE specific file" to `file_info` (vs `folder_size`
      for a whole folder); the console "Try:" line suggests "tell me about my
      resume.docx"
- [x] `tests/smoke.py fileinfo` (in the safe set) covers the exact type/size/line
      count/date/checksum facts (checksum verified against `hashlib`), a binary file
      getting no line count, an empty file, the read-only flag, alt arg names, the
      checksum size cap and the text-read cap (both via a temporary cap shrink), the
      containment guard (absolute AND `..`-escape), a folder source steered to
      folder_size, a missing file, ASCII-only output, and the empty/missing/
      wrong-type guards. Full safe set: 243 checks, all PASS

### Phase 35 — Get one value out of a JSON file (2026-07-31)
- [x] `get_json_value` tool (`jarvis/tools/jsondata.py`, alongside `read_json`):
      the next data step flagged in Future work ("query a nested value by key
      path, e.g. 'get models.chat'"). `read_json` SUMMARISES a whole JSON file;
      this pulls out ONE value by its key path so the model doesn't have to
      eyeball a preview and guess ("what's the chat model in my config", "get
      models.chat from settings.json", "what is the first user's email", "what's
      the total in this json"). Pure standard library -- NO new dependency
- [x] Give `path` (the file; find it with find_files first if unknown) and `key`,
      a dotted key path where dots descend into objects and numbers pick a list
      position, so both `users.0.email` and `items[2].price` work; a quoted
      bracket key (`data["a b"]`) and a JSONPath-ish `$.` prefix are tolerated
- [x] No duplicated parsing: `read_json`'s file resolve/validate/parse was
      extracted into a shared `_load_value(raw)` that BOTH tools call (same
      home-containment, size/NUL/binary/JSONL handling and messages -- read_json's
      existing checks all still pass)
- [x] Rooted in the user's home only (shares `organize._resolve_under_home` via
      `_load_value`): a path outside home -- including a `..`-escape -- is
      REJECTED, so it can never read a file from `C:\Windows`
- [x] Bounded: the key path is length-capped (`MAX_KEYPATH_LEN`, 200) and
      step-count-capped (`MAX_TOKENS`, 40); the returned value's rendering reuses
      read_json's bounded, ASCII-forced preview/field-list/scalar helpers, so a
      huge value can't flood the agent's context
- [x] Helpful when it can't resolve the path: a missing key lists the AVAILABLE
      fields so the 8B model can self-correct; an out-of-range list index, trying
      to descend past a scalar, an empty/missing key, wrong-type args and alt arg
      names (`file`/`field`/`keypath`/...) all return friendly, pure-ASCII
      messages. Read-only; never raises
- [x] Auto-registers via the already-present `jsondata` import in `app.py`; the
      agent system prompt steers "get ONE value out of a JSON file" to
      get_json_value (vs read_json to summarise); the console "Try:" line suggests
      "get models.chat from my config.json"
- [x] `tests/smoke.py jsondata` gains 6 get_json_value checks: a dotted scalar
      (incl. bool + number), a list position via both dot and `[n]` syntax, a
      value that is an object/list described + previewed, the missing-key (lists
      available) / out-of-range / can't-descend-past-scalar guards, ASCII output +
      the containment guard, and the empty-key / missing-file / wrong-type /
      alt-name / extra-arg guards. Full safe set: 249 checks, all PASS

### Phase 36 — Compare two text files (2026-07-31)
- [x] `compare_files` tool (`jarvis/tools/compare.py`): the file family could
      LOCATE a file, REARRANGE it, back it up / restore it, remove it, measure a
      folder (`folder_size`), find files stored twice (`find_duplicates`) and
      report the exact facts about one file (`file_info`). `find_duplicates` can
      say two files are byte-for-byte IDENTICAL, but nothing could say what is
      DIFFERENT between two specific files -- and an 8B model can't eyeball two
      documents and reliably report the changes. Now Jarvis can ("did this file
      change", "what's different between my draft and the final", "compare
      config.yaml and config.backup", "are these two notes the same") -- read-only,
      the natural companion to `find_files` (locate two files, then diff them) and
      `file_info` (facts about one file, differences between two)
- [x] Reports whether the two text files are identical or different and, when they
      differ, exactly how many lines were added and removed plus a short, bounded
      preview of the changed lines (unified-diff style, `- from the first, + from
      the second`). Pure standard library (`difflib`), NO new dependency
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): BOTH
      paths -- including a `..`-escape, resolved and re-checked -- are REJECTED
      unless inside the user's home, so Jarvis can never read a file under
      `C:\Windows` or outside the user's own folders
- [x] Text only: a binary file (by extension OR a NUL-byte sniff, reusing
      `fileinfo._is_binary`) is refused rather than dumping a meaningless byte diff;
      a folder source is refused too, and a same-path-twice call is a friendly note
- [x] Bounded everywhere: each file is size-capped before it is read (5 MB), the
      number of lines compared is capped (200k), and the changed-line preview is
      capped in both count (40 lines) and per-line length (200 chars) -- a giant or
      hostile file can't exhaust memory or flood the agent's context
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`first`/`second`/`old`/`new`/`a`/`b`/...),
      a missing file surfaced as a friendly message, output forced to pure ASCII
      (real UTF-8 curly quotes/accents transliterated) -- never raises, read-only
- [x] Auto-registers via a new `compare` import in `app.py`; the agent system
      prompt steers "what changed between these two files / compare X and Y" to
      `compare_files` (file_info for facts about ONE file, compare_files for the
      differences between TWO); the console "Try:" line suggests "compare my
      draft.txt and final.txt"
- [x] `tests/smoke.py compare` (in the safe set) covers a real diff (exact
      added/removed counts + the changed lines in the preview), identical content,
      UTF-8 -> ASCII output, the same-file-twice note, alt arg names, a refused
      binary file, the containment guard (absolute AND `..`-escape, for both
      files), a folder source + missing file, the size cap, ASCII-only output, and
      the empty/missing/wrong-type guards. Full safe set: 259 checks, all PASS

### Phase 37 — Read PDF documents (2026-07-31)
- [x] `read_pdf` tool (`jarvis/tools/pdf.py`): completes document READING. Phase 28
      added `read_document` for Word/ODT but it deliberately REFUSED a `.pdf`, yet a
      PDF is the single most common document a real user has (resumes, letters,
      bank statements, reports). Now Jarvis pulls the text out of a PDF so it can
      read, summarise or answer questions about it ("read my resume.pdf",
      "summarise this report", "what does this letter say") -- a real autonomy win
      and the natural partner to `find_files` (locate the PDF, then read it)
- [x] **First dependency added under the updated policy:** `pypdf` (pinned in
      `requirements.txt`) -- a well-established, PURE-PYTHON, offline package (no
      compiler, no binary wheel, no network; installed clean as
      `pypdf-6.14.2-py3-none-any.whl`). It is imported LAZILY inside the tool, so
      Jarvis's startup pays nothing, and if it is ever missing the tool degrades to
      a friendly "install pypdf" message instead of crashing. Jarvis stays fully
      local/offline
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      path outside home -- including a `..`-escape, resolved and re-checked -- is
      REJECTED, so Jarvis can never read a PDF from `C:\Windows`
- [x] Bounded everywhere: the file on disk (40 MB), the pages walked (500), a
      wall-clock extraction budget (20 s), and the returned text (10000 chars,
      truncated with a note) are all capped -- a giant or pathological PDF can't
      exhaust memory, hang, or flood the agent's context; a page that won't extract
      is skipped, not fatal
- [x] Handles the real-world PDF cases gracefully: a password-protected PDF (an
      empty password is tried first, then reported), a scanned/image-only PDF (no
      text -> "it may be a scanned document" rather than a blank answer), and a
      corrupt/non-PDF file are all friendly messages, not crashes. pypdf's own
      warnings AND logging ("invalid pdf header", "EOF marker not found") are
      silenced so a bad PDF is never console noise
- [x] Pure ASCII out (reuses read_document's transliterator): curly quotes/dashes/
      accents become clean ASCII (cafe, not caf?). Alt arg names accepted
      (`file`/`document`/`doc`/`source`/`pdf`/...), a Word/ODT file steered to
      read_document, a plain-text file to read_file, wrong-type/empty/missing args
      coerced or rejected -- never raises
- [x] Auto-registers via a new `pdf` import in `app.py`; the agent system prompt
      steers "read/summarise that PDF" to `read_pdf` (read_pdf for .pdf,
      read_document for .docx/.odt); `read_document`'s old "can't read PDFs yet"
      message now points at read_pdf; the console "Try:" line suggests "read my
      resume.pdf"
- [x] `tests/smoke.py pdf` (in the safe set) builds a real minimal PDF by hand (no
      writer dependency) and covers reading it, the ASCII transliteration, a
      no-text/scanned PDF, alt arg names, a password-protected PDF, a corrupt/non-
      PDF file, the truncation note, the graceful missing-dependency message
      (forced regardless of environment), non-PDF types steered elsewhere, the
      containment guard (absolute AND `..`-escape), folder + missing guards, and the
      empty/missing/wrong-type guards. The PDF-parsing checks are GUARDED behind
      pypdf being importable so the safe set passes clean either way. Full safe set:
      271 checks, all PASS

### Phase 38 — Read Excel .xlsx workbooks (2026-07-31)
- [x] `read_excel` tool (`jarvis/tools/excel.py`): the Excel counterpart to
      Phase 30's `read_csv` and the "Structured data next" item in Future work.
      `read_csv` handles plain-text CSV/TSV but REFUSES a binary Excel workbook
      (it told the user to "save it as CSV") -- yet a spreadsheet is exactly the
      kind of file a real user keeps in Excel (budgets, expenses, contact lists,
      exports). Now Jarvis reads a `.xlsx` directly and measures it EXACTLY: how
      many sheets, and for a chosen sheet how many data rows and columns, the
      column names, and a preview of the first rows ("how many rows are in my
      workbook.xlsx", "what columns are in my budget", "read sheet 2", "summarise
      my expenses spreadsheet") -- the natural partner to `find_files`
- [x] **Second dependency added under the updated policy:** `openpyxl` (pinned in
      `requirements.txt`) -- a well-established, PURE-PYTHON, offline package (no
      compiler, no binary wheel, no network; installed clean as
      `openpyxl-3.1.5-py2.py3-none-any.whl` + pure-Python `et-xmlfile`). Imported
      LAZILY inside the tool so startup pays nothing; a missing dep degrades to a
      friendly "install openpyxl" message instead of crashing. Jarvis stays
      fully local/offline. Fresh checkout: `.venv\Scripts\python -m pip install
      openpyxl` (or `-r requirements.txt`)
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      path outside home -- including a `..`-escape, resolved and re-checked -- is
      REJECTED, so Jarvis can never read a workbook from `C:\Windows`
- [x] Bounded everywhere: the file on disk (25 MB) is capped before opening, the
      workbook is opened in openpyxl's streaming READ-ONLY mode (bounded memory
      on a huge sheet), the row scan is capped (200k, stops early with a note),
      and every listed sheet/column name and preview cell is truncated -- a giant
      or hostile file can't exhaust memory or flood the agent's context. A fully
      blank row isn't counted so the data-row total stays honest
- [x] `sheet` picks a worksheet by NAME or 1-based NUMBER (default the first);
      an unknown sheet lists the real sheet names so the model can self-correct.
      Cell values are rendered cleanly: an integral float shows as an int
      (1200 not 1200.0), a midnight datetime shows as a plain date, and text is
      transliterated to readable ASCII (reuses read_document's transliterator:
      cafe not caf?, straight quotes not curly)
- [x] Handles the real-world cases gracefully, never crashes: a corrupt/non-xlsx
      or password-protected workbook -> friendly message; an old binary `.xls` ->
      steered to "save as .xlsx"; a `.csv`/`.tsv` -> steered to read_csv; any
      other extension refused. openpyxl's warnings are silenced so a quirky
      workbook is never console noise. Alt arg names (`file`/`workbook`/
      `spreadsheet`/`tab`/...), wrong-type/empty/missing args coerced or rejected
- [x] Auto-registers via a new `excel` import in `app.py`; the agent system prompt
      steers "read/summarise that Excel workbook / how many rows in my .xlsx" to
      `read_excel` (read_excel for .xlsx, read_csv for .csv/.tsv); `read_csv`'s old
      "save as CSV" message now points at read_excel; the console "Try:" line
      suggests "how many rows are in my budget.xlsx"
- [x] `tests/smoke.py excel` (in the safe set) builds a real workbook with
      openpyxl and covers summarising it (sheets/rows/columns/preview), the ASCII
      transliteration, int/float/date cell formatting, the `rows` preview arg,
      sheet selection by name AND number + the missing-sheet guard, alt arg names,
      a corrupt workbook, the row-scan cap, the graceful missing-dependency
      message (forced regardless of environment), non-xlsx types steered
      elsewhere (.csv/.xls/.txt), the containment guard (absolute AND `..`-escape),
      folder + missing guards, and the empty/missing/wrong-type guards. The
      workbook-parsing checks are GUARDED behind openpyxl being importable so the
      safe set passes clean either way. Full safe set: 284 checks, all PASS

### Phase 39 — Convert a data file between CSV and JSON (2026-07-31)
- [x] `convert_data` tool (`jarvis/tools/convertdata.py`): text/data
      TRANSFORMATION -- a new category. The data family could READ files
      (`read_csv`, `read_json`, `read_excel`) but never TRANSFORM one, and turning
      a CSV into JSON (or JSON back into a spreadsheet a person can open in Excel)
      is an everyday chore an 8B local model cannot do reliably by hand (it would
      hallucinate rows, drop fields, mangle quoting). Now Jarvis does it exactly
      ("convert my data.csv to json", "turn this json into a csv so I can open it
      in Excel", "export my contacts.json as csv") -- the natural next step after
      the reading family and the partner to `find_files`
- [x] Pure standard library (`csv` + `json`), NO new dependency. CSV/TSV -> JSON:
      the first row is the header, each later row becomes a JSON object (an array
      of objects, or one object per line if the output is `.jsonl`). JSON/JSONL ->
      CSV: an array of objects (or a single object, or an array of scalars) becomes
      a spreadsheet -- columns are the union of the object keys, one row per record.
      Written UTF-8 with a BOM so Excel opens accents correctly. CSV values stay
      strings (never guesses a number, so a zip code like '007' isn't corrupted)
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`):
      BOTH the source AND the destination -- including a `..`-escape, resolved and
      re-checked -- are REJECTED unless inside the user's home, so Jarvis can never
      read from or write into `C:\Windows` or outside the user's own folders
- [x] Never overwrites (an existing destination is refused; the output can never
      be the source itself); **atomic write** (to a `.part` temp then `os.replace`,
      and the temp is cleaned up on failure) so a crash never leaves a half-written
      file. Bounded: file size (25 MB), row count (200k) and column count (2000) are
      all capped and the conversion is REFUSED before writing anything if a cap is
      exceeded -- a giant/hostile file can't exhaust memory, fill the disk, or leave
      a misleading partial file
- [x] Hardened vs 8B hallucinations: empty/missing/wrong-type args coerced or
      rejected, alt arg names accepted (`file`/`from`/`input`/`to`/`output`/...),
      an Excel `.xlsx` steered to read_excel/"save as CSV", a non-tabular JSON
      scalar refused with a clear reason, an unknown output extension refused, a
      same-format ("CSV to CSV") request refused, a folder/missing/empty source
      answered -- the tool's reply is pure ASCII (the written file keeps the real
      UTF-8 data). Never raises
- [x] Auto-registers via a new `convertdata` import in `app.py`; the agent system
      prompt steers "convert/turn/export this data file to the other format" to
      `convert_data` (transforms the file, unlike read_csv/read_json which only
      summarise); the console "Try:" line suggests "convert my data.csv to json"
- [x] `tests/smoke.py convertdata` (in the safe set) reads back the WRITTEN files:
      CSV -> JSON array of objects (blank row not counted, values kept as strings),
      JSON -> CSV (union columns + UTF-8 BOM + bool rendering), a `.jsonl` output,
      an array of scalars -> single 'value' column, alt arg names, the never-
      overwrite guard, the same-format + non-tabular + unknown-dest-extension
      refusals, an empty source, the containment guard (source AND dest, absolute
      AND `..`-escape), folder + missing guards, the row cap (nothing written when
      over cap), ASCII-only reply, and the empty/missing/wrong-type guards. Full
      safe set: 300 checks, all PASS

### Phase 40 — Extract items (emails / links / phones / IPs / numbers) (2026-07-31)
- [x] `extract_items` tool (`jarvis/tools/textextract.py`): a productivity /
      text-handling win in a category well away from the (now complete)
      document- and structured-data-reading families. Pulling every email
      address, link, phone number, IP or number out of a block of text is an
      everyday chore an 8B local model does badly -- it silently drops some,
      invents others, or mangles the formatting. Now Jarvis harvests them EXACTLY
      with real pattern matching, de-duplicates them and lists them ("get all the
      email addresses from this", "pull the links out of my clipboard", "find all
      the phone numbers in this document"). Pairs with `get_clipboard` (harvest
      what the user just copied) and `find_files`/`read_document` (locate a doc,
      then pull out its contacts/links)
- [x] Pure standard library (`re`), NO new dependency. Give `kind` (emails, urls,
      phones, ips, or numbers -- many spellings/aliases mapped) and EITHER `text`
      (given directly) OR `path` (a plain-text file, or a Word .docx / OpenDocument
      .odt document, reusing `count_words`/`read_document`'s bounded, binary-sniffed
      reader -- no duplicated parsing). A filename dropped into the `text` field is
      detected and read as a file
- [x] Correct, not naive: URLs have trailing punctuation stripped; phone
      candidates are validated (7-15 digits AND a real separator/`+`, so a bare
      digit run is treated as a number not a phone); IP octets are range-checked
      (`999.1.1.1` rejected); results are de-duplicated (case-insensitively for
      emails/urls) in first-seen order
- [x] Rooted in the user's home only (shares `organize._resolve_under_home`): a
      file path outside home -- including a `..`-escape -- is REJECTED, so it can
      never read a file from `C:\Windows`
- [x] Bounded everywhere: directly-passed text capped (searched in part + noted if
      over), an over-large/binary/PDF file refused before reading, the number of
      listed items capped (200, with an "and N more" summary), and every item
      length-bounded + forced to pure single-line ASCII -- a giant or hostile input
      can't exhaust memory or flood the agent's context. Read-only; never raises
- [x] Hardened vs 8B hallucinations: an unknown/empty/missing `kind` returns a
      friendly message listing the supported kinds so the model self-corrects;
      empty/missing source, wrong-type args, a folder source and a missing file all
      surface as friendly ASCII messages; alt arg names accepted
      (`type`/`what`/`content`/`input`/`file`/`document`/...)
- [x] Auto-registers via a new `textextract` import in `app.py`; the agent system
      prompt steers "get/pull/list all the emails/links/phone numbers" to
      `extract_items`; the console "Try:" line suggests "pull the email addresses
      out of my clipboard"
- [x] `tests/smoke.py textextract` (in the safe set) covers extracting emails
      (de-duped), urls (trailing punctuation stripped, alias mapped), phones
      (validated, bare digit run excluded), ips (out-of-range octets rejected) and
      numbers (decimals/negatives/commas, de-duped), reading a plain-text file and
      a real `.docx`, the filename-in-text detection, the no-match + unknown-kind
      messages, alt arg names, the containment guard (absolute AND `..`-escape),
      folder + missing + PDF/binary refusals, the over-long-text truncation, the
      item-count cap, ASCII-only output, and the empty/missing/wrong-type guards.
      The sandbox is pid-tagged so concurrent smoke runs never collide. Full safe
      set: 318 checks, all PASS. No new dependency

## Known limits of v1
- Vision uses `moondream` (small) because qwen2.5vl:3b needs ~8.4 GB free
  RAM; descriptions are basic. Swap `vision:` in config.yaml if RAM frees up.
- Chat model unloads/reloads when vision runs (limited RAM) → "what do you
  see" has a few seconds of extra delay, and the next chat reply too.
- 8B local model: fine for essays/files/apps, patient-but-imperfect at
  multi-step browser tasks.
- Voice wake/STT tested to init + mic level only — real "Hey Jarvis"
  conversation needs a human test; tune `ENERGY_THRESHOLD` in
  `jarvis/voice/stt.py` if it cuts you off or never stops listening.

## Future work
- [ ] Human voice test + threshold tuning: watch the orb's mic bar move as
      you speak; if "Hey Jarvis" is still missed, lower `voice.wake_threshold`
      (e.g. 0.3); tune `ENERGY_THRESHOLD` in `stt.py` if it cuts you off
- [ ] Better voice: Piper or Kokoro TTS (natural Jarvis-like voice)
- [ ] Streaming responses + barge-in (interrupt Jarvis while he talks)
- [ ] Arabic support: whisper handles Arabic (`stt_language: ar`), test TTS
      voices; make Jarvis bilingual
- [ ] Face recognition ("it's you" vs "unknown person") — opt-in
- [ ] Watch multiple cameras at once; small live dashboard window
- [x] Memory: let Jarvis edit/replace a fact (not just add/forget) — done in
      Phase 16 (`update_fact`)
- [ ] Memory next steps: surface remembered facts in the HUD; let recall/update
      fuzzy-match wording, not just substrings
- [x] File management: move/rename/copy a located file -- done in Phase 19
      (`move_file`/`copy_file`)
- [x] File management: back up / archive files into a .zip -- done in Phase 20
      (`zip_files`); whole folders can be zipped too
- [x] File management: an `unzip`/extract counterpart to zip_files -- done in
      Phase 21 (`unzip_files`); extracts into a home folder, zip-slip proof,
      never overwrites
- [x] File management: opt-in delete-to-Recycle-Bin -- done in Phase 22
      (`recycle_file`); undoable (Windows Recycle Bin), files-only, size-capped,
      home-contained, no permanent-delete path
- [x] File management: create a new folder to organise into -- done in Phase 23
      (`make_folder`); home-contained, depth-capped, never overwrites a file
- [x] File management: report folder / disk usage -- done in Phase 24
      (`folder_size`); read-only, home-contained, pruned + bounded, lists the
      biggest items so the user knows what to tidy
- [x] File management: move/rename a whole FOLDER -- done in Phase 26
      (`move_folder`); home-contained, never overwrites/merges, never moves a
      folder into its own subfolder, depth-capped, file source points at move_file
- [x] File management: copy a whole FOLDER -- done in Phase 27 (`copy_folder`);
      home-contained, never overwrites/merges, never copies a folder into its own
      subfolder, depth-capped, pre-measured + bounded on size/count (500 MB / 5000
      files), file source points at copy_file
- [x] File management: recycling whole folders -- done in Phase 32
      (`recycle_folder`); an undoable Recycle-Bin send that refuses the home folder,
      steers a file source to recycle_file, and is size/count aware (pre-measured,
      1 GB / 20000-file caps, refused before any delete)
- [x] Disk-usage next: an `open_folder` tool (reveal a folder in Explorer) so
      after folder_size flags a heavy folder the user can jump straight to it --
      done in Phase 25 (`open_folder`); read-only, home-contained, reveals a file
      highlighted, hermetic-tested (no window opens in tests)
- [x] Document reading: read Word `.docx` / OpenDocument `.odt` documents (not
      just plain text) -- done in Phase 28 (`read_document`); pure stdlib (no dep),
      home-contained, zip-bomb bounded, ASCII-transliterated
- [x] Productivity / text handling: count words / measure text length -- done in
      Phase 29 (`count_words`); exact word/char/line/sentence counts + reading &
      speaking time, on pasted text OR a plain-text/Word/ODT file; home-contained,
      bounded, reuses read_document's extractor, ASCII-only
- [x] Structured data: read / summarise a CSV or TSV data file -- done in Phase 30
      (`read_csv`); pure stdlib (no dep), exact row/column counts + column names +
      a preview, delimiter sniffed, home-contained, bounded (file size / row scan /
      field size / cell truncation), Excel steered to CSV, ASCII-only
- [x] Structured data: read / summarise a JSON or JSON Lines data file -- done in
      Phase 31 (`read_json`); pure stdlib (no dep), reports the structure (object
      with N fields / array of N items / scalar), field names + value types and a
      bounded preview, understands `.jsonl`/`.ndjson` (and detects line-delimited
      `.json`), home-contained, bounded (file size / JSONL scan / keys listed /
      preview chars+lines / deep-nesting), ASCII-only
- [x] File management: find duplicate files to tidy up / free space -- done in
      Phase 33 (`find_duplicates`); pure stdlib (no dep), content-based (size-group
      then `hashlib.blake2b`, so identical names aren't required), read-only, reports
      reclaimable space + points at recycle_file, home-contained, pruned + bounded
      (files hashed / per-file size / total bytes / wall-clock), ignores empty files
- [x] File management: report the exact facts about a single file -- done in
      Phase 34 (`file_info`); pure stdlib (no dep), read-only, reports type / exact
      size / created + modified dates / read-only flag / line + word count (text) /
      SHA-256 checksum; home-contained, bounded (checksum + text-read caps), folder
      source steered to folder_size, ASCII-only
- [x] Productivity / text handling: compare two text files and report what changed
      -- done in Phase 36 (`compare_files`); pure stdlib (`difflib`, no dep),
      read-only, reports identical/different + added/removed line counts + a bounded
      changed-line preview, home-contained (both paths), text-only (binary refused),
      bounded (file size / lines / preview), ASCII-only
- [x] Structured data: an Excel `.xlsx` reader -- done in Phase 38 (`read_excel`);
      the second added dependency under the policy (`openpyxl`, pure-Python/offline,
      imported lazily so startup pays nothing and a missing dep degrades to a
      friendly message). Reports sheet names + a chosen sheet's rows/columns/preview
      exactly; `sheet` picks by name or number; home-contained, bounded (file size /
      streaming read-only / row scan / cell truncation), ASCII-transliterated,
      handles corrupt/password-protected/.xls gracefully; read_csv now steers a .xlsx
      here
- [x] Structured data: query a nested value inside a JSON file by key path
      (e.g. 'get models.chat') -- done in Phase 35 (`get_json_value`); pure stdlib
      (no dep), reuses read_json's shared loader, dotted/bracket key paths,
      home-contained, key-path length/step bounded, lists available fields on a
      miss, ASCII-only
- [x] Document reading next: a PDF reader -- done in Phase 37 (`read_pdf`); the
      first added dependency under the updated policy (`pypdf`, pure-Python/offline,
      imported lazily so startup pays nothing and a missing dep degrades to a
      friendly message). Home-contained, bounded (file size / pages / wall-clock /
      returned chars), ASCII-transliterated, handles password-protected + scanned +
      corrupt PDFs gracefully; read_document now steers a .pdf here
- [x] Text/data transformation: convert a data file between CSV and JSON -- done
      in Phase 39 (`convert_data`); pure stdlib (no dep), CSV/TSV <-> JSON/JSONL,
      home-contained (source AND dest), never overwrites, atomic write, bounded
      (file size / rows / columns, refused before writing a partial file), ASCII
      reply / real-UTF-8 file, handles non-tabular JSON + Excel + unknown types
      gracefully
- [x] Productivity / text handling: extract emails / links / phone numbers / IPs /
      numbers from text or a file -- done in Phase 40 (`extract_items`); pure stdlib
      (no dep), real pattern matching + de-dup + validation (phone digit-count,
      IP octet range), home-contained, bounded (text/file size, items listed, item
      length), reuses count_words' file reader, ASCII-only; pairs with get_clipboard
- [ ] Vision upgrade path: qwen2.5vl:3b (needs free RAM) or RAM upgrade
- [ ] Autostart with Windows + system tray icon
- [ ] Phone notifications on watch-mode alerts (e.g. ntfy.sh)
- [ ] Home automation hooks (lights, plugs) if smart devices arrive
- [ ] Bigger brain when hardware allows (qwen3:14b/30b)
