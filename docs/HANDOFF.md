# HANDOFF — Jarvis build status (2026-07-29)

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

## State when this file was written

ALL CODE IS WRITTEN for all 4 phases, committed, but NOT YET TESTED,
because these background jobs were still running:

1. `ollama pull qwen3:8b` — main model (~5.2 GB)
2. pip install into `.venv`: ollama pyyaml requests ddgs psutil pyttsx3
   sounddevice numpy opencv-python mss pycaw comtypes faster-whisper
   openwakeword ultralytics playwright
3. After pip finishes, still TODO:
   - `.venv\Scripts\playwright install chromium` (browser binaries)
   - `.venv\Scripts\python -c "import openwakeword.utils; openwakeword.utils.download_models()"`
     (wake-word model files, needed once)
   - YOLO weights (`yolov8n.pt`) auto-download on first watch-mode use

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
