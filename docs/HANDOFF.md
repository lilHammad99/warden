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
