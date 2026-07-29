# Jarvis Roadmap

## Done
- (being built — updated as phases land)

## Phase 1 — Core agent (text)
- [ ] Ollama tool-calling agent loop (`qwen3:8b`)
- [ ] Text console
- [ ] Tools: files (create/read/write/list), apps & websites, system info,
      screenshots, volume, web search

## Phase 2 — Eyes
- [ ] Webcam + RTSP camera manager (add IP cams in `config.yaml`)
- [ ] "what do you see" — local vision model description
- [ ] "start working" — watch mode: motion + person detection, spoken alert
      + snapshot saved

## Phase 3 — Voice
- [ ] "Hey Jarvis" wake word (openWakeWord)
- [ ] Local speech-to-text (faster-whisper)
- [ ] Talk back (pyttsx3 / SAPI5)

## Phase 4 — Hands on the web
- [ ] Headed Chromium controlled by the agent (Playwright):
      open page, click, type, read, search

## Future work (not yet built)
- [ ] Better voice: Piper or Kokoro TTS (natural Jarvis-like voice)
- [ ] Streaming responses + barge-in (interrupt Jarvis while he talks)
- [ ] Face recognition ("it's you" vs "unknown person") — opt-in
- [ ] Multi-camera watch simultaneously; camera dashboard window
- [ ] Long-term memory for Jarvis (remember facts about you between runs)
- [ ] Home automation hooks (lights, plugs) if you get smart devices
- [ ] Bigger brain when hardware allows (qwen3:14b/30b, GPU upgrade)
- [ ] Autostart with Windows + tray icon
- [ ] Phone notifications on watch-mode alerts
