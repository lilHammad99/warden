# HANDOFF — Jarvis build status (2026-07-30)

Read this first if you are a new Claude session taking over.

## What this project is

Local Iron-Man-style AI assistant in `path\to\jarvis`
(git repo, 2 commits). Owner: the user. Everything local: Ollama brain,
camera vision, voice, file/app/system/browser tools.
See `docs/DESIGN.md` (architecture) and `docs/ROADMAP.md` (future work).
The old GitHub repos in the parent folder (`Jarvis-master`, *.zip) are
reference only — do not touch them.

## Environment facts

- Windows, Python 3.11, venv at `.venv` (use `.venv\Scripts\python.exe`)
- Ollama installed. Models: `llama3:8b` (old), `qwen2.5vl:3b` (vision,
  DOWNLOADED ✅), `qwen3:8b` (brain, was ~50% downloading — check with
  `ollama list`; if missing run `ollama pull qwen3:8b`)
- Dev machine: consumer laptop, mid-range GPU, memory-constrained
- git identity set locally (the user / you@example.com)

## State when this file was last updated (2026-07-29, end of build session)

v1 COMPLETE AND SMOKE-TESTED. All downloads/installs done (qwen3:8b,
moondream, pip deps, Chromium, wake-word models, Whisper small, YOLO
weights). All smoke tests pass:
imports/tools/agent/camera/vision/tts/watch/e2e — see `tests/smoke.py`.
E2E verified: agent wrote a real Desktop file, started/stopped watch
mode, browser opened+read+clicked pages, app boots with voice on.

IMPORTANT deviation from original design: vision model is `moondream`,
NOT qwen2.5vl:3b — that one failed with "requires 8.4 GiB, available
~7.2" on this dev machine. Also `describe_frame` unloads the chat
model first and uses `keep_alive=0` (RAM can't hold both models).

NOT yet human-tested: actually saying "Hey Jarvis" into the mic (init +
mic-level verified only). First thing next session: have the user try voice,
tune `ENERGY_THRESHOLD` in `jarvis/voice/stt.py` if needed.

## 2026-07-30 — Listening UX (Phase 5)

the user reported wake word often missed + no feedback + feels laggy. Added a
floating "Jarvis orb" HUD and wake tuning. See
`docs/superpowers/specs/2026-07-30-jarvis-listening-hud-design.md`.

- `jarvis/voice/hud.py` — `Hud` thread draws a borderless, always-on-top
  Tkinter orb (color = state) + live mic-level bar; drag to move. `create(cfg)`
  returns a `_NullHud` no-op if disabled or Tk can't open (voice still works).
  Runs via `root.update()` in a 40 ms loop (no blocking mainloop), all Tk
  calls on the hud thread only.
- `wake.py` / `stt.py` gained an optional `on_level(0..1)` callback → mic bar.
- `voice.wake_threshold` now in config (default 0.4, was hardcoded 0.5).
- `loop.py` sets orb state per phase; `app.py` creates/reflects/shuts it down.
- `tests/smoke.py hud` passes (window drew, ok=True). STILL not human-tested
  with a real "Hey Jarvis" — that + threshold tuning is the next step.
- Chosen (brainstorm): keep qwen3:8b brain; did NOT swap to a faster model.

## 2026-07-30 — Search inside files (Phase 15)

Added `search_files` (`jarvis/tools/search.py`): content search INSIDE files,
the natural complement to `find_files` (which matches names). Model can now
answer "which note has the wifi password", "find where I wrote about the
budget" and get the matching files + lines with line numbers.
- Reuses `find_files`' home-containment check and `_SKIP_DIRS` (imported from
  `.find`), so it can never grep outside the user's home or into system/heavy
  dirs. Text only: binary by extension AND NUL-byte sniff, >2 MB files skipped.
  Bounded on depth/files/entries/matches + wall-clock budget. Matched lines are
  forced to single-line bounded pure ASCII. Never raises.
- Wired into `app.py` imports, agent system prompt (when to use search_files
  vs find_files), and the console "Try:" line.
