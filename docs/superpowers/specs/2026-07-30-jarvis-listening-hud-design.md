# Jarvis listening HUD + wake reliability — design (2026-07-30)

## Problem
Wake word ("Hey Jarvis") is missed often, and there is no feedback, so the
user can't tell if the mic hears them. Replies also feel laggy because the
screen sits silent through record → transcribe → think → speak.

## Decisions (from brainstorm)
- Feedback lives in a **floating "Jarvis orb"** window (chosen over console).
- Keep `qwen3:8b` as the brain; add a live "thinking" animation instead of
  swapping to a faster/less-smart model.

## What we build
1. **`jarvis/voice/hud.py`** — a `Hud` thread that draws a small, borderless,
   always-on-top Tkinter window: a glowing orb whose color = state
   (idle / listening / thinking / speaking / off), a one-line label, and a
   live mic-level bar. Drag to reposition. All drawing happens on the hud
   thread; other threads only call thread-safe `.state(name)` / `.level(0..1)`
   / `.shutdown()`. Tkinter ships with Python — nothing to install.
   - **Fail-safe:** if Tkinter can't open a window, `create(cfg)` returns a
     null no-op object and voice keeps working exactly as before.
2. **Mic-level plumbing** — `wake.py` and `stt.py` gain an optional
   `on_level` callback; each audio frame reports a normalized 0..1 level so
   the bar moves even *before* the wake word fires (proves the mic is heard).
3. **Wake sensitivity in config** — `voice.wake_threshold` (default 0.4,
   was a hardcoded 0.5). Lower = easier to trigger.
4. **State wiring** — `loop.py` sets the orb state at each phase and flips to
   green the instant the wake word fires (feels immediate). `app.py` creates
   the orb, reflects console commands, and shuts it down on exit.

## Config additions
```yaml
voice:
  wake_threshold: 0.4
hud:
  enabled: true
  corner: bottom-right
```

## Testing
- `tests/smoke.py hud`: opens the orb, cycles all states + a fake mic level
  (no mic needed), reports whether the window drew.
- Manual: `run.bat` → watch orb → say "Hey Jarvis" → meter should jump.

## Out of scope (YAGNI)
Click-to-talk button, settings GUI, waveform history.
