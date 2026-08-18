"""Run a build/dev command in the BACKGROUND, then poll it.

``run_project_command`` (runner.py) runs a command and WAITS for it to finish
before Jarvis can say anything -- fine for a quick script, but it blocks
Jarvis's single-threaded turn for a slow ``pip install``, a long test suite, or
a dev server (``npm run dev``, ``python -m http.server``) that never exits at
all. This module starts the same kind of command WITHOUT waiting: it returns a
short job id immediately, and later calls report the job's output and whether it
has finished. So Jarvis can kick off a long job, answer other questions, and
check back later, instead of freezing the conversation until it ends.

Three tools:

- ``start_background_command`` -- launch a command, return a job id at once.
- ``check_background_command`` -- report a job's progress/output (or list jobs).
- ``stop_background_command`` -- end a running job (e.g. a dev server).

Safety is NOT re-implemented here: the command line + working directory go
through ``runner._resolve_command_and_dir``, so the SAME defenses apply --
home-containment, the build/dev allowlist, ``shell=False`` (metacharacters
inert), no path-y executables, and publish/push refused. Each job's output is
captured off the process's pipes by daemon reader threads into a bounded buffer,
so a chatty command can never deadlock on a full pipe or exhaust memory.

Never raises: every path returns a plain, pure-ASCII string.
"""

import subprocess
import threading
import time
import uuid
from pathlib import Path

from .find import _coerce
from .registry import tool
from .runner import (MAX_COMMAND_LEN, _NO_WINDOW, _ascii, _clip, _first_str,
                     _resolve_command_and_dir, _where)

MAX_JOBS = 8            # concurrent RUNNING jobs (a hallucination can't fork-bomb)
MAX_LIFETIME = 1800     # seconds a background job may run before we stop it (30m)
MAX_FINISHED = 20       # keep this many finished jobs around for re-checking
MAX_CAPTURE = 200_000   # bytes retained per stream (older output past this dropped)

# job_id -> dict(popen, out_buf, err_buf, lock, threads, command, where, start,
#                done, code, end, stopped, truncated)
_JOBS: "dict[str, dict]" = {}
_JOBS_LOCK = threading.Lock()


def _reader(pipe, buf: bytearray, lock: threading.Lock, flag: dict):
    """Drain one pipe into a bounded buffer on its own thread; once the buffer
    is full the rest is discarded (and noted) so memory stays bounded and the
    child never blocks on a full pipe."""
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            with lock:
                room = MAX_CAPTURE - len(buf)
                if room > 0:
                    buf.extend(chunk[:room])
                else:
                    flag["truncated"] = True
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def _refresh(job: dict) -> None:
    """Update one job's finished/exit state; stop it if it has outlived the cap."""
    if job["done"]:
        return
    proc = job["popen"]
    code = proc.poll()
    if code is not None:
        job["done"] = True
        job["code"] = code
        job["end"] = time.time()
    elif time.time() - job["start"] > MAX_LIFETIME:
        _terminate(proc)
        job["done"] = True
        job["stopped"] = True
        job["stop_reason"] = "limit"
        job["code"] = proc.poll()
        job["end"] = time.time()


def _terminate(proc) -> None:
    """Best-effort stop: ask nicely, then force. Never raises."""
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _prune() -> None:
    """Forget the oldest FINISHED jobs beyond MAX_FINISHED so the store can't
    grow without bound over a long session."""
    finished = [(j["start"], jid) for jid, j in _JOBS.items() if j["done"]]
    if len(finished) <= MAX_FINISHED:
        return
    finished.sort()
    for _, jid in finished[:len(finished) - MAX_FINISHED]:
        _JOBS.pop(jid, None)


def _snapshot(job: dict) -> "tuple[str, str]":
    """Current captured stdout/stderr for a job, as text (decoded, unclipped)."""
    with job["lock"]:
        out = bytes(job["out_buf"]).decode("utf-8", "replace")
        err = bytes(job["err_buf"]).decode("utf-8", "replace")
    return out, err


def _elapsed(job: dict) -> str:
    end = job.get("end") or time.time()
    secs = max(0, int(end - job["start"]))
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m {secs % 60}s"


def _report(job_id: str, job: dict) -> str:
    """A full progress report for one job: status line + bounded output."""
    _refresh(job)
    out, err = _snapshot(job)
    out, err = _clip(out), _clip(err)
    if job["done"]:
        if job.get("stopped"):
            why = (" (it ran past the time limit)"
                   if job.get("stop_reason") == "limit" else "")
            head = (f"Background job {job_id} ('{job['command']}') was stopped "
                    f"after {_elapsed(job)}{why}.")
        else:
            code = job.get("code")
            verd = "succeeded" if code == 0 else f"failed (exit code {code})"
            head = (f"Background job {job_id} ('{job['command']}') {verd} "
                    f"after {_elapsed(job)}, in {job['where']}.")
    else:
        head = (f"Background job {job_id} ('{job['command']}') is still running "
                f"({_elapsed(job)} so far), in {job['where']}.")
    lines = [head]
    if job["flag"].get("truncated"):
        lines.append("(output was long; showing part of it.)")
    if out:
        lines.append("Output so far:\n" + out if not job["done"]
                     else "Output:\n" + out)
    if err:
        lines.append("Errors:\n" + err)
    if not out and not err:
        lines.append("(no output yet.)" if not job["done"]
                     else "(the command produced no output.)")
    return "\n".join(lines)


