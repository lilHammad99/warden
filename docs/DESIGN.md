# Jarvis — Design (2026-07-29)

A local, Iron-Man-style AI assistant for Windows. Everything runs on this PC:
the brain (Ollama), the eyes (webcam + IP cameras), the voice (local STT/TTS),
and the hands (files, apps, system, headed browser).

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
- `qwen2.5vl:3b` — vision model for scene description.
- YOLOv8n (ultralytics, CPU) — fast person detection for watch mode.
- faster-whisper `small` — speech-to-text.
- openWakeWord `hey_jarvis` — wake word.
- pyttsx3 (Windows SAPI5) — text-to-speech (Piper upgrade later).

## Architecture

```
jarvis/                     package
  app.py                    entry: console loop (+ voice loop thread)
  agent.py                  Ollama tool-calling loop
  config.py                 loads config.yaml
  tools/                    each file registers tools with @tool decorator
    registry.py             decorator + schema collection + dispatch
    files.py  apps.py  system.py  web.py  camera.py  browser.py
  vision/
    cameras.py              open webcam index / RTSP URL, grab frames
    watcher.py              background thread: motion + YOLO person alerts
    describe.py             frame -> qwen2.5vl description
  voice/
    tts.py  stt.py  wake.py  loop.py
```

Flow: user text/speech → `agent.chat()` → model returns tool calls →
registry dispatches → results fed back → model answers → print + speak.

The agent keeps a rolling conversation history. Tools return plain strings.
Errors from tools are returned as strings so the model can react (no crashes).

## Camera design

- `config.yaml` lists cameras: `webcam: 0` plus named RTSP URLs.
- "start working" starts the watcher thread on the default camera:
  frame diff motion gate → YOLOv8n person check → alert (speak + snapshot
  to `data/snapshots/`, cooldown 30 s).
- "what do you see" grabs a fresh frame → qwen2.5vl → spoken description.
- "stop working" stops the watcher.

## Error handling

- Every tool call wrapped; failures become readable strings for the model.
- Camera/RTSP failures reported per-camera, never fatal.
- Voice components optional: if mic/wake-word init fails, console still works.

## Testing

- Smoke scripts per phase (agent chat, tool dispatch, camera grab, TTS).
- Manual end-to-end: essay-to-desktop-file, open app, describe scene.
