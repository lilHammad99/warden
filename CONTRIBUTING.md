# Contributing to Warden

Thanks for taking an interest. Warden is a local-first assistant, so the most
useful contributions are ones that keep it working offline, on one machine,
with no account and no cloud model.

## Before you start

Open an issue describing what you want to change before writing much code. The
project has a strong house style for tools (below), and it is easier to agree
on the shape of a tool before it is built than after.

## Getting set up

Warden targets Windows and Python 3.11.

```powershell
git clone https://github.com/lilHammad99/warden.git
cd warden
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

You also need [Ollama](https://ollama.com) running locally, with the two models
the assistant uses:

```powershell
ollama pull qwen3:8b
ollama pull moondream
```

Then start it with `run.bat`, or `.venv\Scripts\python -m jarvis`.

## Running the tests

```powershell
.venv\Scripts\python -m tests.smoke            # the safe set: no model, no hardware
.venv\Scripts\python -m tests.smoke memory     # one section
.venv\Scripts\python -m tests.smoke all        # everything, including live sections
```

The **safe set** is the default and is what a pull request must keep green. It
needs no model, no camera, no microphone and no internet, so it is
deterministic. Sections that need real hardware or the network — `network`,
`system`, `camera`, `vision`, `tts`, `watch`, `hud`, `agent`, `e2e` — are
excluded from it and must be run explicitly.

Every new tool needs a section in `tests/smoke.py` covering its happy path, its
containment guard, and the junk-input cases described below.

## The house style for tools

The assistant's brain is a local 8B model. It will eventually pass a wrong
type, a missing argument, an invented argument name, or a path it should not be
allowed to touch. Every tool is written on that assumption:

- **Never raise.** A tool returns a friendly string, including on failure. An
  exception reaching the agent loop is a bug.
- **Stay inside the user's home.** Resolve every path and reject anything
  outside it, including `..` escapes. Reuse `organize._resolve_under_home`
  rather than writing a new check.
- **Be bounded.** Cap file size, entry counts, recursion depth and wall-clock
  time. Say so in the reply when a cap is hit rather than truncating silently.
- **Be forgiving about arguments.** Accept the obvious aliases (`file`, `path`,
  `source`), coerce wrong types, and drop extra arguments.
- **Return pure ASCII**, so the text-to-speech and console never choke.
- **Prefer the standard library.** A new dependency needs a reason, and must be
  pure-Python and work offline.

Read a couple of existing tools in `jarvis/tools/` before writing a new one —
they are all built to this pattern.

## Pull requests

- Keep the change small and focused.
- Match the surrounding code: its naming, comment density and idiom.
- Update `docs/ROADMAP.md` and `CHANGELOG.md` if the change is user-visible.
- Say in the description what you actually ran to verify it.

## Reporting security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).
