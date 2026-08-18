"""Run a build/dev command inside one of the user's project folders.

This is the counterpart to ``run_command`` (shell.py). That tool runs a strict
allowlist of read-only SYSTEM-inspection commands (ipconfig, ping, tasklist).
This one lets Jarvis actually RUN and TEST the code it writes -- ``python
script.py``, ``pytest``, ``pip install requests``, ``npm test``, ``git status``
-- inside a specific project directory, capturing the output, the errors and the
exit code so the model can see whether what it built works and fix it if not.
It is the piece that turns "Jarvis can write files" into "Jarvis can build and
run a small project".

Safety model (strict, because an 8B local model WILL eventually emit junk):

- **Scoped to a project folder under the user's home.** The working directory
  is resolved and REJECTED unless it lives inside the user's home (same
  boundary as the file tools), so a command can never run in ``C:\\Windows``.
- **Allowlist of build/dev tools only.** Only the executables in ``ALLOWED``
  (python, pip, pytest, node, npm, git, cargo, go, ...) may be launched.
  Anything else is refused with the list, so the model can self-correct.
- **No shell.** The command is parsed into a fixed argv and run with
  ``shell=False``, so ``&``, ``|``, ``>``, ``;`` are inert -- they become plain
  arguments, never a second command cmd.exe would execute.
- **No path-y executables.** The program must be a bare name resolved on PATH
  (via ``shutil.which``); a first token with a slash (``.\\evil.exe``) is
  refused, so only real installed tools run.
- **Outward-facing sub-commands blocked.** Publishing/pushing (``git push``,
  ``npm publish``, ``cargo publish``, ...) is refused -- that is a deploy the
  user should trigger deliberately, not an 8B side effect.
- **Bounded.** A wall-clock timeout, captured + capped output, no popup window.

Never raises: every path returns a plain, pure-ASCII string the model can read.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ..config import HOME
from .find import _coerce
from .organize import _resolve_under_home
from .registry import tool

# bare program name (lower, no extension) -> allowed. shutil.which resolves the
# real executable (so "npm" finds npm.cmd on Windows). Build/dev tools only.
ALLOWED = {
    # Python
    "python", "python3", "py", "pip", "pip3", "pipx", "pytest", "tox",
    # JS / TS
    "node", "npm", "npx", "yarn", "pnpm", "bun", "deno", "tsc",
    # version control
    "git",
    # other common toolchains
    "go", "cargo", "rustc", "rustup",
    "ruby", "gem", "bundle", "rake",
    "java", "javac", "mvn", "gradle", "kotlinc",
    "dotnet", "php", "composer",
    "make", "cmake", "ninja",
}

# (program, first-argument) pairs that PUBLISH or PUSH -- outward-facing, so
# refused. The user should deploy deliberately, not have an 8B model do it.
BLOCKED_SUBCOMMANDS = {
    ("git", "push"),
    ("npm", "publish"),
    ("yarn", "publish"),
    ("pnpm", "publish"),
    ("cargo", "publish"),
    ("gem", "push"),
    ("composer", "global"),
}

DEFAULT_TIMEOUT = 120        # seconds; a test run or install can be slow
MAX_TIMEOUT = 300            # hard cap so a hallucinated timeout can't hang
MAX_COMMAND_LEN = 600        # a command line, not an essay
MAX_STREAM = 4000            # cap stdout / stderr each

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ascii(text: str) -> str:
    """Force output to safe, bounded ASCII (curly quotes etc. replaced)."""
    return (text or "").encode("ascii", "replace").decode("ascii")


def _allowed_list() -> str:
    return ", ".join(sorted(ALLOWED))


def _first_str(*values) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
        if v is not None and not isinstance(v, str):
            s = str(v).strip()
            if s:
                return s
    return ""


def _tokenize(command: str) -> list[str]:
    """Split a command line into argv without a shell. ``posix=False`` keeps
    Windows backslashes intact (``.\\x`` stays ``.\\x``); we then strip a token's
    own surrounding quotes so ``python -c "print(1)"`` yields a clean 'print(1)'.
    Falls back to a plain split if the quoting is malformed."""
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = command.split()
    cleaned = []
    for t in tokens:
        if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
            t = t[1:-1]
        if t:
            cleaned.append(t)
    return cleaned


def _clamp_timeout(value) -> int:
    if value is None or value == "":
        return DEFAULT_TIMEOUT
    try:
        n = int(float(str(value).strip().split()[0]))
    except (ValueError, IndexError):
        return DEFAULT_TIMEOUT
    if n <= 0:
        return DEFAULT_TIMEOUT
    return min(n, MAX_TIMEOUT)


def _resolve_command_and_dir(command, directory, extra):
    """Validate a command + working directory against the full safety model
    (allowlist, no shell, no path-y exe, publish/push blocked, home-contained)
    and resolve the real executable on PATH.

    Shared by run_project_command (synchronous) and the background runner, so
    both apply exactly the same defenses. Returns ``(argv, proj, command)`` on
    success, or ``(None, None, error_string)`` -- a plain ASCII message -- on
    any refusal. Never raises."""
    command = _first_str(command, extra.get("cmd"), extra.get("run"),
                         extra.get("shell"), extra.get("commandline"))
    if not command:
        return None, None, ("Error: tell me what command to run, sir (e.g. "
                            "'pytest' or 'python app.py').")
    command = _coerce(command, MAX_COMMAND_LEN)

    tokens = _tokenize(command)
    if not tokens:
        return None, None, "Error: that command is empty, sir."

    # --- the program must be a bare, allowlisted, build/dev executable ---
    raw_exe = tokens[0]
    if ("/" in raw_exe) or ("\\" in raw_exe):
        return None, None, ("Error: run the program by its name, sir (e.g. "
                            "'python' or 'npm'), not a path. Allowed: "
                            + _allowed_list() + ".")
    exe_name = os.path.splitext(raw_exe)[0].lower()
    if exe_name not in ALLOWED:
        return None, None, (f"Error: '{_ascii(raw_exe)}' is not an allowed "
                            f"program, sir. I can only run build/dev tools: "
                            f"{_allowed_list()}.")

    # --- refuse outward-facing publish/push sub-commands ---
    if len(tokens) > 1:
        sub = tokens[1].lower()
        if (exe_name, sub) in BLOCKED_SUBCOMMANDS:
            return None, None, (f"Error: '{exe_name} {sub}' publishes or pushes "
                                "to a remote, sir; I won't do that automatically "
                                "-- run it yourself when you're ready.")

    # --- resolve the working directory, kept inside the user's home ---
    dir_raw = _first_str(directory, extra.get("dir"), extra.get("folder"),
                         extra.get("path"), extra.get("project"),
                         extra.get("cwd"), extra.get("working_dir"))
    if dir_raw:
        proj, err = _resolve_under_home(dir_raw)
        if proj is None:
            return None, None, (err or "Error: that project folder isn't valid, sir.")
    else:
        proj = Path(HOME).resolve()  # no folder given -> the home folder
    if not proj.exists():
        return None, None, (f"Error: I can't find the folder "
                            f"'{_ascii(str(proj))}', sir. Make it first, or tell "
                            "me the right project folder.")
    if not proj.is_dir():
        return None, None, (f"Error: '{_ascii(proj.name)}' is a file, not a "
                            "folder, sir; give me the project folder to run in.")

    # --- resolve the real executable on PATH (npm -> npm.cmd, etc.) ---
    exe_path = shutil.which(raw_exe) or shutil.which(exe_name)
    if not exe_path:
        return None, None, (f"Error: '{exe_name}' doesn't seem to be installed "
                            "on this PC, sir (it isn't on the PATH).")

    argv = [exe_path] + tokens[1:]
    return argv, proj, command


@tool(
    "run_project_command",
    "Run ONE build or development command inside a project folder and return "
    "its output, errors and exit code -- so you can actually run and test code "
    "you have written. Use this to run a script, run tests, install packages, "
    "or check a repo: e.g. 'python app.py', 'pytest', 'pip install requests', "
    "'npm test', 'node index.js', 'git status'. Allowed programs only: python, "
    "pip, pytest, node, npm, npx, yarn, git, go, cargo, java, dotnet, make and "
    "similar build tools. 'directory' is the project folder to run in (under "
    "the user's home). This is for running/building code; for reading PC info "
    "like your IP or running processes use run_command instead.",
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command to run, e.g. 'pytest' or "
                "'python script.py' or 'npm install'.",
            },
            "directory": {
                "type": "string",
                "description": "Project folder to run the command in, e.g. "
                "'Desktop/myapp'. Must be inside the user's home.",
            },
            "timeout": {
                "type": "integer",
                "description": "Optional seconds to wait before giving up "
                f"(default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT}).",
            },
        },
        "required": ["command"],
    },
)
def run_project_command(command: str = "", directory: str = "",
                        timeout=None, **extra) -> str:
    argv, proj, value = _resolve_command_and_dir(command, directory, extra)
    if argv is None:
        return value  # a plain, refusal message
    command = value
    secs = _clamp_timeout(timeout if timeout is not None
                          else extra.get("timeout"))

    # --- run it, fully sandboxed from the shell, never crash the agent ---
    try:
        proc = subprocess.run(
            argv,
            cwd=str(proj),
            capture_output=True,
            text=True,
            timeout=secs,
            shell=False,
            creationflags=_NO_WINDOW,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return (f"The command '{_ascii(command)}' timed out after {secs}s, sir "
                "-- it may need longer, or it's waiting for input it won't get.")
    except FileNotFoundError:
        return f"The program '{exe_name}' isn't available on this PC, sir."
    except OSError as e:
        return f"Error running '{_ascii(command)}': {_ascii(str(e))}"
    except Exception as e:  # last-resort guard
        return f"Error running '{_ascii(command)}': {_ascii(str(e))}"

    return _format(command, proj, proc.returncode,
                   proc.stdout or "", proc.stderr or "")


def _clip(stream: str) -> str:
    stream = _ascii(stream).strip()
    if len(stream) > MAX_STREAM:
        stream = stream[:MAX_STREAM] + "\n...[truncated]"
    return stream


def _where(proj: Path) -> str:
    """A short home-relative label for a project folder ('.' -> home)."""
    try:
        rel = proj.relative_to(Path(HOME).resolve())
        return str(rel) if str(rel) != "." else "your home folder"
    except ValueError:
        return _ascii(str(proj))


def _format(command: str, proj: Path, code: int, out: str, err: str) -> str:
    where = _where(proj)
    status = "succeeded" if code == 0 else f"failed (exit code {code})"
    lines = [f"Ran '{_ascii(command)}' in {where} -- {status}."]
    out, err = _clip(out), _clip(err)
    if out:
        lines.append("Output:\n" + out)
    if err:
        lines.append("Errors:\n" + err)
    if not out and not err:
        lines.append("(the command produced no output.)")
    return "\n".join(lines)
