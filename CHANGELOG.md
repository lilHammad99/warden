# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions below 1.0.0 were tagged retrospectively from the development history;
the project was private until 1.0.0.

## [1.0.0] — 2026-08-18

First public release, as **Warden**.

### Added
- **The Mind** (`JARVIS.md`, `jarvis/mind.py`) — a persistent "how to think"
  core loaded ahead of the tool rules, so the local 8B brain stays on the
  thread, admits what it does not know, and does not give up after one try.
- **Earned lessons** (`learn_lesson` / `forget_lesson`) — short lessons the
  assistant keeps from experience and re-reads on later turns.
- Piper text-to-speech with barge-in, so you can interrupt a reply by speaking.
- An MIT licence, a changelog, and contribution, security and conduct guides.

### Changed
- Renamed the project from its working title to **Warden**. The Python package
  is still `jarvis/` and the spoken wake phrase is still "Hey Jarvis" — that
  phrase is a pretrained openWakeWord model, and changing it needs a
  custom-trained one.
- The startup banner now reports the version.

### Fixed
- **Tool router**: `specs_for` applied its limit below the core-tool count and
  silently hid 54 tools, including `date_add`, `get_weather` and the PDF
  reader. Those tools were registered but unreachable.
- Six agent-loop defects found by testing the real loop rather than the tools
  in isolation, including a wrong word count reaching the user.

### Security
- Removed the maintainer's name, email and machine paths from the tree and from
  every commit, and removed the development machine's hardware fingerprint
  (GPU model, memory size, OS build, interpreter and runtime patch versions).
  Stored data — remembered facts, tasks, reminders, lessons — is gitignored and
  has never been committed.

## [0.4.0] — 2026-07-31

### Added
- Document writers: `create_pdf`, `create_docx`, `create_xlsx`.
- `get_weather` for a local forecast.

### Fixed
- A per-question tool router and a loop guard, which together stopped the small
  model looping on tool selection.
- Text-to-speech now speaks every reply rather than dropping some.
- Hardened the camera tools and audited every registered tool.

## [0.3.0] — 2026-07-31

### Added
- Data and text handling: `find_duplicates`, `file_info`, `get_json_value`,
  `compare_files`, `read_pdf`, `read_excel`, `convert_data`, `extract_items`,
  `summarize_numbers`, `generate_password`, `encode_text`.
- First two dependencies, both pure-Python and offline: `pypdf`, `openpyxl`.
- Smoke fixtures isolated in per-run sandboxes so tests cannot collide.

## [0.2.0] — 2026-07-30

### Added
- Long-term memory (`remember` / `recall` / `forget` / `update_fact`).
- A persistent to-do list, reminders and timers.
- The file family: find, search inside, recently changed, move, copy, rename,
  zip, unzip, delete to the Recycle Bin, folder size, reveal in Explorer.
- Document and data readers: Word, OpenDocument, CSV/TSV, JSON/JSON Lines.
- Exact-computation tools: calculator, unit converter, date arithmetic,
  word and character counts.
- Safe shell execution and self-correcting tool dispatch with `list_tools`.

## [0.1.0] — 2026-07-29

### Added
- Initial scaffold: agent loop, tool registry, vision, voice and a headed
  browser the assistant drives itself.
- Smoke test suite and the session-continuity handoff document.
- Vision switched to `moondream` so the chat and vision models are not resident
  at the same time on a memory-constrained machine.

[1.0.0]: https://github.com/lilHammad99/warden/releases/tag/v1.0.0
