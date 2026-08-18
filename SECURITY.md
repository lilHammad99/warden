# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a vulnerability

Please report privately, not in a public issue.

Use GitHub's private reporting: go to the
[Security tab](https://github.com/lilHammad99/warden/security/advisories/new)
and open a draft advisory. That is visible only to the maintainer until a fix
is ready.

Include what you did, what happened, and what you expected. A proof of concept
helps. Expect a first reply within a week; this is a personal project, not a
staffed one.

## What Warden can do to the machine it runs on

This matters more than usual here, because Warden is an assistant that acts,
driven by a local language model that can be wrong. By design it can:

- read, write, move, copy and archive files;
- delete files and folders — always to the Recycle Bin, so a delete is undoable,
  and never with a hard-delete path;
- run build and development commands inside a project folder, and a fixed
  allowlist of read-only system commands;
- drive a visible browser, open applications and websites, read the clipboard;
- capture the webcam and the microphone.

Every one of those is constrained to the user's home directory. Paths are
resolved and rejected if they escape it, including via `..`, so the assistant
cannot reach `C:\Windows` or anything outside the user's own folders. Archive
extraction is zip-slip proof and bounded against zip bombs. Deletes are size
capped, because Windows permanently removes items too large for the Recycle Bin.

Those boundaries are the security model, and a bug in them is a genuine
vulnerability. Please report it.

## What Warden does not do

- It does not send your data anywhere. The model runs locally through Ollama.
  The only outbound traffic is the web search and weather tools, and the browser
  when you ask it to open a page.
- It does not require an account, an API key, or a network connection to think.
- It does not store anything outside the repository's gitignored `data/`
  directory.

## Scope

Findings in the containment boundaries, the archive handling, the command
allowlist, or the deletion caps are in scope. The local model saying something
wrong is not a vulnerability — it is an 8B model, and the tools are written on
the assumption that it will misbehave.