@tool(
    "start_background_command",
    "Start a build or development command in the BACKGROUND and return a job "
    "id immediately, WITHOUT waiting for it to finish. Use this instead of "
    "run_project_command when the command may take a long time or never exits "
    "on its own -- a slow 'pip install' or 'npm install', a long test suite, "
    "or a dev server like 'npm run dev' or 'python -m http.server'. It returns "
    "a job id; call check_background_command with that id to see its output and "
    "whether it has finished, and stop_background_command to end it. Same "
    "allowed programs and safety as run_project_command (python, pip, pytest, "
    "node, npm, git and similar; project folders under the user's home only). "
    "For a quick command whose result you need right now, use "
    "run_project_command instead.",
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command to run in the background, e.g. "
                "'npm install' or 'pytest' or 'python -m http.server'.",
            },
            "directory": {
                "type": "string",
                "description": "Project folder to run in, e.g. 'Desktop/myapp'. "
                "Must be inside the user's home.",
            },
        },
        "required": ["command"],
    },
)
def start_background_command(command: str = "", directory: str = "",
                            **extra) -> str:
    with _JOBS_LOCK:
        for job in _JOBS.values():
            _refresh(job)
        running = sum(1 for j in _JOBS.values() if not j["done"])
        if running >= MAX_JOBS:
            return (f"Error: {running} background commands are already running, "
                    "sir -- that's the limit. Check or stop one first "
                    "(check_background_command / stop_background_command).")

    argv, proj, value = _resolve_command_and_dir(command, directory, extra)
    if argv is None:
        return value  # a plain refusal message (same defenses as run_project_command)
    command = value

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(proj),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            shell=False,
            creationflags=_NO_WINDOW,
            bufsize=0,
        )
    except FileNotFoundError:
        return f"The program in '{_ascii(command)}' isn't available on this PC, sir."
    except OSError as e:
        return f"Error starting '{_ascii(command)}': {_ascii(str(e))}"
    except Exception as e:  # last-resort guard
        return f"Error starting '{_ascii(command)}': {_ascii(str(e))}"

    out_buf, err_buf = bytearray(), bytearray()
    lock = threading.Lock()
    flag: dict = {"truncated": False}
    t_out = threading.Thread(target=_reader,
                             args=(proc.stdout, out_buf, lock, flag), daemon=True)
    t_err = threading.Thread(target=_reader,
                             args=(proc.stderr, err_buf, lock, flag), daemon=True)
    t_out.start()
    t_err.start()

    job_id = uuid.uuid4().hex[:8]
    where = _where(proj)
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "popen": proc, "out_buf": out_buf, "err_buf": err_buf, "lock": lock,
            "threads": (t_out, t_err), "command": command, "where": where,
            "start": time.time(), "done": False, "code": None, "end": None,
            "stopped": False, "flag": flag,
        }
        _prune()
    # let it get going so an instant failure (bad entry point) is visible at once
    time.sleep(0.05)
    return (f"Started '{command}' in the background in {where} (job {job_id}). "
            f"I'll keep it running; ask me to check job {job_id} to see how it's "
            "doing, or to stop it.")


@tool(
    "check_background_command",
    "Check on a background command started with start_background_command: "
    "reports whether it has finished, its exit status, and its output so far. "
    "Pass the job id you were given. Call this with no job id to list all "
    "background jobs and whether each is still running.",
    {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "The job id from start_background_command. Omit "
                "to list all background jobs.",
            },
        },
        "required": [],
    },
)
def check_background_command(job_id: str = "", **extra) -> str:
    job_id = _first_str(job_id, extra.get("id"), extra.get("job"),
                        extra.get("name"), extra.get("jobid"))
    job_id = _coerce(job_id, 64).strip() if job_id else ""

    with _JOBS_LOCK:
        for job in _JOBS.values():
            _refresh(job)
        if not _JOBS:
            return "There are no background commands, sir."
        if not job_id:
            lines = ["Background commands:"]
            for jid, j in _JOBS.items():
                if j["done"]:
                    if j.get("stopped"):
                        state = "stopped"
                    else:
                        state = ("finished ok" if j.get("code") == 0
                                 else f"finished (exit {j.get('code')})")
                else:
                    state = f"running ({_elapsed(j)})"
                lines.append(f"- {jid}: '{j['command']}' -- {state}")
            return "\n".join(lines)
        job = _JOBS.get(job_id)
        if job is None:
            known = ", ".join(_JOBS.keys())
            return (f"I don't have a background job '{_ascii(job_id)}', sir. "
                    + (f"Current jobs: {known}." if known
                       else "There are no background commands."))
        return _report(job_id, job)


@tool(
    "stop_background_command",
    "Stop a background command started with start_background_command -- e.g. a "
    "dev server you no longer need, or a job that's taking too long. Pass its "
    "job id. This ends the process; it does not delete any files it created.",
    {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "The job id from start_background_command.",
            },
        },
        "required": ["job_id"],
    },
)
def stop_background_command(job_id: str = "", **extra) -> str:
    job_id = _first_str(job_id, extra.get("id"), extra.get("job"),
                        extra.get("name"), extra.get("jobid"))
    job_id = _coerce(job_id, 64).strip() if job_id else ""
    if not job_id:
        return ("Error: tell me which background job to stop, sir (its job id). "
                "Call check_background_command to list them.")

    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            known = ", ".join(_JOBS.keys())
            return (f"I don't have a background job '{_ascii(job_id)}', sir. "
                    + (f"Current jobs: {known}." if known
                       else "There are no background commands."))
        _refresh(job)
        if job["done"]:
            return (f"Background job {job_id} ('{job['command']}') has already "
                    "finished, sir -- nothing to stop.")
        _terminate(job["popen"])
        job["done"] = True
        job["stopped"] = True
        job["stop_reason"] = "user"
        job["code"] = job["popen"].poll()
        job["end"] = time.time()
    return (f"Stopped background job {job_id} ('{job['command']}') after "
            f"{_elapsed(job)}, sir.")
