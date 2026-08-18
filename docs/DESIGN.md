# Warden — Design (2026-07-29)

A local AI assistant for Windows that watches and acts. Everything runs on this
PC: the brain (Ollama), the eyes (webcam + IP cameras), the voice (local
STT/TTS), and the hands (files, apps, system, headed browser).

Named Warden; the Python package is still `jarvis/`, from the working title,
and the spoken wake phrase is still "Hey Jarvis" (pretrained openWakeWord
model).

## Goals

- Talk to Jarvis by voice ("Hey Jarvis") or text console.
- Jarvis can DO things: create/write files, open apps and websites, report
  system info, control a visible browser.
- "start working" → camera mode: describe what it sees on demand, and a
  background watch mode that alerts when a person/motion appears.
- 100% local AI: no cloud LLM. (Web search tool needs internet, but the
  model deciding and answering is local.)

## Hardware / models

- Consumer laptop with a mid-range GPU; memory-constrained, so only one model
  is resident at a time. Python 3.11, Ollama.
- `qwen3:8b` — main brain (supports tool calling in Ollama).
- `moondream` — vision model for scene description. `qwen2.5vl:3b` is sharper
  but needs ~8.4 GB free, more than is available alongside the chat model, so
  the config ships moondream. Swap `models.vision` if memory frees up.
- YOLOv8n (ultralytics, CPU) — fast person detection for watch mode.
- faster-whisper `small` — speech-to-text.
- openWakeWord `hey_jarvis` — wake word.
- Piper — text-to-speech, a small local neural voice. Falls back to the
  built-in Windows SAPI voice when Piper is not set up; `voice.engine`
  (auto | piper | sapi) chooses. Both are interruptible mid-sentence, so
  barge-in stops speech within milliseconds.

## Architecture

```
jarvis/                     package
  app.py                    entry: console loop (+ voice loop thread)
  agent.py                  Ollama tool-calling loop
  mind.py                   loads JARVIS.md: how the assistant is told to think
  config.py                 loads config.yaml
  control.py                process-wide signals (e.g. shutdown) between
                            a tool and the main loop
  tools/                    one module per tool family, each registering
                            its tools with the @tool decorator
    registry.py             decorator + schema collection + dispatch +
                            specs_for(): the per-question tool router
    files.py  apps.py  system.py  web.py  camera.py  browser.py  ...
  vision/
    cameras.py              open webcam index / RTSP URL, grab frames
    watcher.py              background thread: motion + YOLO person alerts
    describe.py             frame -> moondream description
  voice/
    tts.py  stt.py  wake.py  loop.py  hud.py
```

Flow: user text/speech → `agent.chat()` → `specs_for()` picks the tools worth
offering for THIS question → model returns tool calls → registry dispatches →
results fed back → model answers → print + speak.

The router matters more than it looks. An 8B model chooses badly when shown all
87 tools at once, so each turn offers the core set plus up to 14 more whose
keywords the question actually mentions. The mind (`JARVIS.md`) is prepended
ahead of the tool rules, so the model's sense of how to behave is not buried at
the top of a long prompt.

The agent keeps a rolling conversation history. Tools return plain strings.
Errors from tools are returned as strings so the model can react (no crashes).

## Camera design

- `config.yaml` lists cameras: `webcam: 0` plus named RTSP URLs.
- "start working" starts the watcher thread on the default camera:
  frame diff motion gate → YOLOv8n person check → alert (speak + snapshot
  to `data/snapshots/`, cooldown 30 s).
- "what do you see" grabs a fresh frame → moondream → spoken description.
- "stop working" stops the watcher.

## Error handling

- Every tool call wrapped; failures become readable strings for the model.
- Camera/RTSP failures reported per-camera, never fatal.
- Voice components optional: if mic/wake-word init fails, console still works.

## Testing

- Smoke scripts per phase (agent chat, tool dispatch, camera grab, TTS).
- Manual end-to-end: essay-to-desktop-file, open app, describe scene.
