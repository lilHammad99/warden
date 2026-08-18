# HANDOFF — Jarvis build status (2026-07-31)

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

## 2026-07-30 — Move / rename a whole folder (Phase 26)

Added `move_folder` (`jarvis/tools/organize.py`, alongside move_file/copy_file/
make_folder): the organise family could rearrange a single FILE and CREATE a
folder, but not move an existing FOLDER (move_file refuses a folder source). Now
Jarvis can relocate or rename a whole tree ("move my Taxes folder into
Documents", "rename my Projects folder to Archive") -- the natural partner to
make_folder.
- `source` (the folder) + `dest` (a folder to move INTO, or a bare new name/path
  to rename to). A move within home is a fast rename (`shutil.move`).
- Reuses `organize._resolve_under_home`: BOTH source AND dest must be inside home
  (can't touch `C:\Windows` or leave the user's folders); the home folder itself
  is never moved. Folder-specific hardening beyond move_file: never overwrites OR
  merges into an existing dest folder, and **never moves a folder into one of its
  own subfolders** (`src in target.parents` refused -- the footgun that loses/
  nests the tree). A FILE source is refused and points the model at move_file;
  dest depth capped (`MAX_NEW_DEPTH`, 12). Alt arg names (`from`/`to`/`into`/
  `directory`/...), wrong-type/empty/missing args coerced or rejected, output
  pure ASCII. Never raises.
- Auto-registers via the already-present `organize` import in `app.py`; wired
  into the agent system prompt (move_folder for a whole folder vs move_file for a
  single file) and the console "Try:" line ("move my taxes folder into
  documents").
- `tests/smoke.py movefolder` (safe set): move-into-folder, rename-in-place,
  never-overwrite/merge, refuse-into-own-subfolder, refuse-file-source, refuse-
  home-folder, alt arg names, containment, missing source, ASCII-only, and the
  empty/missing/wrong-type guards. Full safe set: 150 checks, all PASS.

## 2026-07-30 — Copy a whole folder (Phase 27)

Added `copy_folder` (`jarvis/tools/organize.py`, alongside move_file/copy_file/
make_folder/move_folder): the organise family could COPY a single file and MOVE a
whole folder, but not copy a whole folder. Now Jarvis can duplicate an entire tree
("copy my Taxes folder into Backups", "duplicate my Projects folder"). The natural
partner to move_folder and the backup counterpart to copy_file. Closes the
"copy_folder counterpart to move_folder, bounded on size/count" item in Future work.
- `source` (the folder) + `dest` (a folder to copy INTO, or a bare new name/path
  to name the copy). The original is always left in place.
- Reuses `organize._resolve_folder_pair` (parametrised so a FILE source now points
  at copy_file, not move_file) -> `_resolve_under_home`: BOTH source AND dest must
  be inside home; home folder never copied; never overwrites/merges an existing
  dest; **never copies a folder into its own subfolder** (`src in target.parents`);
  dest depth capped (`MAX_NEW_DEPTH`, 12).
- **Bounded on size/count** (unlike a move, a copy duplicates bytes): the tree is
  pre-measured by `_measure_tree` (nothing pruned, so caps are honest) and REFUSED
  before writing anything if over `MAX_COPY_FILES` (5000), `MAX_COPY_TREE_BYTES`
  (500 MB), walk depth, or a wall-clock budget. On any copy error the partial copy
  is rmtree'd (target never existed before us, so only our own bytes are cleared).
  Success reports the file count + total size. Alt arg names, wrong-type/empty/
  missing args coerced or rejected, output pure ASCII. Never raises.
- Auto-registers via the already-present `organize` import in `app.py`; wired into
  the agent system prompt (copy_folder for a whole folder vs copy_file for one
  file) and the console "Try:" line ("copy my taxes folder into backups").
- `tests/smoke.py copyfolder` (safe set): copy-into-folder (original kept),
  rename-in-place + count/size report, never-overwrite/merge, refuse-into-own-
  subfolder, refuse-file-source (points at copy_file), refuse-home-folder, alt arg
  names, containment, missing source, the size/count cap (nothing written when
  over cap), ASCII-only, and the empty/missing/wrong-type guards. Full safe set:
  162 checks, all PASS.

## 2026-07-30 — Read Word / OpenDocument documents (Phase 28)

Added `read_document` (`jarvis/tools/document.py`): a DIFFERENT category from the
now well-covered folder-ops family -- document READING. `read_file` only handles
plain text, so pointed at a Word file it returns binary zip bytes; Jarvis can now
actually read/summarise/answer about the documents the user has ("read my
resume", "what does that letter say", "summarise this report"). Natural partner
to `find_files` (locate, then read).
- Reads `.docx` (Word) AND `.odt` (OpenDocument) -- both are a ZIP of XML, so it
  is pure stdlib (`zipfile` + `xml.etree`), NO new dependency. docx text comes
  from `<w:t>` in `word/document.xml`; odt from `<text:p>`/`<text:h>` in
  `content.xml`.
- Reuses `organize._resolve_under_home` for containment (a path outside home,
  incl. a `..`-escape, is REFUSED -> can't read `C:\Windows`). Bounded: file on
  disk 25 MB, UNCOMPRESSED document XML 60 MB (zip-bomb guard, refused before
  read), paragraph count, and returned text 10000 chars (truncated + noted).
- Pure ASCII AND readable: curly quotes/dashes transliterated, accents stripped
  (cafe not caf?) via a punctuation map + NFKD. Corrupt/non-zip, PDF (steered to
  "not yet"), plain-text (steered to read_file), folder source, missing file,
  empty document -> friendly messages. Alt arg names (`file`/`document`/`doc`/
  `source`/...), wrong-type/empty/missing args coerced or rejected. Never raises.
- Wired into `app.py` imports (`from .tools import document`) + the console "Try:"
  line ("read my resume.docx"), and the agent system prompt (read_document for a
  Word/ODT document, NOT read_file).
- `tests/smoke.py document` (safe set) builds real `.docx`/`.odt` zips: reads
  each, the ASCII transliteration, empty document, alt arg names, unsupported
  types (pdf + plain text steered elsewhere), corrupt/non-zip, containment
  (absolute + `..`-escape), folder/missing guards, the xml/size caps (via a
  temporary cap shrink), the truncation note, and the empty/missing/wrong-type
  guards. Full safe set: 174 checks, all PASS.

## 2026-07-30 — Count words / measure text (Phase 29)

Added `count_words` (`jarvis/tools/textstats.py`): a productivity & text-handling
tool, a DIFFERENT category from the well-covered folder-ops family. The 8B model
guesses (wrongly) at "how many words is my essay" / "is this under 300 words";
this measures text EXACTLY -- words, characters, characters-without-spaces, lines,
a rough sentence count, plus reading- and speaking-time estimates -- the way
`calculate` handles arithmetic. Rounds out the exact-computation family and pairs
with `find_files`/`read_document` (locate the essay, then size it up).
- Measures EITHER text passed directly OR a file: plain text (.txt/.md/...) read
  straight, or a Word `.docx` / OpenDocument `.odt` document whose text is pulled
  out by REUSING `read_document`'s extractor (`_extract_docx`/`_extract_odt`/
  `_ascii_body`/`_tidy`) -- no duplicated parsing, no new dependency. A file name
  the model drops into the `text` field is detected (single token, no spaces, has
  a separator/real extension) and read as a file.
- Reuses `organize._resolve_under_home` for containment (a path outside home,
  incl. a `..`-escape, is REJECTED). Bounded: directly-passed text capped
  (measured in part + noted if over), file-on-disk cap, binary refused (extension
  allowlist AND NUL-byte sniff), PDF steered to "not yet". Output pure ASCII
  (counts + ASCII-forced file name only). Alt arg names, wrong-type/empty/missing
  coerced or rejected. Never raises.
- Wired into `app.py` imports (`from .tools import textstats`) + the console
  "Try:" line ("how many words is my essay.txt"), and the agent system prompt
  (count_words for "how many words / how long is this", exact not guessed).
- `tests/smoke.py textstats` (safe set): counts text (words/lines/sentences/
  reading time), a plain-text file, a real `.docx`, the filename-in-text
  detection, PDF + binary + NUL-byte refusal, containment, folder + missing
  guards, over-long-text truncation, ASCII-only, and the empty/missing/wrong-type
  guards. Full safe set: 184 checks, all PASS.

## 2026-07-30 — Read / summarise CSV & TSV data files (Phase 30)

Added `read_csv` (`jarvis/tools/spreadsheet.py`): structured-data handling, a
DIFFERENT category from the well-covered folder-ops family and a step beyond
`read_document` (Word/ODT prose). `read_file` only dumps a spreadsheet's raw
bytes and the 8B model is hopeless at counting rows/columns, so Jarvis can now
measure a CSV/TSV EXACTLY -- data-row count, column count, column names, and a
preview of the first rows ("how many rows are in my sales data", "what columns
are in this spreadsheet", "summarise my csv", "show me the first few rows").
Natural partner to `find_files` (locate, then read).
- Pure stdlib (`csv`), NO new dependency. `path` + optional `rows` (preview
  count, default 5). Delimiter from extension (.tsv/.tab -> tab) or sniffed
  (comma/semicolon/tab/pipe) with a cheap fallback; a BOM is stripped. First row
  is treated as the header; blank rows aren't counted so the total is honest.
- Reuses `organize._resolve_under_home` for containment (a path outside home,
  incl. a `..`-escape, is REJECTED -> can't read `C:\Windows`). Bounded: file on
  disk 25 MB, row scan 200k (stops early with a note), `csv.field_size_limit`
  clamped (a lying mega-field can't exhaust memory), every column name / preview
  cell truncated + forced to single-line ASCII.
- Forgiving to 8B quirks: alt arg names (`file`/`document`/`source`/...),
  wrong-type `path`/`rows` coerced or defaulted, an Excel `.xlsx`/`.xls` steered
  to "save as CSV", a PDF/binary/NUL-byte file refused, folder/empty/missing ->
  friendly messages. Read-only; never raises.
- Wired into `app.py` imports (`from .tools import spreadsheet`) + the console
  "Try:" line ("how many rows are in my data.csv"), and the agent system prompt
  (read_csv for a CSV/TSV, after the count_words bullet).
- `tests/smoke.py spreadsheet` (safe set): summarise a CSV (rows/cols/columns/
  preview), the `rows` preview arg + default, blank rows not counted, a `.tsv`, a
  sniffed semicolon delimiter, a header-only file, an empty file, Excel + NUL-byte
  refusal, containment, folder + missing, the row-scan cap, ASCII-only, and the
  empty/missing/wrong-type guards. Full safe set: 197 checks, all PASS.

## 2026-07-30 — Read / summarise JSON & JSON Lines data files (Phase 31)

Added `read_json` (`jarvis/tools/jsondata.py`): the next member of the
structured-data family after Phase 30's `read_csv`. `read_file` only dumps a JSON
file's raw text and the 8B model is unreliable at eyeballing nested braces, so
Jarvis can now PARSE a JSON file and report its shape exactly ("what's in this
json", "how many records are in my export", "what fields does this data have",
"summarise this json").
- Pure stdlib (`json`), NO new dependency. Reports the top-level structure
  (object with N fields / array of N items / a single scalar), the field names
  with their value types, and a bounded preview. Understands line-delimited JSON
  (`.jsonl`/`.ndjson`) AND detects it when a `.json` file is actually
  line-delimited.
- Reuses `organize._resolve_under_home` for containment (a path outside home,
  incl. a `..`-escape, is REJECTED -> can't read `C:\Windows`). Bounded: file on
  disk 25 MB, JSONL scan 200k lines (stops early with a note), 40 field names
  listed, preview capped to 1200 chars / 30 lines. A too-deep structure raises
  `RecursionError` in the parser -- caught and reported, never crashes.
- Forgiving to 8B quirks: alt arg names (`file`/`document`/`source`/`json`/...),
  wrong-type/empty/missing `path` coerced or rejected, a binary/Excel/PDF/image
  file (by extension) or a NUL-byte file refused, invalid JSON / folder / missing
  file -> friendly messages, output pure ASCII (field names + preview forced to
  ASCII). Read-only; never raises.
- Wired into `app.py` imports (`from .tools import jsondata`) + the console "Try:"
  line ("what's in my export.json"), and the agent system prompt (read_json for a
  .json/.jsonl file, after the read_csv bullet).
- `tests/smoke.py jsondata` (safe set): summarise an object (fields/types/preview),
  an array of objects, an array of scalars, a top-level scalar, a `.jsonl` (blank
  line skipped), the JSONL fallback for a line-delimited `.json`, empty file,
  invalid JSON, the deep-nesting guard, binary + NUL-byte refusal, containment,
  folder + missing, the JSONL scan cap, ASCII-only, and the empty/missing/
  wrong-type guards. Full safe set: 212 checks, all PASS.

## 2026-07-30 — Delete a whole folder to the Recycle Bin (Phase 32)

Added `recycle_folder` (`jarvis/tools/recycle.py`, alongside `recycle_file`): the
delete member of the file family was files-only (recycle_file refuses a folder), so
"delete that whole folder", "remove my old Projects folder", "bin the Temp folder"
was impossible. Now Jarvis bins a whole tree the same safe, undoable way it bins a
file -- completing the delete family and pairing with move_folder/copy_folder.
- Sends the folder (and everything in it) to the Windows Recycle Bin (`FOF_ALLOWUNDO`)
  by REUSING recycle_file's `_send_to_recycle_bin` (ctypes, no new dependency);
  SHFileOperation handles a directory as-is. Still no hard-delete path.
- Reuses `organize._resolve_under_home` for containment (a folder outside home,
  incl. a `..`-escape, is REJECTED) and additionally refuses the **home folder
  itself** so one hallucinated path can't bin the user's whole home. A FILE source
  is refused and steered to recycle_file (and recycle_file now steers a folder to
  recycle_folder), so neither tool does the other's job.
- Bounded BEFORE any delete: `_measure_folder` pre-scans the tree (bounded on file
  count 20000 + a 15 s wall-clock budget) and the folder is refused if it has too
  many files or is over `MAX_RECYCLE_BYTES` (1 GB) -- Windows permanently deletes
  items too big for the bin, so an oversized folder is left untouched. Success only
  claimed after confirming the folder actually left; file count + total size
  reported. Alt arg names (`folder`/`source`/`directory`/...), wrong-type/empty/
  missing args coerced or rejected, output pure ASCII. Never raises.
- Auto-registers via the already-present `recycle` import in `app.py`; wired into
  the agent system prompt (recycle_folder vs recycle_file) and the console "Try:"
  line ("delete my old projects folder").
- `tests/smoke.py recycle` gains recycle_folder coverage (happy path with honest
  file count + recoverable tree, empty folder, alt arg names, refuse-a-file,
  refuse-home, containment, missing folder, size cap, file-count cap, OS-failure
  guard, ASCII-only, empty/missing/wrong-type guards) -- via the same hermetic fake
  bin, so it's deterministic and never touches the real Recycle Bin. Full safe set
  all PASS.

## 2026-07-31 — Find duplicate files (Phase 33)

Added `find_duplicates` (`jarvis/tools/duplicates.py`): a tidy-up / free-space
member of the file family. `folder_size` tells the user WHAT is big, but nothing
told them what is stored TWICE -- a real problem for a cluttered Downloads or a
phone-photo dump, and one an 8B model can't spot by name (identical photos often
have different names). Jarvis can now answer "find duplicate files", "am I storing
anything twice", "what duplicates are in my Downloads", "clean up duplicate photos".
- Finds files whose CONTENTS are byte-for-byte identical, groups them, and reports
  how much space the extra copies waste. Fast AND correct: files are grouped by size
  first (identical files must share a size) and only same-size groups are hashed; a
  match is a streamed `hashlib.blake2b` over the whole file, so identical means the
  bytes really match, not just the size. Pure stdlib, NO new dependency.
- Read-only -- never moves/renames/deletes; points the user at `recycle_file` to
  remove a copy (undoable). Reuses `organize._resolve_under_home` (containment: a
  folder outside home, incl. a `..`-escape, is REJECTED) and `find._SKIP_DIRS`
  (AppData/node_modules/.git/... pruned). Optional `folder` (default = whole home);
  sets ranked by reclaimable space, each listing home-relative copy paths.
- Bounded: walk depth / entries visited / files hashed / per-file size cap /
  total-bytes-hashed cap / wall-clock budget -- stops early with a note rather than
  hanging or thrashing the disk. Empty (0-byte) files ignored (no bogus "duplicates");
  un-readable/vanished files skipped. Alt arg names (`path`/`directory`/`dir`/...),
  wrong-type/file-source/missing-folder coerced or answered, output pure ASCII.
  Never raises.
- Wired into `app.py` imports (`from .tools import duplicates`) + the console "Try:"
  line ("find duplicate files in my downloads"), and the agent system prompt
  (find_duplicates after the open_folder bullet, stressing read-only + recycle_file
  to actually remove a copy).
- `tests/smoke.py duplicates` (safe set): content duplicates across different
  names/folders (reclaimable total + biggest-set-first ordering), ignoring a
  same-size/different-content pair AND empty files, dir pruning, whole-home default,
  the no-duplicates message, alt arg names, containment (absolute + `..`-escape), a
  file source + missing folder, ASCII-only, and the wrong-type/extra-arg guards. Full
  safe set: 232 checks, all PASS.

## 2026-07-31 — Facts about a single file (Phase 34)

Added `file_info` (`jarvis/tools/fileinfo.py`): the file family could measure a
whole FOLDER (`folder_size`) and spot files stored twice (`find_duplicates`) but
"tell me about THIS file" was unanswerable. An 8B model guesses a file's size and
dates and can't compute a checksum, so this reports the EXACT facts -- same
philosophy as calculate/convert_units/count_words. Answers "how big is this file
exactly", "when did I create/last change this", "is this file read-only",
"what's the checksum of this download". Read-only; partners with find_files.
- Reports type (friendly label from the extension), exact size (human + bytes),
  created + modified dates (each with a human "how long ago" phrase, reusing
  recent_files' `_ago`), read-only flag (real Windows `st_file_attributes`, else a
  write probe), a line + word count for TEXT files (binary by extension OR a
  NUL-byte sniff isn't counted), and the SHA-256 checksum. Pure stdlib (`hashlib`,
  `os.stat`), NO new dependency.
- Reuses `organize._resolve_under_home` for containment (a path outside home, incl.
  a `..`-escape, is REJECTED -> can't read `C:\Windows`); a FOLDER is refused and
  steered to `folder_size`. Bounded: checksum streamed and skipped with a note over
  `MAX_HASH_BYTES` (400 MB); line/word count reads at most `MAX_TEXT_BYTES` (20 MB)
  and notes a partial count. Alt arg names (`file`/`source`/`document`/...),
  wrong-type/empty/missing args coerced or rejected, output pure ASCII. Never raises.
- Wired into `app.py` imports (`from .tools import fileinfo`) + the console "Try:"
  line ("tell me about my resume.docx"), and the agent system prompt (file_info for
  ONE file vs folder_size for a whole folder).
- `tests/smoke.py fileinfo` (safe set): exact type/size/line-count/date/checksum
  facts (checksum verified against `hashlib`), binary file gets no line count, empty
  file, read-only flag, alt arg names, checksum size cap + text-read cap (temporary
  cap shrink), containment (absolute + `..`-escape), folder source steered to
  folder_size, missing file, ASCII-only, and the empty/missing/wrong-type guards.
  Full safe set: 243 checks, all PASS.

## 2026-07-31 — Get one value out of a JSON file (Phase 35)

Added `get_json_value` (`jarvis/tools/jsondata.py`, alongside `read_json`): the
next data step flagged in Future work ("query a nested value by key path, e.g.
'get models.chat'"). `read_json` SUMMARISES a whole JSON file; this pulls out
ONE value by its key path ("what's the chat model in my config", "get
models.chat from settings.json", "what is the first user's email", "what's the
total in this json"). Pure stdlib, NO new dependency.
- Args `path` (the file) + `key` (a dotted key path). Dots descend into objects,
  numbers pick a list position, so both `users.0.email` and `users[2].price`
  work; a quoted bracket key (`data["a b"]`) and a JSONPath-ish `$.` prefix are
  tolerated. Refactor: read_json's file resolve/validate/parse was extracted into
  a shared `_load_value(raw)` that BOTH tools use (same containment, size/NUL/
  binary/JSONL handling and messages -- read_json's 15 existing checks still
  pass), so there's no duplicated parsing.
- Hardened like the rest: reuses `organize._resolve_under_home` (a path outside
  home, incl. a `..`-escape, is REJECTED -> can't read `C:\Windows`); key path
  length- and step-count-bounded (`MAX_KEYPATH_LEN` 200 / `MAX_TOKENS` 40);
  result rendering reuses read_json's bounded, ASCII-forced `_preview`/`_fields_
  line`/`_scalar`. A missing key lists the AVAILABLE fields so the 8B model can
  self-correct; out-of-range list index, "can't go deeper than a scalar", empty/
  missing key, wrong-type args, alt arg names (`file`/`field`/`keypath`/...) all
  return friendly ASCII. Read-only; never raises.
- Auto-registers via the already-present `jsondata` import in `app.py`; wired into
  the agent system prompt (get_json_value for ONE value vs read_json to summarise)
  and the console "Try:" line ("get models.chat from my config.json").
- `tests/smoke.py jsondata` gains 6 get_json_value checks (dotted scalar incl.
  bool/number, list index via dot AND `[n]`, a value that is an object/list
  described + previewed, missing-key/out-of-range/too-deep-past-scalar guards,
  ASCII + containment, and the empty-key/missing-file/wrong-type/alt-name/extra-
  arg guards). Full safe set: 249 checks, all PASS.

## 2026-07-31 — Compare two text files (Phase 36)

Added `compare_files` (`jarvis/tools/compare.py`): the file family could report a
file's facts (`file_info`) and spot files stored twice (`find_duplicates`, which
says two files are IDENTICAL), but nothing could say what is DIFFERENT between two
specific files -- and an 8B model can't eyeball two documents and report the
changes. Jarvis can now answer "did this file change", "what's different between
my draft and the final", "compare config.yaml and config.backup", "are these two
notes the same". Read-only; partners with find_files (locate two, then diff) and
file_info (facts about one file vs differences between two).
- Reports identical/different and, when different, exactly how many lines were
  added and removed plus a short unified-diff-style preview of the changed lines
  (`- from the first, + from the second`). Pure stdlib (`difflib`), NO new dep.
- Reuses `organize._resolve_under_home` for containment (BOTH paths, incl. a
  `..`-escape, REJECTED outside home) and `fileinfo._is_binary` (binary by
  extension OR NUL-byte sniff refused -- no meaningless byte diff). A folder source
  is refused; a same-path-twice call is a friendly note.
- Bounded: each file size-capped before read (`MAX_FILE_BYTES`, 5 MB), lines
  compared capped (`MAX_LINES`, 200k), preview capped in count (`MAX_PREVIEW_LINES`,
  40) and per-line length (`MAX_LINE_LEN`, 200). Alt arg names (`first`/`second`/
  `old`/`new`/`a`/`b`/...), wrong-type/empty/missing args coerced or rejected,
  output pure ASCII (real UTF-8 curly quotes/accents transliterated). Never raises.
- Wired into `app.py` imports (`from .tools import compare`) + the console "Try:"
  line ("compare my draft.txt and final.txt"), and the agent system prompt
  (compare_files for the differences between TWO files vs file_info for ONE).
- `tests/smoke.py compare` (safe set): a real diff (exact added/removed counts +
  changed lines in the preview), identical content, UTF-8 -> ASCII output, the
  same-file-twice note, alt arg names, a refused binary file, containment
  (absolute + `..`-escape, both files), folder + missing guards, the size cap,
  ASCII-only, and the empty/missing/wrong-type guards. Full safe set: 259 checks,
  all PASS.

## 2026-07-31 — Read PDF documents (Phase 37) [FIRST DEPENDENCY ADDED]

Added `read_pdf` (`jarvis/tools/pdf.py`): completes document READING. Phase 28's
`read_document` reads Word/ODT but deliberately REFUSED a `.pdf`, yet PDFs are the
most common real document a user has (resumes, letters, statements, reports).
Jarvis can now read/summarise/answer about them ("read my resume.pdf", "summarise
this report", "what does this letter say"). Natural partner to `find_files`.
- **Dependency (new, allowed under the updated policy):** `pypdf`, pinned in
  `requirements.txt`. Pure-Python, offline, no compiler/binary wheel (installed
  clean as `pypdf-6.14.2-py3-none-any.whl`, no transitive deps). Imported LAZILY
  inside the tool, so startup is unaffected; if it's ever missing the tool returns
  a friendly "install pypdf" message instead of crashing. Jarvis stays fully
  local/offline. To install on a fresh checkout:
  `.venv\Scripts\python -m pip install pypdf` (or `-r requirements.txt`).
- Reuses `organize._resolve_under_home` for containment (a path outside home,
  incl. a `..`-escape, is REJECTED -> can't read `C:\Windows`) and
  `document._ascii_body`/`_tidy` for readable pure-ASCII output (curly quotes/
  dashes/accents transliterated: cafe not caf?). Bounded: file on disk 40 MB,
  pages walked 500, a 20 s extraction wall-clock budget, returned text 10000 chars
  (truncated + noted). A page that won't extract is skipped, not fatal.
- Real-world PDF cases handled gracefully, never crash: password-protected (empty
  password tried first, then reported), scanned/image-only (no text -> "it may be
  a scanned document"), corrupt/non-PDF. pypdf's warnings AND its logging noise
  ("invalid pdf header", "EOF marker not found") are silenced so a bad PDF never
  reaches the console. Alt arg names (`file`/`document`/`doc`/`source`/`pdf`/...),
  a .docx/.odt steered to read_document, a plain-text file to read_file, wrong-
  type/empty/missing args coerced or rejected. Never raises.
- Wired into `app.py` imports (`from .tools import pdf`) + the console "Try:" line
  ("read my resume.pdf"), and the agent system prompt (read_pdf for .pdf,
  read_document for .docx/.odt). `read_document`'s old "can't read PDFs yet"
  message now steers to read_pdf.
- `tests/smoke.py pdf` (safe set) builds a real minimal PDF by hand (no writer
  dep) and covers reading it, ASCII transliteration, a no-text/scanned PDF, alt
  arg names, a password-protected PDF, a corrupt/non-PDF, the truncation note, the
  graceful missing-dependency message (forced regardless of environment), non-PDF
  types steered elsewhere, containment (absolute + `..`-escape), folder + missing,
  and the empty/missing/wrong-type guards. The PDF-parsing checks are GUARDED
  behind pypdf being importable so the safe set passes clean either way. Full safe
  set: 271 checks, all PASS.

## 2026-07-31 — Read Excel .xlsx workbooks (Phase 38) [SECOND DEPENDENCY ADDED]

Added `read_excel` (`jarvis/tools/excel.py`): the Excel counterpart to Phase 30's
`read_csv` and the "Structured data next" item in ROADMAP Future work. `read_csv`
handles CSV/TSV but REFUSED a binary Excel workbook (steered to "save as CSV");
now Jarvis reads a `.xlsx` directly ("how many rows are in my budget.xlsx", "what
columns are in my expenses", "read sheet 2", "summarise my workbook"). Natural
partner to `find_files`.
- **Dependency (new, allowed under the policy):** `openpyxl`, pinned in
  `requirements.txt`. Pure-Python, offline, no compiler/binary wheel (installed
  clean as `openpyxl-3.1.5-py2.py3-none-any.whl` + pure-Python `et-xmlfile-2.0.0`).
  Imported LAZILY inside the tool, so startup is unaffected; if missing the tool
  returns a friendly "install openpyxl" message instead of crashing. Jarvis stays
  fully local/offline. Fresh checkout:
  `.venv\Scripts\python -m pip install openpyxl` (or `-r requirements.txt`).
- Reports the sheet names and, for a chosen sheet, the data-row count, column
  count, column names, and a preview of the first rows. `sheet` picks a worksheet
  by NAME or 1-based NUMBER (default the first); an unknown sheet lists the real
  names so the model self-corrects. Cells render cleanly: integral float -> int
  (1200 not 1200.0), midnight datetime -> plain date, text transliterated to
  readable ASCII (reuses `document._ascii_body`: cafe not caf?, straight quotes).
- Reuses `organize._resolve_under_home` for containment (a path outside home,
  incl. a `..`-escape, is REJECTED). Bounded: file on disk 25 MB, streaming
  READ-ONLY mode (bounded memory), row scan 200k (stops early with a note), cell
  + name truncation; a fully blank row isn't counted so the total stays honest.
- Real-world cases never crash: corrupt/non-xlsx + password-protected -> friendly
  message; old binary `.xls` -> steered to "save as .xlsx"; `.csv`/`.tsv` ->
  steered to read_csv; other extensions refused. openpyxl's warnings silenced.
  Alt arg names (`file`/`workbook`/`spreadsheet`/`tab`/...), wrong-type/empty/
  missing args coerced or rejected. Never raises.
- Wired into `app.py` imports (`from .tools import excel`) + the console "Try:"
  line ("how many rows are in my budget.xlsx"), and the agent system prompt
  (read_excel for .xlsx, read_csv for .csv/.tsv). `read_csv`'s old "save as CSV"
  message now steers a .xlsx to read_excel.
- `tests/smoke.py excel` (safe set) builds a real workbook with openpyxl and
  covers summarising it, ASCII transliteration, int/float/date formatting, the
  `rows` preview arg, sheet selection by name AND number + missing-sheet guard,
  alt arg names, a corrupt workbook, the row-scan cap, the forced missing-
  dependency message, non-xlsx types steered elsewhere, containment (absolute +
  `..`-escape), folder + missing, and the empty/missing/wrong-type guards. The
  parsing checks are GUARDED behind openpyxl being importable so the safe set
  passes clean either way. Full safe set: 284 checks, all PASS.

## 2026-07-31 — Convert data files between CSV and JSON (Phase 39)

Added `convert_data` (`jarvis/tools/convertdata.py`): a NEW category -- text/data
TRANSFORMATION. The data family could READ files (read_csv / read_json /
read_excel) but never TRANSFORM one; turning a CSV into JSON, or JSON back into a
spreadsheet a person can open in Excel, is an everyday chore the 8B model can't do
by hand without hallucinating rows or mangling quoting. Now Jarvis does it exactly
("convert my data.csv to json", "turn this json into a csv so I can open it in
Excel", "export my contacts.json as csv"). Natural next step after the reading
family; partners with find_files.
- Pure stdlib (`csv` + `json`), NO new dependency. CSV/TSV -> JSON (header row ->
  object keys; array of objects, or one object per line for a `.jsonl` dest).
  JSON/JSONL -> CSV (array of objects/single object/array of scalars -> a sheet;
  columns are the union of keys, one row per record). Output written UTF-8 with a
  BOM so Excel shows accents right. CSV values stay strings (never guesses a
  number, so '007' isn't corrupted).
- Reuses `organize._resolve_under_home` for containment (BOTH source AND dest,
  incl. a `..`-escape, REJECTED outside home -> can't read from or write into
  `C:\Windows`), `spreadsheet._pick_delimiter` (delimiter sniff) and
  `jsondata._load_value` (the shared JSON reader/validator/parser, incl. JSONL
  detection). Never overwrites; the output can never be the source. **Atomic
  write** (`.part` temp then `os.replace`, temp cleaned on failure). Bounded: file
  25 MB, rows 200k, columns 2000 -- REFUSED before writing anything if a cap is
  exceeded (no partial/misleading file).
- Forgiving to 8B quirks: alt arg names (`file`/`from`/`input`/`to`/`output`/...),
  a `format` hint, wrong-type/empty/missing args coerced or rejected; an Excel
  `.xlsx` steered to read_excel, a non-tabular JSON scalar refused with a reason,
  an unknown output extension refused, a same-format ("CSV to CSV") request
  refused, folder/missing/empty source answered. The tool's reply is pure ASCII
  (the written FILE keeps the real UTF-8 data). Never raises.
- Wired into `app.py` imports (`from .tools import convertdata`) + the console
  "Try:" line ("convert my data.csv to json"), and the agent system prompt
  (convert_data transforms the file, vs read_csv/read_json which only summarise).
- `tests/smoke.py convertdata` (safe set) reads back the WRITTEN files: CSV->JSON
  (blank row not counted, values kept as strings), JSON->CSV (union columns + BOM +
  bool), a `.jsonl` output, array-of-scalars -> single 'value' column, alt arg
  names, never-overwrite, same-format/non-tabular/unknown-dest refusals, empty
  source, containment (source AND dest, absolute + `..`-escape), folder + missing,
  the row cap (nothing written when over cap), ASCII-only reply, and the
  empty/missing/wrong-type guards. Full safe set: 300 checks, all PASS. No new
  dependency added.

## 2026-07-31 — Extract items from text (Phase 40)

Added `extract_items` (`jarvis/tools/textextract.py`): a productivity / text-
handling win in a fresh category (the document- and structured-data-READING
families are complete). Harvesting every email / link / phone number / IP /
number out of a block of text is an everyday chore the 8B model does badly (drops
some, invents others, mangles formatting); Jarvis now does it EXACTLY ("get all
the email addresses from this", "pull the links out of my clipboard", "find all
the phone numbers in this document"). Pairs with get_clipboard and find_files/
read_document. No new dependency (pure stdlib `re`).
- Args `kind` (emails/urls/phones/ips/numbers, with a big alias map) + EITHER
  `text` OR `path`. Reuses `textstats._read_file_text`/`_looks_like_path` (so a
  plain-text/.docx/.odt file is read with the same bounded, binary-sniffed,
  zip-bomb-guarded reader; a filename dropped into `text` is read as a file) and
  `organize._resolve_under_home` (containment: a path outside home, incl. a
  `..`-escape, is REJECTED). Read-only.
- Correct not naive: URLs get trailing punctuation stripped; phones validated
  (7-15 digits AND a real separator/`+`, so a bare digit run is a number not a
  phone); IP octets range-checked (999.x rejected); results de-duped
  (case-insensitively for emails/urls). Bounded: text capped (searched in part +
  noted), over-large/binary/PDF file refused, items listed capped (200 + "and N
  more"), each item length-bounded + pure single-line ASCII. Unknown/empty `kind`
  lists the supported kinds; alt arg names (`type`/`what`/`content`/`file`/...);
  wrong-type/folder/missing args -> friendly ASCII. Never raises.
- Wired into `app.py` imports (`from .tools import textextract`) + the console
  "Try:" line ("pull the email addresses out of my clipboard"), and the agent
  system prompt (extract_items after the count_words bullet).
- `tests/smoke.py textextract` (safe set): emails/urls/phones/ips/numbers happy
  paths (de-dup, validation, punctuation strip), a plain-text file + a real
  `.docx`, filename-in-text, no-match + unknown-kind, alt arg names, containment
  (absolute + `..`-escape), folder/missing/PDF/binary refusals, over-long-text
  truncation, item cap, ASCII-only, and the empty/missing/wrong-type guards. The
  sandbox is **pid-tagged** so concurrent smoke runs never collide. Full safe set:
  318 checks, all PASS. No new dependency.

## 2026-07-31 — Smoke test isolation retrofit (separate commit)

Older smoke fixtures used FIXED sandbox dir/file names (find_duplicates was the
known one; also find/search/recent/organize/.../json/convertdata, plus the temp
memory/tasks/reminders stores). Two overlapping smoke runs (queued loop cycles)
collided on those names and caused transient false failures. Retrofit (assertions
UNCHANGED, only paths):
- 22 home-rooted fixtures: `sandbox = home / f"<base>_{pid}_{uuid4().hex}"`; a
  `_sb` var carries the unique name and every tool-arg path references it. Cleanup
  was already in a `finally` (rmtree sandbox).
- memory/tasks/reminders: unique `tempfile.mkdtemp()` store DIR per run (also
  isolates the fixed-name `*.corrupt.json` sidecar), removed at end of the fixture
  (check() swallows assertion errors, so control always reaches the cleanup).
- t_tools temp file: pid/uuid-tagged and removed after use.
Done via a scoped transform (each fixed base name is function-unique). Committed
separately from Phase 41.

## 2026-07-31 — Summarise a set of numbers (Phase 41)

Added `summarize_numbers` (`jarvis/tools/numstats.py`): the exact-statistics
member of the exact-computation family (after calculate / convert_units /
count_words). The 8B model is bad at arithmetic over MANY numbers, so this reports
the count, sum, average, min, max, median, range and standard deviation EXACTLY
("what's the average of these", "sum this list", "median sale", "std dev of these
figures"). Pairs with read_csv (average a column). NO new dependency (pure stdlib
`statistics`/`csv`/`re`/`math`).
- Input: `numbers` (a string OR a list; any separators) OR `path` to a file --
  a plain list/text file (all numbers extracted) or a CSV/TSV with `column` (name
  OR 1-based number) to summarise one column. Extractor handles negatives,
  decimals, thousands separators (1,234,567) and scientific notation (6.02e23);
  non-numeric text ignored. A filename dropped into `numbers` is read as a file
  (reuses textstats `_looks_like_path`).
- Reuses `organize._resolve_under_home` (containment: outside home / `..`-escape
  REJECTED), `textstats._read_file_text` (bounded, binary-sniffed reader) and
  `spreadsheet._pick_delimiter` (CSV delimiter sniff). Bounded: direct text capped,
  over-large file refused, at most `MAX_VALUES` (100000) values used (+ note);
  `math.fsum` for an accurate total; non-finite skipped. Read-only; never raises;
  pure ASCII out. Alt arg names (`values`/`data`/`list`/`file`/`col`/`field`/...).
- Wired into `app.py` imports (`from .tools import numstats`) + the console "Try:"
  line ("average 4, 8, 15, 16, 23, 42"), and the agent system prompt
  (summarize_numbers for average/median/sum/std dev, after the calculate bullet).
- `tests/smoke.py numstats` (safe set, pid/uuid-tagged sandbox): exact stats,
  forgiving input (list/thousands/scientific/negatives/alt names/single value),
  a text file, filename-in-`numbers`, CSV column by name AND number + missing-
  column list, the value cap, containment + folder/missing/no-number/binary
  guards, ASCII-only, and the empty/missing/wrong-type guards. Full safe set:
  326 checks, all PASS. No new dependency.

## 2026-07-31 — Generate a strong password (Phase 42)

Added `generate_password` (`jarvis/tools/password.py`): a productivity /
safe-automation win that is on-brand for a "local - private - yours" assistant.
Rather than the user visiting a website that SEES (and may log) the password it
returns, Jarvis mints a strong random one right here -- it never leaves the PC and
is never stored ("generate a password", "make me a 20 character password", "a
password with no symbols", "create 5 passwords"). Then "copy that" (set_clipboard)
puts it on the clipboard. NO new dependency (pure stdlib `secrets`).
- Options: `length` (default 16), include `symbols`/`digits`/`uppercase`/
  `lowercase`, `avoid_ambiguous` look-alikes (0/O, 1/l/I; default on), `count`.
  Uses `secrets` (cryptographically strong); when it fits, guarantees one char
  from every enabled class then securely shuffles (Fisher-Yates via `secrets`).
- Bounded: `length` coerced + clamped 4..128 (`MIN_LEN`..`MAX_LEN`) so a
  hallucinated `length=1e9` can't hang; `count` clamped to `MAX_COUNT` (20). Pure
  ASCII by construction. Never persists, never raises: all classes off -> a strong
  default set (with a note), not an error/loop; wrong-type/empty/missing args
  coerced (`_as_int` reads "20 characters", `_as_bool` reads yes/no/on/off/1/0);
  alt count names (`n`/`number`/`amount`/`quantity`). Password returned then
  forgotten.
- Wired into `app.py` imports (`from .tools import password`) + the console "Try:"
  line ("generate a strong password"), and the agent system prompt (mint locally,
  offer to copy, never invent one or read it aloud), after the summarize_numbers
  bullet.
- `tests/smoke.py password` (safe set; no filesystem, so no sandbox needed): the
  happy path (16 chars, all four classes, no look-alikes, over 30 draws), custom
  length + per-class selection (digits-only / no-symbols / ambiguous-allowed),
  `count` making N distinct passwords, the length/count clamps, the all-off
  fallback, and the wrong-type/alt-name/extra-arg guards. Checks assert INVARIANTS
  (random output) not fixed strings. Full safe set: 331 checks, all PASS. No new
  dependency.

## 2026-07-31 — Encode / decode text (Base64 / hex / URL) (Phase 43)

Added `encode_text` (`jarvis/tools/textcodec.py`): a text/data-TRANSFORMATION win
in the same on-brand vein as generate_password. Decoding a Base64 blob, a hex
string or a percent-encoded URL is an everyday chore (a pasted token, a value out
of a log, a link with %20 in it), and the usual answer is a website that SEES (and
may log) whatever you hand it. The 8B model itself invents/drops characters on
these encodings, so Jarvis now does it EXACTLY, on-device ("decode this base64
aGVsbG8=", "base64 encode this", "convert this to hex", "url decode
hello%20world"). Pairs with get_clipboard/set_clipboard. NO new dependency (pure
stdlib `base64`/`binascii`/`urllib.parse`).
- Six operations: base64_encode/decode, hex_encode/decode, url_encode/decode.
  Args `operation` + `text`. Plain phrasing ("decode base64", "to hex") resolves
  via a forgiving alias map; a `format`+`direction` pair split across two fields is
  reassembled. Robust decoders: Base64 tolerates whitespace/URL-safe alphabet +
  repairs `=` padding; hex tolerates a `0x` prefix and `:`/`,`/`;` separators.
- Bounded: input capped (`MAX_TEXT`, 200k chars) and REFUSED (not truncated) if
  over -- a truncated Base64/hex string would decode to corrupt bytes. Pure ASCII
  out: encoded output is ASCII by construction; decoded output is forced to
  readable ASCII (reuses `document._ascii_body`), and a mostly-binary decode is
  flagged so a decoded image/file blob can't corrupt the console/context.
- Hardened: empty/whitespace/missing text -> friendly message; wrong-type text
  coerced (`str(123)`); alt text fields (`content`/`string`/`data`/`input`/...);
  invalid Base64/hex refused; a bare "encode"/"decode" or unknown operation lists
  the six choices. Read-only, nothing persisted, never raises.
- Wired into `app.py` imports (`from .tools import textcodec`) + the console "Try:"
  line ("decode this base64 aGVsbG8gd29ybGQ="), and the agent system prompt
  (encode_text after the extract_items bullet, offer to copy the result).
- `tests/smoke.py textcodec` (safe set; no filesystem, so no sandbox needed):
  Base64/hex/URL round-trips + known vectors (Base64 encode matches the stdlib),
  plain phrasing + split fields + forgiving inputs, UTF-8 -> ASCII on decode, a
  binary blob flagged + still ASCII, invalid Base64/hex refused, unknown/bare
  operation listing the choices, and the empty/whitespace/missing/wrong-type/
  oversized/extra-arg guards. Full safe set: 335 checks, all PASS. No new dep.

## 2026-07-30 — Tool-count note

Tool-count note (the fluctuating figure): NOT a registry bug. The registry holds
exactly one entry per `@tool`-decorated function. The printed number only swings
on whether the OPTIONAL `browser` module imports at count time (it adds 6):
after Phase 43 that is 68 without browser, 74 with (encode_text added one).
No tools are being silently dropped.

## 2026-07-31 — Fix: loops after every question + apparent loss of voice/vision

the user reported Jarvis getting "stuck in a loop after every minor question" and
"losing the ability to talk and to see". Diagnosed and fixed; NO model swap was
needed (tested and rejected — see below).

Root causes (evidence-based, reproduced):
1. **The loop.** For a simple question (e.g. "what time is it"), qwen3:8b picks
   the WRONG tool (`run_command "time"`), which errors, and then repeats the
   identical failing call until `MAX_TOOL_ROUNDS` is exhausted -> "I got stuck in
   a tool loop". The deeper cause: **68-74 tools + a 14 KB system prompt overwhelm
   a small local model's tool selection.** Proof: the SAME qwen3:8b shown only
   ~19 tools answered time/math/convert/dates/word-count all correctly in 2-7 s.
2. **"Lost voice and vision" was NOT broken code.** There were TWO `python -m
   jarvis` instances running at once, contending for the single mic, webcam and
   Ollama model; the loser can't hear/see/speak, and a looping brain never
   produces a spoken reply. With the duplicate killed, tts / camera / vision
   smoke tests all PASS unchanged.

Fixes:
- `jarvis/agent.py` — loop guard + graceful finish. Track (tool+args) per turn:
  an identical repeat is not re-run, it gets a firm "you already called this,
  change course or answer" push-back. Cap any single tool to `MAX_SAME_TOOL` (3)
  calls per turn (catches thrash with varied args). If rounds still run out,
  `_final_answer()` makes ONE no-tools call so Jarvis says something useful
  instead of the dead-end "stuck in a tool loop" message. `_call_model` now takes
  an explicit `tools=` list.
- `jarvis/tools/registry.py` — **per-turn tool router** (`specs_for(text)`).
  Keeps ALL tools registered/dispatchable but only OFFERS the model a relevant
  subset: an always-on `_CORE` (~20 everyday/vague-trigger tools) plus the
  non-core tools whose name/description keywords the question mentions, ranked by
  overlap, capped at `limit` (24). `dispatch()` is unchanged and still runs any
  registered tool, so a tool left out of an offer is never lost — the model can
  still reach it via `list_tools`. `agent.chat()` calls `specs_for(user_text)`.
- Config unchanged: still `qwen3:8b`. Verified end-to-end in the real app
  (`-m jarvis`, piped): time/percent/convert all correct, 2-5 s, no loops.

Model bake-off (why we did NOT "upgrade"): tested qwen2.5:7b-instruct (slower,
thrashes worse), qwen2.5:14b-instruct (~109 s/answer, RAM/VRAM-bound, still
wrong), llama3.1:8b (fabricates tool-call JSON as text), and qwen3:8b think=True
(slower, avoids tools). All WORSE than qwen3:8b+routing on the dev machine.
The bottleneck was tool count, not model IQ. The extra pulled models
(qwen2.5:7b-instruct, qwen2.5:14b-instruct, llama3.1:8b) are still in `ollama`
and can be removed with `ollama rm` if disk is needed.

Pre-existing, still open (NOT caused by this change, out of scope here):
`set_volume` hits a pycaw `'AudioDevice' has no attribute 'Activate'` error;
`get_time` is sometimes picked over `today` (both correct); the clipboard smoke
checks fail transiently when another app holds the Windows clipboard ("clipboard
is busy").

## 2026-07-31 — Fix: PDFs that won't open + Jarvis went mute after one line

the user reported (a) a written PDF (his CV) won't open and (b) Jarvis still can't
talk aloud. Both root-caused and fixed.

1. **"PDF won't open."** There was NO pdf-WRITER tool — only `read_pdf` and
   `write_file`. Asked for a CV "as a PDF", the model called `write_file` with a
   `.pdf` name, which just dumps raw text; those bytes aren't a PDF, so no viewer
   opens it. Fix: new `create_pdf` (`jarvis/tools/makepdf.py`) writes a REAL PDF
   via `fpdf2` (small, pure-Python, offline — added to requirements.txt). Text is
   transliterated to ASCII (reusing read_document's transliterator) because fpdf's
   core fonts are Latin-1; multi_cell uses `new_x=LMARGIN,new_y=NEXT` (without it
   fpdf raises "Not enough horizontal space"). `write_file` now REFUSES a `.pdf`
   path and steers to create_pdf; the agent system prompt routes "as a pdf" to
   create_pdf. Verified end-to-end: agent -> create_pdf -> `%PDF-` file that pypdf
   reads back. (Even when the model tries write_file first, the steer makes it
   self-correct to create_pdf.) Wired via `from .tools import makepdf` in app.py.
   Now 69 tools without browser. NOTE: still no .docx WRITER — a "as a word doc"
   request would hit the same raw-text trap; add a create_docx later if asked.

2. **"Can't talk aloud."** `jarvis/voice/tts.py` created a "fresh" pyttsx3 engine
   per utterance, but `pyttsx3.init()` returns a CACHED singleton — proven: same
   engine id every call, first utterance speaks (~3s), every later one returns
   instantly (~0.1s) with NO sound. So Jarvis spoke once after launch then went
   mute. Fix: speak through Windows SAPI directly with ONE persistent
   `SAPI.SpVoice` (comtypes) on the tts thread (`comtypes.CoInitialize()` first,
   `voice.Rate = 1`). Verified: 3/3 utterances speak, on a background daemon
   thread, and via the real `Speaker` class. `pyttsx3` is now unused (left in
   requirements.txt, harmless).

Also fixed this session: `set_volume` for pycaw 20251023 (see the earlier commit).

## 2026-07-31 — Weather that works, a Word writer, a resourcefulness nudge

the user: "what's the weather like today" made Jarvis web_search and then say it
couldn't find it; also asked for a .docx writer and to make Jarvis "more like
you".

- **get_weather** (`jarvis/tools/weather.py`): web_search only returns page
  DESCRIPTIONS ("get accurate forecasts..."), never the actual temperature, so
  the model had nothing to report. New tool pulls real current conditions +
  today's hi/lo/rain from wttr.in (free, no API key; geolocates this PC by IP
  when no city is given). Output is pure ASCII (wttr's emoji/arrows stripped).
  KEY guard: `_clean_location` drops filler/question words a small model dumps
  into `location` ("today", "whats the weather like now" -> "" -> IP geolocation;
  "weather in London" -> "London"). Without it the model passed "today" and
  wttr resolved it to a random city (saw "Silhaam, Indonesia"). System prompt +
  routing send weather to get_weather, not web_search.
- **create_docx** (`jarvis/tools/makedocx.py`): the Word-doc twin of create_pdf
  (Phase from earlier today), via python-docx (added to requirements.txt). Same
  home-containment + never-raise safety. write_file now refuses BOTH .pdf and
  .docx and steers to create_pdf / create_docx; the system prompt routes "as a
  word doc" here. .docx keeps real unicode (unlike PDF's Latin-1 core fonts).
- **Resourcefulness nudge** (system prompt): added a rule to be helpful and try
  another approach before giving up, only claim it can't AFTER trying, lead with
  the answer, and never invent a fact/claim a tool result it didn't get. This is
  the "more like you" ask, scoped to a behavior change rather than a model swap
  (an 8B local model can't be made Opus-smart, but it can stop giving up early).

71 tools without browser, 77 with. Verified end-to-end in the real app: weather
reports the correct local city; create_docx/create_pdf produce openable files
(pypdf / python-docx read them back). NOTE: no create_xlsx writer yet.

## 2026-07-31 — create_xlsx + a real audit ("why is something always broken")

the user asked for an Excel writer and, frustrated, "why is there always something
missing or broken -- check all the skills and functions".

- **create_xlsx** (`jarvis/tools/makexlsx.py`): the third writer (after
  create_pdf/create_docx). Model passes `content` as CSV-ish rows (first row =
  header); cells that look numeric are stored as NUMBERS so Excel can sum them,
  header row bolded, sheet name from `title`. openpyxl (already a dep). write_file
  now refuses .pdf/.docx/.xlsx (one table) and steers to the right writer; prompt
  routes "as a spreadsheet/excel" here. Verified end-to-end.

- **The audit + the real answer.** Ran the safe set AND a live-tool sweep
  (`scratchpad/audit.py`): every live tool works -- get_time, system_info,
  get_weather, web_search, fetch_page, take_screenshot, and the Playwright
  browser (open/read/close) all OK. THE ROOT CAUSE of "always something broken":
  **23 of 78 tools had NO automated test** (append_file, list_folder, open_app/
  website, take_screenshot, the browser_*, the camera tools, set_volume,
  lock_pc, web_search/fetch_page, and -- until now -- the new writers/weather).
  Logic-only smoke tests also gave false confidence (tts asserted `ok=True`, not
  that sound played; set_volume had no test at all). So breakage only surfaced
  when the user hit it. Actions taken this pass:
  - Added `t_writers` smoke section (create_pdf/docx/xlsx make REAL files,
    validated by reading them back; write_file steer; guards) to the SAFE set,
    and added makepdf/makedocx/makexlsx/weather to the imports test.
  - Fixed a real bug the audit found: the camera tools (`list_cameras`,
    `describe_view`, `start_working`, `stop_working`) crashed with a raw
    `'NoneType' has no attribute` when the camera manager wasn't initialised
    (no webcam / init failed); they now return a friendly `_NO_CAM` message.
  - Full safe set PASS incl. the 5 new writer checks; camera/vision/tts smokes
    PASS after the guard changes.
## 2026-07-31 — Coverage: network + system smoke sections (close the gap)

Built the two sections the prior audit called for, so the untested tools now have
guards:
- SAFE set gained `append_file` + `list_folder` (in t_tools) -- pure filesystem,
  deterministic. (list_folder test uses a dedicated small dir: the real tool caps
  its listing at 100 items, which flaked against the huge shared temp dir.)
- New **`network`** section (`smoke network`, needs internet, NOT in safe):
  web_search returns results, fetch_page reads example.com, get_weather returns
  live conditions here + for a named place, and get_weather's `_clean_location`
  filters filler offline. This is the section that would have caught the weather
  bug.
- New **`system`** section (`smoke system`, touches hardware, NOT in safe):
  take_screenshot writes a real PNG (validated by magic bytes) + cleans up;
  set_volume reads/sets/mutes and RESTORES the original level; open_app,
  open_website, open_folder are exercised with their launcher faked (no windows
  pop up) to check command-building / URL-normalisation / home-containment;
  lock_pc is checked as registered but deliberately NOT executed.
Results: safe set now 342 checks PASS; `network` and `system` both PASS. Still no
automated guard for the browser_* tools (covered live in the audit + e2e) and the
camera tools (covered by the camera/vision sections + the new None-manager guard).

## 2026-08-01 — Edit part of a file without rewriting it (Phase 44)

Added `edit_file` (`jarvis/tools/edit.py`): a core CODE-BUILDING capability and
the missing verb in the write family. Until now the only way to CHANGE something
already in a file was `write_file`, which overwrites the WHOLE file -- so the 8B
model had to reproduce every other line perfectly or silently lose the rest. For
a small local model iterating on code/config/notes that is a real hazard. This is
Claude Code's own Edit tool: find an exact piece of text and replace it, leaving
everything else untouched. Answers "change the port to 8080 in my config", "fix
that typo", "rename that function", "update the version number".
- Args `path` + `old` (exact existing text) + `new` (replacement; empty `new`
  DELETES the old text) + optional `replace_all`. The `old` text must appear
  EXACTLY: 0 matches -> friendly "couldn't find that text" (file untouched);
  >1 match without `replace_all` -> REFUSED as ambiguous with the count, so a
  single hallucinated match can never rewrite the wrong line. Pure stdlib, NO new
  dependency.
- Reuses `organize._resolve_under_home` for containment (a path outside home,
  incl. a `..`-escape, is REJECTED -> can't edit `C:\Windows`) and
  `fileinfo._is_binary` (binary by extension OR NUL-byte sniff refused, so an
  edit can't corrupt an image/archive/Office doc). A missing file is steered to
  write_file; a folder is refused. **Newline-preserving**: matching is done on
  \n-normalised text (read_file shows the model \n) but the file's original CRLF
  endings are restored on write, so an edit doesn't reflow a whole file. **Atomic
  write** (`.part` temp then `os.replace`) so a failure never truncates the file.
  Bounded: file 5 MB, old/new 100k chars each (over-cap refused, not truncated).
  Forgiving arg names (`file`/`find`/`replace`/`old_string`/`new_string`/...),
  wrong-type/empty/missing args coerced or rejected, output pure ASCII. Never
  raises.
- Added to registry `_CORE` (always offered, a peer of write_file/read_file) so
  the router surfaces it for any edit request. Wired into `app.py` imports
  (`from .tools import edit`) + the console "Try:" line ("change the port to 8080
  in my config.txt"), and the agent system prompt (edit_file to CHANGE part of an
  existing file, NOT write_file which risks losing the rest; write_file only to
  CREATE, append_file to add to the end).
- `tests/smoke.py edit` (safe set, pid/uuid-tagged sandbox): single exact
  replacement (rest of file intact), empty-`new` deletion, ambiguous-refused +
  replace_all, not-found (file untouched), CRLF preservation, alt arg names,
  old==new no-op, binary refused, missing-file steer to write_file, containment
  (absolute + `..`-escape), folder refused, ASCII-only, the size cap, and the
  empty/missing/wrong-type guards. Full safe set: 357 checks, all PASS. Verified
  end-to-end: the router offers edit_file for "change the port..." and a real
  dispatch edited a real file, changing only the target line. No new dependency.
  72 tools without browser (78 with).

## 2026-08-01 — Run/build/test code in a project folder (Phase 45)

Added `run_project_command` (`jarvis/tools/runner.py`): the biggest missing
CODE-BUILDING verb. Jarvis could already write and edit files but could NEVER
RUN them, so it couldn't tell whether the code it produced actually works -- the
core thing Claude Code does. Now it runs a real build/dev command inside a
project folder and gets back the stdout, stderr and exit code, so it can run a
script, run tests, install a package or check a repo and SEE the result ("run my
script", "run the tests", "does it work", "pip install requests", "npm install",
"git status"). This is the counterpart to `run_command` (shell.py), which stays
strictly for read-only PC inspection (ipconfig/ping/tasklist) and cannot run the
user's code. Pure stdlib, NO new dependency.
- Args `command` (e.g. 'pytest' or 'python app.py') + `directory` (the project
  folder, under home; defaults to home) + optional `timeout`. The command is
  parsed into a fixed argv (`shlex`, `posix=False` so Windows backslashes and
  quoted args survive) and run with `subprocess.run(shell=False, cwd=proj)`.
  Output is reported as a readable, bounded, pure-ASCII summary (status + exit
  code + Output/Errors), each stream capped at 4000 chars.
- Safety, layered (an 8B model WILL emit junk): (1) **scoped to home** --
  reuses `organize._resolve_under_home`, so cwd outside home / a `..`-escape is
  REJECTED (can't run in `C:\Windows`); (2) **allowlist of build/dev tools
  only** (python/pip/pytest/node/npm/npx/yarn/git/go/cargo/java/dotnet/make/...);
  anything else refused with the list; (3) **no shell** -- `&`, `|`, `>`, `;`
  become inert arguments, never a second command (real injection-inert smoke
  test: `python --version & del hello.py` leaves the file intact); (4) **no
  path-y exe** -- a first token with a slash (`.\evil.exe`) is refused; the
  program must resolve on PATH via `shutil.which` (so `npm` finds `npm.cmd`);
  (5) **outward-facing publish/push blocked** (`git push`, `npm publish`,
  `cargo publish`, ...) since a deploy should be the user's deliberate act;
  (6) **bounded** -- timeout coerced+clamped (default 120s, max 300s), no popup
  window. Alt arg names (`cmd`/`dir`/`folder`/`project`/`cwd`/...), wrong-type/
  empty/missing args coerced or rejected. Never raises.
- Added to registry `_CORE` (a peer of write_file/read_file/edit_file, so the
  router always offers it for a run/test/build request) and wired into `app.py`
  imports (`from .tools import runner`), the console "Try:" line ("run the tests
  in my project"), and the agent system prompt (run_project_command to actually
  run/test code vs run_command which only inspects the PC; do not claim code
  runs until it has been run; won't push/publish).
- `tests/smoke.py runner` (new safe-set section, pid/uuid-tagged sandbox under
  home, real subprocesses using this same Python): runs a script (stdout+exit),
  reports a nonzero exit, captures stderr, allowlist refusal, shell-metacharacter
  injection inert (no file deleted), path-exe refused, publish/push refused,
  containment (absolute + `..`-escape), missing folder, an uninstalled allowed
  tool, alt arg names + wrong-type + ASCII guards, and the timeout clamp. Full
  safe set: 369 checks, all PASS. Verified end-to-end for real: the full build
  loop make_folder -> write_file -> run_project_command produced correct live
  output ("sum = 108"), and dispatch actually ran python/git and captured their
  output/exit codes. No new dependency. NEXT best step: let the model run a
  longer task in the BACKGROUND (start + poll) so a slow test/build/install
  doesn't block the single-threaded turn, or capture combined interleaved
  output for commands that stream progress.

## 2026-08-01 — Run a command in the BACKGROUND (start + poll + stop) (Phase 46)

Added `start_background_command` / `check_background_command` /
`stop_background_command` (`jarvis/tools/background.py`): the increment Phase 45
flagged as next. `run_project_command` runs a command and WAITS for it, which
blocks Jarvis's single-threaded turn -- fine for a quick script, bad for a slow
`pip install`/`npm install`, a long test suite, or a dev server (`npm run dev`,
`python -m http.server`) that never exits. Jarvis can now kick a long job off,
keep talking, and check back -- the way Claude Code runs a build in the
background. Pure stdlib, NO new dependency.
- **Reuses the runner's whole safety model, not a copy of it.** runner.py's
  command+directory validation was refactored out into a shared
  `_resolve_command_and_dir()` (plus a shared `_where()`), and BOTH
  run_project_command and the background tools call it -- so the same defenses
  apply: home-containment (a `..`-escape / `C:\Windows` REJECTED), the build/dev
  allowlist, `shell=False` (metacharacters inert), no path-y exe, publish/push
  refused, PATH resolution (`npm`->`npm.cmd`). run_project_command's 12 smoke
  checks still pass unchanged after the refactor.
- `start_background_command` launches via `subprocess.Popen` (stdin=DEVNULL, no
  window) and returns a short job id AT ONCE. Output is drained off the process's
  pipes by two daemon reader threads into a per-stream bounded `bytearray`
  (`MAX_CAPTURE` 200 KB, overflow dropped + flagged), so a chatty command can
  never deadlock on a full pipe or exhaust memory. Bounded elsewhere too:
  `MAX_JOBS` (8) concurrent running jobs (a hallucination can't fork-bomb),
  `MAX_LIFETIME` (30 min) after which a still-running job is auto-stopped, and
  `MAX_FINISHED` (20) finished jobs retained for re-checking then pruned oldest-first.
- `check_background_command` reports running/finished, exit code, elapsed time
  and the (clipped, ASCII) output so far; with NO id it lists every job and its
  state. `stop_background_command` terminates a running job (terminate -> kill
  fallback); a manual stop and the lifetime auto-stop are worded distinctly, and
  re-stopping a finished job is a friendly no-op. Alt arg names (`cmd`/`dir`/
  `id`/`job`/...), wrong-type/empty/missing coerced or rejected. Never raises;
  output pure ASCII.
- `start`+`check` added to registry `_CORE` (always offered, peers of
  run_project_command; core offer stays at 24, within the router cap); `stop` is
  surfaced by keyword routing ("stop that background job"). Wired into `app.py`
  imports (`from .tools import background`) + the console "Try:" line ("install
  the packages in my project in the background"), and the agent system prompt
  (use the background tools for a slow/never-exiting command; run_project_command
  only when you need the result now).
- `tests/smoke.py background` (new safe-set section, pid/uuid-tagged sandbox under
  home, real subprocesses using this same Python): start+stream+finish (stdout AND
  stderr captured), an in-progress poll showing "still running" + partial output,
  a nonzero exit, stopping a never-ending "server" + the re-stop no-op, the job
  listing + unknown-id guards, the shared runner defenses refused BEFORE launch
  (allowlist/containment/path-exe/publish), the concurrent-job cap (via a
  temporary `MAX_JOBS=1`), and the alt-name/wrong-type/empty/ASCII guards. Every
  launched job is stopped in a `finally`. Full safe set: 377 checks, all PASS
  (369 prior + 8). Verified end-to-end for real OUTSIDE the tests: a 3-tick
  streaming script showed partial output while running then its exit code +
  stderr on finish; a `while True` "server" was started, confirmed running, and
  stopped. No new dependency. Adds 3 tools (start/check/stop_background_command).
  NEXT best step
  candidates: a `run_project_command`/background option to capture COMBINED
  interleaved stdout+stderr (some tools only make sense interleaved), or a
  code-search `grep`-style tool over a project folder (regex + file glob) so
  Jarvis can navigate an unfamiliar codebase before editing it.

## 2026-08-01 — Grep-style code search (regex + file glob) (Phase 47)

Added `search_code` (`jarvis/tools/codesearch.py`): the code-navigation verb
Phase 46 flagged as next, and the last major missing piece of Claude Code's
core toolset. Jarvis could WRITE, EDIT and RUN code but had no way to SEARCH a
codebase, so before editing an unfamiliar project it was navigating blind. This
is Claude Code's own `Grep`: search file CONTENTS for a **regular expression**
and get back each file with the line number and line ("where is run_project
defined", "find every call to set_volume", "grep for TODO|FIXME", "find
`import requests`"). It completes the finder trio -- `find_files` (by NAME),
`search_files` (a plain substring, aimed at notes/documents), `search_code` (a
REGEX + file glob, aimed at code). Pure stdlib (`re`/`fnmatch`), NO new dep.
- One combined tool, not two: the glob facet is a `glob` argument that filters
  WHICH files are grepped (`*.py`, several comma-separated, or a path glob like
  `src/**/*.js` with real `**`-across-directories semantics via a small
  `_glob_to_regex`). A standalone path-glob file lister would mostly duplicate
  `find_files`, so it was deliberately folded in here instead.
- Reuses the existing safety model wholesale: `find._resolve_root`
  (home-containment -- a folder outside home / a `..`-escape is REJECTED, can't
  grep `C:\Windows`), `find._SKIP_DIRS` (.git/node_modules/venv/AppData pruned),
  `find._coerce`, and `search._BINARY_EXTS`/`_looks_binary`/`_ascii` (binary by
  extension AND NUL-byte sniff skipped, matched lines forced to bounded
  single-line ASCII). Bounded on depth (12, deeper than the doc tools), files
  read, entries scanned, matches (total + per file), 2 MB/file cap and a 10 s
  wall-clock budget -- a pathological or catastrophic-backtracking pattern stops
  early with a note. A file over the budget stops, never hangs.
- Forgiving to 8B quirks, never raises: an INVALID regex (a stray `(`) is retried
  as literal text and the reply says so, so it self-corrects instead of dead-
  ending; `case_sensitive` (default off) honored; alt arg names
  (`query`/`regex`/`text` for pattern, `file`/`files`/`name`/`include` for glob,
  `dir`/`directory`/`project`/`path` for folder); a bare `*` glob = no filter;
  wrong-type/empty/missing args coerced or answered. Results show the absolute
  path + `lineno: line`, ready to hand straight to read_file/edit_file.
- Added to registry `_CORE` (a peer of write_file/read_file/edit_file/
  run_project_command) so the router always offers it -- necessary because
  `_CORE` already fills the router's per-turn limit, so a non-core tool is
  effectively never surfaced. Real-app offer is now 25 tools (was 24). Wired
  into `app.py` imports (`from .tools import codesearch`) + the console "Try:"
  line ("search my code for the run_project function"), and the agent system
  prompt (search_code = REGEX over code to navigate before editing, vs
  search_files = plain substring for notes; results feed read_file/edit_file).
- `tests/smoke.py codesearch` (new safe-set section, pid/uuid-tagged sandbox
  project under home): a regex definition match with line number (a bare call in
  another file correctly excluded), an alternation regex across files, the `*.py`
  glob excluding a `.txt`, a recursive `src/**/*.py` path glob reaching only the
  nested file, case-insensitive default vs `case_sensitive`, node_modules pruned
  + a `.pyc` binary skipped, the invalid-regex->literal fallback, ASCII-only
  output, containment (absolute + `..`-escape), alt arg names, the router
  actually offering search_code for a code query, and the empty/missing/
  wrong-type/bare-`*`/missing-folder guards. Full safe set: 390 checks, all PASS
  (377 prior + 13). Verified end-to-end for real OUTSIDE the tests: a regex
  search over this actual Jarvis codebase located `def _resolve_under_home`
  (organize.py:82) and `@tool(` (codesearch.py:157), returning absolute paths.
  No new dependency. 78 tools without browser (84 with). NEXT best step
  candidates: an optional context-lines (`-C`) window around each match, or a
  standalone glob file-lister if `find_files`'s basename-only matching proves
  too weak for `**`-style project queries.

## 2026-08-01 — Context lines around a code-search match (Phase 48)

Refined `search_code` (`jarvis/tools/codesearch.py`) with an optional `context`
(grep's `-C`) argument -- the refinement Phase 47 flagged as next. Before this,
a match came back as a lone `lineno: line`, so to see the code AROUND a hit
(the whole function, the lines it depends on) Jarvis had to make a second
`read_file` round-trip. Now one search can show the surrounding lines, so the
search -> read -> edit loop needs one fewer step before an edit. Pure stdlib,
NO new dependency.
- `context` = how many lines to show on each side of every match (default 0 =
  today's behaviour, unchanged). A matched line is rendered `lineno: line` and a
  context line `lineno- line` (grep's `:` vs `-` convention); overlapping or
  adjacent windows are MERGED and separate groups divided by a `--` line, so
  consecutive matches don't repeat lines and distant ones read clearly.
- Bounded + forgiving like the rest: `context` coerced from junk/wrong-type to 0
  and clamped to `MAX_CONTEXT` (10) so one hallucinated huge value can't blow up
  the output; alt arg names (`context_lines`/`around`/`C`/`lines`); at most
  `MAX_MATCHES_PER_FILE` (8) matches per file are expanded, and the existing
  `MAX_RESULTS`/time/size caps still bound the whole reply. Context path reads
  the (already <=2 MB) file's lines once; context lines go through the same
  `_ascii` sanitiser, so output stays pure single-line ASCII. Never raises.
- Default behaviour is byte-for-byte unchanged (context defaults to 0), so all
  13 prior codesearch checks pass untouched. Schema + tool description gained the
  `context` field so the model knows to reach for it before an edit.
- `tests/smoke.py codesearch` gains a context check: `context=1` shows the `-`
  context line above and below plus the `:` match line (and the surrounding
  `return x` that a plain search does NOT pull in), the `context_lines` alt name,
  and the clamp of a 9999 value -- still ASCII. Full safe set: 391 checks, all
  PASS (390 prior + 1). Verified end-to-end for real OUTSIDE the tests: a
  `context=2` search over this actual codebase showed `def _resolve_under_home`
  (organize.py:82) with its 2 lines of surrounding code each side, and a
  multi-match `context=1` search correctly MERGED adjacent hits and divided
  distant groups with `--`. No new dependency.
- Note on scope this cycle: git status/diff/log/add/commit are ALREADY runnable
  via `run_project_command` (git is on its allowlist; only push/publish is
  blocked), so a dedicated git wrapper would have been largely redundant -- the
  context-lines refinement was the higher marginal value. NEXT best step
  candidates: a `web_fetch` (plain HTTP GET + HTML-to-text, local-only, for docs
  lookup) as a genuinely NEW capability, or a project scaffolder (one call to
  create a runnable python/node starter) as a convenience over
  make_folder+write_file+run_project_command.

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

## 2026-08-18 — Second model bake-off (bigger brain REJECTED again) + 4 agent-loop fixes

the user asked for "a much bigger model even if that makes him slower". Measured it
properly instead of assuming, and the answer is the same as 2026-07-31: on this
box a bigger brain is slower and NOT smarter. Config unchanged: still `qwen3:8b`.

Bake-off through the REAL Agent (mind + router + 88 tools), 8 questions, one
model at a time on an idle box (memory-constrained dev laptop):
- `qwen3:8b` -- **6/8, 188 s**
- `qwen3:14b` -- **6/8, 341 s** (same accuracy, 1.8x slower; 98 s on one question)
- `gpt-oss:20b` -- **2/8, 239 s**. With `think=False` Ollama returns 500
  `error parsing tool call` (gpt-oss needs its Harmony channel). `think='low'`
  stops the crashes (2/4); `think=True` is worse (0/4) and it answers from
  stored memory instead of the question. Its ONE tool-free reasoning answer was
  right and the fastest result of the whole exercise (11.7 s vs 19 s) -- the MoE
  speed thesis held, the format compatibility did not. Not viable without
  rewriting the 14 KB system prompt for a second model's conventions.

KEY FINDING: all three models failed the SAME two questions. A failure shared by
an 8B, a 14B and a 21B MoE is a harness bug, not a brain problem. Fixes (TDD,
new `tests/smoke.py agentguard` section, 9 checks, in the safe set):
- `agent.py` `_tool_call_in_text()` + use in `chat()`: when the model WRITES its
  tool call as text instead of making one, run it instead of handing the user
  raw JSON. Previously `{"name": "count_words", ...}` was returned verbatim --
  and in voice mode SPOKEN aloud.
- `agent.py` self-feeding guard (`results_seen`): the model fed `count_words` its
  own output back ("count the word count"), which the (tool+args) dedupe missed
  because the args differed each round. Now refused.
- `agent.py` `wrap_up`: when a guard fires, end the turn via `_final_answer()`
  instead of looping. Left running, the model answers ABOUT the push-back ("I
  see, if you have already used the count_words function...") instead of
  answering. Also `_final_answer()` now demands the actual figures.
- `agent.py` `_refresh_memory()` now states today's date in the system message.
  Told only to "call today", the model built dates from a guessed year (it
  produced `2023-11-01` in 2026).
- `dates.py`: `date_add` description now says it does NOT count days between two
  dates; `days_until` says it is the only correct way to count from today.
- `textstats.py` `_strip_counting_request()`: ignores a "how many words ...:"
  preamble the model may pass along with the text. NOTE: this fixed a slip that
  was MISDIAGNOSED -- the observed 24-word answer came from the self-feeding bug,
  not from a bad argument. Kept because it is narrowly gated and tested, in the
  same spirit as the existing `_looks_like_path` guard.

- `memory.py` `_is_transient()`: `remember` now REFUSES a "fact" that just
  restates the current moment. Handed get_time/today/get_weather output the
  model called `remember` with it ("Today is Tuesday, 18 August 2026, 06:19
  PM"), which is false by tomorrow, crowds out real facts, and derailed the
  reply into "Done, sir.". Five such junk facts were cleaned out of the real
  store with `forget`. Durable facts that merely MENTION a date or the weather
  ("Alex's birthday is on 12 March", "Alex hates cold weather") still store.
  The tool description now also says never to store what another tool just
  returned -- after which the real app answered time AND weather without
  calling `remember` at all.

Result: word count went from broken in EVERY pre-fix run to correct in 3 of 3
post-fix runs ("...contains 9 words."). No raw JSON reached the user in any run.
Safe suite green throughout. Run-to-run variance is high (5/8-7/8 across four
post-fix runs), so judge changes on repeated runs, not one.

STILL BROKEN (genuine 8B limits, not harness): "how many days between today and
the 1st of November" -- it answers 84, or calls `days_between` with the year
2023, even with today's date in the prompt. The TOOLS are right (`days_until`
and `days_between` both return the correct 75). Occasional meta-narration leaks
("The user asked for a unit conversion, and I already provided...").

OPERATIONAL: the Ollama server DIED silently mid-session while cycling the 13 GB
gpt-oss model on the dev machine, which looks exactly like "Jarvis broke".
20B-class models are memory-unsafe here. `gpt-oss:20b` and `qwen3:14b` were
removed after the bake-off to reclaim 22.3 GB.
