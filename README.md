# Warden — your local AI assistant

[![tests](https://github.com/lilHammad99/warden/actions/workflows/ci.yml/badge.svg)](https://github.com/lilHammad99/warden/actions/workflows/ci.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#requirements)

An assistant that watches and acts, running entirely on your own PC. It talks,
listens, sees your cameras, writes files, opens apps, and drives its own
browser. No cloud model, no account, no API key — nothing leaves the machine.

The brain is a local 8B model served by [Ollama](https://ollama.com). Around it
sits the part that actually matters: 87 tools with strict boundaries, a router
that picks the few worth showing the model on any given question, and a "mind"
that keeps a small model on the thread instead of letting it wander.

## Requirements

- Windows 10 or 11
- Python 3.11
- [Ollama](https://ollama.com), running locally
- A webcam, if you want the vision features
- About 6 GB of disk for the models

## Install

```powershell
git clone https://github.com/lilHammad99/warden.git
cd warden
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

Then pull the two models:

```powershell
ollama pull qwen3:8b
ollama pull moondream
```

## Run it

Double-click **`run.bat`**, or:

```powershell
.venv\Scripts\python -m jarvis
```

## Talk to it

- **Voice:** say **"Hey Jarvis"**, wait for "Yes, sir?", then speak.
- **Text:** just type in the console.

The spoken wake phrase is still "Hey Jarvis" — it comes from openWakeWord's
pretrained model, and a new phrase needs a custom-trained one. Set
`voice.wake_word` in `config.yaml` to use a different bundled phrase.

## Things to try

| Say / type | What happens |
|---|---|
| `start working` | Watches the camera, alerts + snapshot when someone appears |
| `what do you see?` | Describes the current camera view |
| `stop working` | Stops watching |
| `make a file on my desktop and write an essay about public health` | Writes the file |
| `open chrome` / `open youtube` | Opens apps and sites |
| `how is my battery?` | System status |
| `search the web for today's weather in Lisbon` | Web answers |
| `use your browser to open wikipedia and search for Mars` | Drives a visible browser |
| `find duplicate files in my downloads` | Content-based duplicate finder |
| `read my resume.pdf` | Reads PDF, Word, OpenDocument, Excel, CSV, JSON |
| `remind me in 10 minutes to stretch` | Reminders and a to-do list |

Say `list tools` to see everything it can do.

## What it can do to your machine

Warden acts on your files, so it is worth knowing the boundaries. It can read,
write, move, copy, archive and delete files, run build commands in a project
folder, drive a browser, and use the camera and microphone.

Everything is confined to your home directory — paths that escape it, including
via `..`, are refused, so it cannot touch `C:\Windows` or anything outside your
own folders. Deletes always go to the Recycle Bin and are undoable; there is no
hard-delete path. Archive extraction is zip-slip proof and bounded against zip
bombs.

The full picture is in [SECURITY.md](SECURITY.md).

## Add your IP / CCTV cameras

Edit `config.yaml`:

```yaml
cameras:
  webcam: 0
  front_door: rtsp://user:password@192.168.1.50:554/stream1
default_camera: front_door
```

Then: `start working on front door`.

## Where things live

- `config.yaml` — models, cameras, voice settings, app aliases
- `jarvis/tools/` — one module per tool family
- `JARVIS.md` — the mind: how the assistant is told to think
- `data/` — remembered facts, tasks, reminders, lessons (gitignored, stays local)
- `docs/DESIGN.md` — how it works; `docs/ROADMAP.md` — what's next

## Tests

```powershell
.venv\Scripts\python -m tests.smoke        # the safe set: no model, no hardware
.venv\Scripts\python -m tests.smoke memory # one section
```

CI runs the subset that needs no model, no network and no devices. The rest is
run locally, because a headless runner has no camera, microphone or Ollama.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Tools follow a strict house style —
never raise, stay inside the user's home, stay bounded — because the model
driving them is small and will eventually pass something wrong.

## Naming

The project is Warden. The Python package is still `jarvis/`, and the assistant
still answers to "Hey Jarvis" — both from the working title, both kept
deliberately.

## Licence

MIT — see [LICENSE](LICENSE). Changes are recorded in [CHANGELOG.md](CHANGELOG.md).
