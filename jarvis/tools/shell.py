"""Safe shell command execution for Jarvis.

Gives the assistant a way to answer real questions about the machine and
network — "what's my IP?", "is the internet up?", "what's running?" — by
running actual system commands, without ever handing an 8B model a raw
shell.

Safety model (this whole file is the strict error handling the loop asks
for, because a hallucinating local model WILL eventually emit something like
``ipconfig & del /q *``):

- **Allowlist only.** Only the read-only, non-destructive commands in
  ``ALLOWED`` can run. Anything else is refused with the list of what's
  permitted, so the model can correct itself.
- **No shell.** Commands run via ``subprocess.run`` with a fixed argv and
  ``shell=False`` — the model's text is never interpreted by cmd.exe, so
  ``&``, ``|``, ``>``, ``;`` and friends are inert.
- **Arguments are whitelisted per command.** Only ``ping``/``nslookup`` take
  an argument, and it must match a strict host/IP pattern; every other
  command ignores extra text entirely.
- **Bounded.** Hard timeout, capped output, no popup console window.
"""

import re
import subprocess

from .registry import tool

# name the model uses -> fixed, safe argv (no shell interpolation ever)
ALLOWED: dict[str, list[str]] = {
    "ipconfig": ["ipconfig", "/all"],   # network adapters / IP / DNS
    "hostname": ["hostname"],           # this PC's name
    "whoami": ["whoami"],               # current user
    "ver": ["cmd", "/c", "ver"],        # Windows version
    "tasklist": ["tasklist"],           # running processes
    "getmac": ["getmac"],               # MAC addresses
    "systeminfo": ["systeminfo"],       # full system summary (slow-ish)
    "netstat": ["netstat", "-n"],       # active connections
    "ping": ["ping", "-n", "2"],        # connectivity test (needs a host)
    "nslookup": ["nslookup"],           # DNS lookup (needs a host)
}

# commands that require exactly one host/IP argument
NEEDS_HOST = {"ping", "nslookup"}

# a plausible hostname or IPv4/IPv6 literal — nothing else may reach argv
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._:-]{0,251}[A-Za-z0-9])?$")

TIMEOUT_SECONDS = 20
MAX_OUTPUT = 3000

# don't flash a console window when running from the GUI/voice loop
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _allowed_list() -> str:
    return ", ".join(sorted(ALLOWED))


@tool(
    "run_command",
    "Run one safe, read-only system command to inspect this PC or its "
    "network, and return its output. Allowed commands only: ipconfig, "
    "hostname, whoami, ver, tasklist, getmac, systeminfo, netstat, ping, "
    "nslookup. 'ping' and 'nslookup' need a host in the 'target' argument "
    "(e.g. google.com). Cannot change or delete anything.",
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "One of: ipconfig, hostname, whoami, ver, "
                "tasklist, getmac, systeminfo, netstat, ping, nslookup",
            },
            "target": {
                "type": "string",
                "description": "Host or IP for ping/nslookup, e.g. google.com",
            },
        },
        "required": ["command"],
    },
)
def run_command(command: str = "", target: str = "") -> str:
    # --- validate the command name (model may pass junk / wrong type) ---
    if not isinstance(command, str):
        command = str(command or "")
    # tolerate the model jamming args in, e.g. "ping google.com" or "ipconfig /all"
    tokens = command.replace("\x00", "").strip().lower().split()
    if not tokens:
        return "Error: no command given, sir. Allowed: " + _allowed_list()
    name = tokens[0].lstrip("/-")  # strip a stray leading slash/dash
    if name not in ALLOWED:
        return (f"Error: '{name}' is not an allowed command, sir. "
                f"Allowed: {_allowed_list()}.")

    argv = list(ALLOWED[name])

    # --- validate the host argument for commands that need one ---
    if name in NEEDS_HOST:
        host = (target or "").strip()
        if not host and len(tokens) > 1:
            host = tokens[1]          # model put the host in `command`
        host = host.strip().strip('"').strip("'")
        if not host:
            return f"Error: {name} needs a host, sir (e.g. google.com)."
        if len(host) > 253 or not _HOST_RE.match(host):
            return (f"Error: '{host}' is not a valid host name or IP, sir — "
                    "refusing to run it.")
        argv.append(host)

    # --- run it, fully sandboxed from the shell ---
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
            creationflags=_NO_WINDOW,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"The {name} command timed out after {TIMEOUT_SECONDS}s, sir."
    except FileNotFoundError:
        return f"The {name} command isn't available on this PC, sir."
    except Exception as e:  # last-resort guard — never crash the agent
        return f"Error running {name}: {e}"

    out = (proc.stdout or "").strip()
    if not out:
        out = (proc.stderr or "").strip()
    if not out:
        return f"{name} ran but produced no output (exit {proc.returncode})."
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n...[truncated]"
    return out
