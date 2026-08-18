# Warden — your local AI assistant

An assistant that watches and acts, running 100% on this PC. It talks,
listens, sees your cameras, writes files, opens apps, and drives its own
browser. No cloud model, no account, nothing leaves the machine.

## Start it

Double-click **`run.bat`** (or from a terminal: `.venv\Scripts\python -m jarvis`).

Requirements already set up: Python venv in `.venv`, Ollama with
`qwen3:8b` (brain) and `qwen2.5vl:3b` (eyes).

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
- `data/snapshots/` — photos saved when watch mode sees someone
- `docs/ROADMAP.md` — what's next; `docs/DESIGN.md` — how it works

The Python package is still named `jarvis/`, from the project's working title.
