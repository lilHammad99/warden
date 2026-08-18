# Jarvis "Mind" — design spec

**Date:** 2026-08-01
**Status:** approved by the user, building
**Goal:** Give Jarvis a persistent "how to think" self, so the local 8B brain
carries itself more like Claude — stays on the thread, admits what it doesn't
know instead of inventing, and doesn't give up after one try — and can learn
short lessons from experience.

## Why

Jarvis's brain (`qwen3:8b`) is fixed by the hardware. The lever for making it
feel closer to Claude is the *harness* around the model, not the model. Today
the identity ("You are Jarvis… address the user as sir") is one line buried at
the top of a ~250-line tool-rules prompt, and there is no notion of Jarvis
improving itself. This adds a real "mind" at the front of the prompt plus an
earned-lessons store.

## Components

### 1. `JARVIS.md` (repo root, editable by the user)
Holds Jarvis's identity + a short "how to think" core (~200 tokens), three
principles: **CONTINUITY**, **HONESTY**, **PERSISTENCE**, plus a note steering
it to save lessons. Lives at `PROJECT_ROOT/JARVIS.md` so the user can open and edit
it like `config.yaml`.

### 2. `jarvis/mind.py` (loader, never raises)
- `FALLBACK_MIND` — the same text baked into code, so a missing/empty/broken
  `JARVIS.md` still boots Jarvis with its mind intact (resilience).
- `load_mind()` — reads `PROJECT_ROOT/JARVIS.md`, returns its text, or
  `FALLBACK_MIND` on any error/empty. Loaded once per `Agent` (per session).

### 3. `jarvis/tools/lessons.py` (near-clone of `tools/memory.py`)
A SEPARATE store from user facts: facts = about the user (`memory.json`);
lessons = how Jarvis should do its job (`data/lessons.json`).
- `learn_lesson(lesson)` — append one short, bounded lesson. Same defenses as
  memory: dedup, `MAX_LESSONS` 200, `MAX_LESSON_LEN` 300, atomic write,
  corrupt-file recovery, never raises.
- `forget_lesson(query)` — remove a bad lesson (ambiguous-match safety like
  `forget`), so a hallucinated lesson can be cleared.
- `lessons_preamble()` — an injected block "Lessons you have learned…".
- `count()` — for the startup status line.

### 4. Wiring — `jarvis/agent.py`
- Split the current `SYSTEM_PROMPT`: move identity + character + the
  concise/honesty/persistence lines OUT into `JARVIS.md`; keep the tool-routing
  rules in `SYSTEM_PROMPT`.
- `Agent.__init__` caches `self.mind = mind.load_mind()` and a base string
  `self.mind + "\n\n" + SYSTEM_PROMPT`.
- `_refresh_memory()` rebuilds `messages[0]` as:
  **mind → tool rules → facts → lessons → tasks → reminders**
  (principles at the top, live memory at the bottom — a small model weights the
  start and end of the prompt most).

### 5. Registration & UX
- `app.py` imports `tools.lessons` (registers the tools) and shows a
  `lessons: N learned` count on the startup status line.
- `registry._CORE` gains `learn_lesson` so it is always offerable; `forget_lesson`
  is keyword-matched.

### 6. Tests — `tests/smoke.py`
- New `t_lessons` mirroring `t_memory`: happy path (learn + preamble), dedup,
  hallucination guards, forget flow, corrupt-store recovery. Added to the safe
  set, `SECTIONS`, and the `t_imports` import line. Uses a unique temp store dir
  (pid-tagged) so overlapping runs never collide.

## Out of scope (on purpose)
- No self-authoring of the identity core (Jarvis may only APPEND lessons, not
  rewrite `JARVIS.md`).
- No change to tool-routing rules, the concise/spoken rules, or per-turn tool
  filtering.
- Not rebuilding the session-history window.

## Verification
`smoke safe` stays green (incl. new `t_lessons`); full app boots showing the
`lessons:` count; then the user runs `run.bat` and hears the difference (must fully
close the old window first — Jarvis reads its mind at startup).
