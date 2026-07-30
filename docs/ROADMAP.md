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
- [ ] File management next: opt-in delete-to-Recycle-Bin (needs a safe
      confirm/undo path, e.g. send2trash); moving whole folders with move_file
- [ ] Vision upgrade path: qwen2.5vl:3b (needs free RAM) or RAM upgrade
- [ ] Autostart with Windows + system tray icon
- [ ] Phone notifications on watch-mode alerts (e.g. ntfy.sh)
- [ ] Home automation hooks (lights, plugs) if smart devices arrive
- [ ] Bigger brain when hardware allows (qwen3:14b/30b)
