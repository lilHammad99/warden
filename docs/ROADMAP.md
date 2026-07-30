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
- [ ] Memory next steps: let Jarvis edit/replace a fact (not just add/forget),
      and surface remembered facts in the HUD
- [ ] Vision upgrade path: qwen2.5vl:3b (needs free RAM) or RAM upgrade
- [ ] Autostart with Windows + system tray icon
- [ ] Phone notifications on watch-mode alerts (e.g. ntfy.sh)
- [ ] Home automation hooks (lights, plugs) if smart devices arrive
- [ ] Bigger brain when hardware allows (qwen3:14b/30b)