- `tests/smoke.py search` added to the safe set (happy path, line numbers,
  case-insensitive/nested, name filter, pruning, binary skip, ASCII-only,
  containment + hallucination guards). Full safe set: 45 tools, all PASS.

## 2026-07-30 — Update a remembered fact (Phase 16)

Added `update_fact` (`jarvis/tools/memory.py`, alongside remember/recall/forget):
the model can CORRECT or replace an existing fact instead of storing a second,
contradicting one ("actually my wifi password changed to ...", "my meeting moved
to Tuesday"). Closes the top memory item in ROADMAP Future work.
- Args `old` (a few words identifying the existing fact) + `new` (corrected
  wording). Single match -> replaced in place (count unchanged, ts refreshed),
  reflected instantly in `recall` and the injected preamble. Mirrors `forget`'s
  safety: several matches -> nothing changes + matches listed; no match -> told
  to use `remember`; `new` duplicating a DIFFERENT fact -> old dropped, no dup.
- Hardened like the rest: empty old/new rejected, over-long `new` truncated
  (MAX_FACT_LEN), wrong types coerced, no-op reported, atomic `_save`, corrupt
  recovery inherited. Never raises.
- Wired into the agent system prompt (steer "X changed/was wrong" to update_fact)
  and the console "Try:" line. `tests/smoke.py memory` (safe set) gains two
  update_fact checks (happy path + guards). Full safe set: 45 tools, all PASS.

## 2026-07-30 — Unit converter (Phase 17)

Added `convert_units` (`jarvis/tools/convert.py`): exact unit conversion, the
natural third member of the exact-computation family after `calculate` (numbers)
and the date tools (calendar). The 8B model is unreliable at conversions, so it
can now answer "how many km is 5 miles", "convert 32 F to C", "how many ml in a
cup", "60 mph in km/h", "2 GB to MB" exactly.
- Pure stdlib, no new dependency. Categories: length, mass, volume, temperature,
  time, speed, area, data. Linear categories convert via a factor to a per-
  category base unit; temperature is special-cased (affine, via Celsius).
- Hardened like the rest: unknown units refused (allowlist + plural fallback),
  cross-category conversions refused, value magnitude capped (non-finite/1e400
  rejected), unit/phrase strings length-bounded, wrong types coerced. Forgiving:
  accepts `from`/`to` as well as `from_unit`/`to_unit`, and parses a whole phrase
  ("5 miles to km") dumped into one field. Never raises; output pure ASCII.
- Wired into `app.py` imports, agent system prompt (steer "convert X to Y"), and
  the console "Try:" line ("convert 5 miles to km").
- `tests/smoke.py convert` added to the safe set (happy path, affine temperature,
  forgiving input, cross-category + unknown-unit guards, magnitude/overflow
  guards, wrong-type shapes, ASCII-only). Full safe set: 47 tools, all PASS.

## 2026-07-30 — Recently changed files (Phase 18)

Added `recent_files` (`jarvis/tools/recent.py`): the third member of the file-
navigation family after `find_files` (by NAME) and `search_files` (by CONTENT) --
it searches by TIME. The model can now act on what the user last touched
("open the file I was just editing", "what did I work on today", "what did I
change this week"), listing the most recently modified files newest-first with a
human "how long ago" phrase.
- Reuses `find_files`' `_resolve_root` (home-containment), `_SKIP_DIRS` and
  `_coerce` (imported from `.find`), so it can never crawl outside home or into
  system/heavy dirs. Optional `days` window (default 7), `folder`, and `name`
  glob. Bounded on depth/scan/results + wall-clock budget. `days` is coerced and
  clamped (junk/negative/non-finite -> default, absurd -> capped, "3 days"
  phrase parsed). Paths forced to pure ASCII. No required args (no args = whole
  home, last week). Never raises.
- Wired into `app.py` imports, the agent system prompt (recent_files vs
  find_files/search_files), and the console "Try:" line ("what did I work on
  today").
- `tests/smoke.py recent` added to the safe set (happy path + newest-first
  ordering, days window, name filter, pruning, ASCII-only, containment guard,
  no-match message, hallucination guards). Full safe set: 48 tools, all PASS.

## 2026-07-30 — Move, rename & copy files (Phase 19)

Added `move_file` + `copy_file` (`jarvis/tools/organize.py`): the ACTION half of
the file tools. find_files/search_files/recent_files let Jarvis LOCATE a file
but it could only read/open it; now it can organise what it finds ("move the
budget into Documents", "rename my resume to CV.pdf", "make a copy of my notes").
- `move_file` moves a file into a folder OR renames it (a bare new name renames
  inside the file's own folder); `copy_file` duplicates and keeps the original.
  Deleting is deliberately NOT offered.
- Reuses `find_files`' home-containment idea via a local `_resolve_under_home`:
  BOTH source and destination must live inside the user's home, so it can never
  move a file into `C:\Windows` or out of the user's folders. Never overwrites
  (refuses if the destination exists); files only; `copy_file` has a 500 MB cap
  (`org.MAX_COPY_BYTES`). Forgiving to 8B quirks: accepts from/to/path/new_name
  aliases (via **extra), coerces wrong types, sanitises a bare new name of path
  parts. All output forced to pure ASCII; never raises.
- Wired into `app.py` imports + the console "Try:" line, and the agent system
  prompt (move_file/copy_file after the find/search/recent bullet).
- `tests/smoke.py organize` added to the safe set (move-into-folder, rename in
  place, copy keeps original, never-overwrite, alt arg names, containment guard,
  missing-source + folder-source messages, copy size cap, ASCII-only, and the
  empty/missing/wrong-type guards). Full safe set: 44 tools (50 with browser),
  all PASS.

## 2026-07-30 — Back up / archive files (Phase 20)

Added `zip_files` (`jarvis/tools/archive.py`): the backup member of the file
tools. find/search/recent LOCATE a file and move/copy REARRANGE it; this bundles
files up so the user can back them up or send them on ("back up my Documents into a
zip", "zip my resume and cv", "make an archive of the report"). Originals stay
put.
- Zips a single file, several files (list OR comma/newline string), or a whole
  folder (walked, `_SKIP_DIRS` pruned); entries stored relative to home so no
  absolute path leaks. Reuses `organize._resolve_under_home` so BOTH every
  source AND the destination `.zip` must live inside home -- can't read
  `C:\Windows` or write outside the user's folders.
- Never overwrites an existing `.zip`; missing `.zip` suffix added; written to a
  `.part` temp then `os.replace`-d in (atomic, no half-written archive). Bounded:
  5000 files / 500 MB uncompressed / depth / wall-clock caps; unreadable files
  skipped + counted. Forgiving arg names (`files`/`paths`/`from`/`to`/`name`/...)
  and list-shaped sources. Pure ASCII out. Never raises.
- Wired into `app.py` imports + the console "Try:" line, and the agent system
  prompt (zip_files after the move/copy bullet).
- `tests/smoke.py archive` added to the safe set (zip-a-folder with noise pruned
  + originals kept, zip-several-files + auto `.zip` suffix, alt arg names,
  never-overwrite, containment for source AND dest, total-size cap with no
  partial archive, ASCII-only, and the empty/missing/wrong-type/list-shape
  guards). Full safe set: 51 tools with browser (45 without), all PASS.

## 2026-07-30 — Unzip / extract archives (Phase 21)

Added `unzip_files` (`jarvis/tools/extract.py`): the restore/unpack counterpart
to `zip_files`. zip bundles files IN; this opens one back UP ("unzip my backup",
"extract downloaded.zip into Documents", "open that archive"). Closes the last
file-management loop (locate -> rearrange -> back up -> restore).
- `source` (the `.zip`) + optional `dest` folder; default is a new folder named
  after the archive, beside it. The archive is always left in place.
- Reuses `organize._resolve_under_home` so BOTH the source `.zip` AND the dest
  folder must be inside home -- can't read an archive from `C:\Windows` or write
  outside the user's folders. **Zip-slip proof**: each entry is rebuilt from
  sanitised parts (a `..` component is rejected + skipped, drive letters/leading
  slashes neutralised) and re-checked to stay inside dest, so `..\..\evil.exe`
  can never escape (there's a real malicious-zip smoke test).
- Never overwrites (existing target files skipped + counted). Zip-bomb bounded:
  5000 files / 500 MB uncompressed / compression-ratio / depth / wall-clock caps,
  streamed with a running byte cap so a lying header can't fill the disk. Atomic
  per file (`.part` temp then `os.replace`). Corrupt/non-zip, wrong-type, empty,
  missing all -> friendly ASCII strings. Never raises.
- Wired into `app.py` imports + the console "Try:" line ("unzip my backup"), and
  the agent system prompt (unzip_files after the zip_files bullet).
- `tests/smoke.py extract` added to the safe set (default folder, named dest,
  never-overwrite, a REAL zip-slip archive staying inside the folder, containment
  for source AND dest, corrupt zip, alt arg names, ASCII-only, and the
  empty/missing/wrong-type/folder-source guards). Safe set: 103 checks, all PASS
  (46 tools registered without the optional browser module).

## 2026-07-30 — Delete to Recycle Bin (Phase 22)

Added `recycle_file` (`jarvis/tools/recycle.py`): the safe 'delete' member of the
file tools, completing the family (locate -> rearrange -> back up -> restore ->
remove). Jarvis can now act on "delete that draft", "remove the old screenshot",
"bin my notes" -- without ever destroying anything permanently.
- Sends the file to the Windows Recycle Bin (`FOF_ALLOWUNDO` via the Win32 shell
  API `SHFileOperationW`, ctypes -- no new dependency, mirrors the clipboard
  tool), so every delete is undoable. There is deliberately NO hard-delete path.
- Reuses `organize._resolve_under_home` for containment: a file outside the
  user's home is REFUSED, so it can never bin anything in `C:\Windows`. Files
  only (a folder is refused). Size-capped (`MAX_RECYCLE_BYTES`, 1 GB): a file too
  big for the Recycle Bin -- which Windows would delete for good -- is refused,
  never risking a permanent delete. Success is only claimed after confirming the
  file actually left its place; an OS-level failure comes back as a friendly
  message. Alt arg names (`file`/`source`/`path`/...), wrong-type/empty/missing
  args coerced or rejected, output pure ASCII. Never raises.
- Wired into `app.py` imports + the console "Try:" line ("delete that old draft
  to the recycle bin"), and the agent system prompt (recycle_file after the
  unzip_files bullet, stressing undoable + single-file only).
- `tests/smoke.py recycle` added to the safe set: the real Recycle Bin call is
  swapped for a hermetic fake (moves the file into a sandbox trash folder), so
  the test is deterministic and never touches the user's real bin. Covers happy
  path (removed + recoverable), alt arg names, containment, folder refusal,
  missing source, size cap, OS-failure guard, ASCII-only, and the
  empty/missing/wrong-type guards. Full safe set: 106 checks, all PASS
  (53 tools registered with the optional browser module).

## 2026-07-30 — Create folders (Phase 23)

Added `make_folder` (`jarvis/tools/organize.py`, alongside move_file/copy_file):
the missing primitive in the file-organise family. move_file/copy_file could drop
a file INTO a folder but couldn't CREATE one, so "make a folder called Taxes in
Documents" then "move my receipts into it" was impossible. Now Jarvis can make the
destination first and organise into it.
- Arg `path` (e.g. 'Documents/Taxes'); intermediate parents created too. Also
  accepts a bare `name` + separate `parent` folder. Reuses
  `organize._resolve_under_home` so a path outside home -- including a `..`-escape
  (resolved + re-checked) -- is REFUSED; can't create under `C:\Windows`.
- Never destructive: an existing folder is a friendly no-op (not an error); a path
  that already exists as a FILE is refused, never overwritten; the home folder
  itself is never "created". Depth-capped (`MAX_NEW_DEPTH`, 12) so one hallucinated
  call can't spawn an absurdly deep tree. Empty/whitespace/missing args rejected,
  wrong types coerced, alt arg names (`name`/`directory`/`dir`/`folder`/...),
  output pure ASCII. Never raises.
- Auto-registers via the already-present `organize` import in `app.py`; wired into
  the agent system prompt (make_folder after the move/copy bullet, "make one first
  if you need somewhere to move files into") and the console "Try:" line ("make a
  folder called taxes in documents").
- `tests/smoke.py makefolder` added to the safe set: nested-create (parents too),
  parent+name shape, existing-folder no-op, refuse-over-a-file, alt arg names,
  containment (absolute + `..`-escape), depth cap, ASCII-only, and the
  empty/whitespace/missing/wrong-type guards. Full safe set: 121 checks, all PASS.

## 2026-07-30 — Folder / disk usage (Phase 24)

Added `folder_size` (`jarvis/tools/disk.py`): the "how much space is this using?"
member of the file family (locate -> rearrange -> back up -> restore -> remove ->
UNDERSTAND usage). Jarvis can now answer "how big is my Downloads folder", "what's
taking up space in Documents", "how much space is my Desktop using" -- reporting a
folder's total size, its file count, and the biggest items inside so the user
knows what to tidy. Read-only: it never moves, writes or deletes anything.
- Optional `folder` (default = whole home); pointed at a single file it reports
  just that file's size. Reuses `organize._resolve_under_home` for containment
  (a path outside home, incl. a `..`-escape, is REFUSED -> can't measure
  `C:\Windows`) and `find._SKIP_DIRS` to prune AppData/node_modules/.git/... The
  bytes are attributed to each first-level child so the "Biggest inside:" list is
  meaningful. Human sizes (B/KB/MB/GB/TB), pure ASCII.
- Bounded: depth / entries-scanned / wall-clock caps; a broad scan stops early
  with a clear note. Wrong-type/alt-name (`path`/`directory`/`dir`/...) args
  coerced; missing folder -> friendly message. Never raises, never mutates.
- Wired into `app.py` imports + the console "Try:" line ("how big is my downloads
  folder"), and the agent system prompt (folder_size after the recycle_file bullet).
- `tests/smoke.py disk` (safe set): exact total + file count with a pruned
  `node_modules` excluded + biggest-first ordering, whole-home default, single-
  file size, empty folder, alt arg names, containment (absolute + `..`-escape),
  missing-folder message, ASCII-only, wrong-type/extra-arg guards. Full safe set:
  130 checks, all PASS.

## 2026-07-30 — Open / reveal a folder in Explorer (Phase 25)

Added `open_folder` (`jarvis/tools/explorer.py`): the "show me that" member of the
file family. After the family LOCATES / rearranges / backs up / removes a file and
folder_size flags what's eating the disk, this pops the folder open in Windows
Explorer ("open my Downloads folder", "show me that folder", "reveal that file").
Pointed at a file it opens the file's folder with the file highlighted. The natural
follow-up after folder_size.
- Optional `folder` (or a file path); no args = home folder. A folder is opened in
  a new window (`os.startfile`); a file is revealed (`explorer /select,<path>`).
- Reuses `organize._resolve_under_home` for containment: a path outside home
  (incl. a `..`-escape, resolved + re-checked) is REFUSED and nothing is launched.
  Read-only -- never moves/writes/deletes. The OS launch is isolated in a fixed-
  argv, `shell=False` `_reveal(path, is_file)` helper (a hallucinated path can't
  become a shell command, and the smoke test swaps in a hermetic fake so no window
  opens). Missing target + OS launch failure -> friendly ASCII messages. Wrong-type
  / alt-name (`path`/`directory`/`dir`/`file`/...) args coerced. Never raises.
- Wired into `app.py` imports + the console "Try:" line ("open my downloads
  folder"), and the agent system prompt (open_folder after the folder_size bullet).
- `tests/smoke.py explorer` (safe set): open-a-folder, reveal-a-file (highlighted),
  whole-home default, alt arg names, containment (absolute + `..`-escape, nothing
  launched), missing target, OS-launch-failure guard, ASCII-only, wrong-type/extra-
  arg guards -- via a hermetic fake so no real window opens. Full safe set: 139
  checks, all PASS.

## 2026-07-30 — Tool-count note

Tool-count note (the fluctuating figure): NOT a registry bug. The registry holds
exactly one entry per `@tool`-decorated function. The printed number only swings
on whether the OPTIONAL `browser` module imports at count time (it adds 6):
after Phase 25 that is 50 without browser, 56 with (55 + `open_folder`). No
tools are being silently dropped.

## How to test (in order)

```
cd "path\to\jarvis"
.venv\Scripts\python -m tests.smoke safe     # imports + tools, no models
.venv\Scripts\python -m tests.smoke agent    # needs qwen3:8b downloaded
.venv\Scripts\python -m tests.smoke camera   # webcam frame grab
.venv\Scripts\python -m tests.smoke vision   # webcam + qwen2.5vl:3b
.venv\Scripts\python -m tests.smoke tts      # speaks out loud
```

Then end-to-end: `run.bat` → try `what time is it`, `make a file on my
desktop...`, `start working`, `what do you see`, voice "Hey Jarvis".

## Architecture crib sheet

- `jarvis/agent.py` — Ollama tool-calling loop (`think=False`, num_ctx 8192,
  max 8 tool rounds, thread-lock shared by console+voice)
- `jarvis/tools/registry.py` — `@tool(name, desc, schema)` decorator;
  importing a tool module registers its tools; errors returned as strings
- `jarvis/tools/` — files, apps, system, web, camera, browser
  - browser.py: Playwright sync API lives on its own thread (queue of
    actions) because sync API is thread-bound
- `jarvis/vision/` — cameras.py (webcam index or RTSP URL from config.yaml),
  watcher.py (motion gate → YOLOv8n person → speak + snapshot, cooldown 30 s),
  describe.py (frame → qwen2.5vl)
- `jarvis/voice/` — tts.py (pyttsx3 on dedicated thread, fresh engine per
  utterance), stt.py (faster-whisper small int8 CPU, energy-based VAD),
  wake.py (openWakeWord `hey_jarvis_v0.1`, onnx), loop.py (wake→listen→
  agent→speak)
- `config.yaml` — models, cameras (add RTSP cams here), voice, app aliases
- User-visible entry: `run.bat`

## Known risks / likely first bugs

- qwen3:8b tool-calling format quirks; if it loops or ignores tools, try
  `qwen2.5:7b-instruct` or `llama3.1:8b` in config.yaml.
- ollama-python `think=False` needs a recent ollama lib (agent has a
  TypeError fallback).
- openwakeword on Windows: must use `inference_framework="onnx"` (done) and
  models must be downloaded first (see TODO above). Wake model name may be
  `hey_jarvis_v0.1` or `hey jarvis` depending on version — check
  `openwakeword.models` dir if init fails.
- pycaw volume + comtypes: may need `comtypes.CoInitialize()` when called
  from agent thread — wrap set_volume if it errors.
- Webcam may be busy/permission-blocked; smoke camera test reveals it.
- VoiceLoop echo: Jarvis may hear its own TTS; speaking-event guard exists
  but may need tuning.

## What the user asked for (requirements)

1. Jarvis-like AI, fully local brain (Ollama) ✅ designed
2. "start working" → watch cameras (webcam now, IP/RTSP later), alert on
   person + describe on demand ✅ coded
3. Voice ("Hey Jarvis") + text console ✅ coded
4. Agentic abilities: write files/essays on Desktop, open apps/sites,
   system control, web answers, HEADED browser Jarvis controls ✅ coded
5. Update Claude memory when done + keep ROADMAP.md current ⬅ REMEMBER
6. User is not deeply technical: keep instructions simple, README friendly.

## Immediate next steps for whoever takes over

1. Wait/verify downloads (`ollama list`; pip job; see TODO above)
2. Run smoke tests in order, fix what breaks
3. Update ROADMAP.md checkboxes + HANDOFF.md as things pass
4. Write Claude memory files (project + user preferences) per memory rules
5. Tell the user how to start Jarvis (`run.bat`) and what to try
