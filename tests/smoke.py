"""Smoke tests: run with  .venv\\Scripts\\python -m tests.smoke [section]
Sections: imports, tools, memory, shell, find, clipboard, tasks, calc, agent,
camera, vision, tts, hud, watch, e2e, all (default: safe set)
"""

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

PASS, FAIL = "  [PASS]", "  [FAIL]"
failures = []


def check(name, fn):
    try:
        out = fn()
        print(f"{PASS} {name}" + (f" -> {str(out)[:120]}" if out else ""))
    except Exception as e:
        failures.append(name)
        print(f"{FAIL} {name}: {e}")


def t_imports():
    def _all():
        from jarvis import agent, app, config  # noqa
        from jarvis.tools import apps, browser, calc, camera, clipboard, files, find, memory, registry, shell, system, tasks, web  # noqa
        from jarvis.vision import cameras, describe, watcher  # noqa
        from jarvis.voice import loop, stt, tts, wake  # noqa
        return "all modules import"
    check("imports", _all)


def t_tools():
    from jarvis.tools import files, registry, system
    from jarvis.tools import apps, web, camera  # noqa: F401  (register)
    check("registry has tools", lambda: f"{len(registry.specs())} tools")
    check("get_time", lambda: registry.dispatch("get_time", {}))
    check("system_info", lambda: registry.dispatch("system_info", {}))
    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), "jarvis_smoke.txt")
    check("write_file", lambda: registry.dispatch("write_file", {"path": tmp, "content": "hello"}))
    check("read_file", lambda: registry.dispatch("read_file", {"path": tmp}))


def t_memory():
    """Exercises long-term memory + its defenses against 8B hallucinations.
    No model needed, so it lives in the safe set."""
    from jarvis.tools import memory as mem
    from jarvis.tools import registry

    # isolate: use a temp store so we never touch the user's real memory
    import tempfile, os, pathlib
    mem._STORE = pathlib.Path(tempfile.gettempdir()) / "jarvis_mem_smoke.json"
    for p in (mem._STORE, mem._STORE.with_name("memory.corrupt.json")):
        if p.exists():
            os.remove(p)

    def happy_path():
        assert "Remembered" in registry.dispatch("remember", {"fact": "The user's name is the user"})
        assert "the user" in registry.dispatch("recall", {"query": "name"})
        assert mem.count() == 1
        # remember/recall show up in the injected preamble
        assert "the user" in mem.memory_preamble()
        return "remember/recall/preamble ok"
    check("memory happy path", happy_path)

    def dedup():
        registry.dispatch("remember", {"fact": "The user's name is the user"})
        return f"count still {mem.count()} (deduped)" if mem.count() == 1 \
            else (_ for _ in ()).throw(AssertionError("duplicate stored"))
    check("memory dedup", dedup)

    def hallucination_guards():
        # empty / whitespace / wrong-type args must NOT crash or store junk
        assert "Error" in registry.dispatch("remember", {"fact": "   "})
        assert "Error" in registry.dispatch("remember", {"fact": ""})
        assert registry.dispatch("remember", {}).startswith(("Error", "Remembered", "Already"))
        assert "Error" in registry.dispatch("forget", {"query": ""})
        # over-long "fact" (essay dump) is truncated, not rejected or unbounded
        long = registry.dispatch("remember", {"fact": "x" * 5000})
        assert "shortened" in long
        return f"guards held, count={mem.count()}"
    check("memory hallucination guards", hallucination_guards)

    def forget_flow():
        before = mem.count()
        assert "Forgotten" in registry.dispatch("forget", {"query": "the user"})
        assert mem.count() == before - 1
        assert "Nothing in memory matches" in registry.dispatch("forget", {"query": "zzzz"})
        return "forget ok"
    check("memory forget", forget_flow)

    def corrupt_store_recovers():
        mem._STORE.write_text("{ this is not valid json ", encoding="utf-8")
        # _load must not raise; corrupt file set aside, store treated as empty
        assert mem.count() == 0
        assert mem._STORE.with_name("memory.corrupt.json").exists()
        return "corrupt store recovered"
    check("memory corrupt-store recovery", corrupt_store_recovers)


def t_shell():
    """Exercises the safe run_command tool + its defenses. No model needed."""
    from jarvis.tools import shell  # noqa: F401  (register)
    from jarvis.tools import registry

    def happy_path():
        out = registry.dispatch("run_command", {"command": "whoami"})
        assert "Error" not in out and out.strip(), f"whoami gave: {out!r}"
        assert registry.dispatch("run_command", {"command": "hostname"}).strip()
        return "whoami/hostname ran"
    check("shell happy path", happy_path)

    def allowlist_blocks():
        # anything not on the allowlist is refused, not run
        for bad in ("del", "rm -rf /", "format c:", "shutdown", "powershell"):
            r = registry.dispatch("run_command", {"command": bad})
            assert "not an allowed command" in r, f"{bad!r} not blocked: {r}"
        return "disallowed commands blocked"
    check("shell allowlist", allowlist_blocks)

    def injection_is_inert():
        # shell metacharacters can't escape: only the first token is parsed,
        # and it isn't on the allowlist, so the whole thing is refused
        r = registry.dispatch("run_command", {"command": "ipconfig & del /q *"})
        # 'ipconfig' IS allowed; the '& del ...' is ignored (never shelled)
        assert "Error" not in r or "not an allowed" in r
        r2 = registry.dispatch("run_command", {"command": "whoami; rm -rf ~"})
        assert "not an allowed command" in r2  # 'whoami;' != 'whoami'...
        return "injection inert"
    check("shell injection inert", injection_is_inert)

    def host_validation():
        assert "needs a host" in registry.dispatch("run_command", {"command": "ping"})
        bad = registry.dispatch("run_command", {"command": "ping", "target": "google.com & del *"})
        assert "not a valid host" in bad, f"bad host not rejected: {bad}"
        return "host arg validated"
    check("shell host validation", host_validation)

    def wrong_types_dont_crash():
        assert "Error" in registry.dispatch("run_command", {"command": ""})
        assert "Error" in registry.dispatch("run_command", {})
        registry.dispatch("run_command", {"command": 123})  # must not raise
        return "wrong-type args survived"
    check("shell wrong-type guards", wrong_types_dont_crash)


def t_find():
    """Exercises the find_files tool + its defenses against 8B hallucinations.
    Uses a temp tree inside the user's home, so no models are needed and it
    lives in the safe set."""
    import os
    import pathlib
    from jarvis.tools import find  # noqa: F401  (register)
    from jarvis.tools import registry

    # build an isolated sandbox INSIDE the home folder (find only searches home)
    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_find_smoke"
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)
    (sandbox / "budget_2026.xlsx").write_text("x", encoding="utf-8")
    (sandbox / "sub" / "my_cv.pdf").write_text("x", encoding="utf-8")
    # a pruned dir that must NOT be descended into
    (sandbox / "node_modules").mkdir(exist_ok=True)
    (sandbox / "node_modules" / "budget_junk.xlsx").write_text("x", encoding="utf-8")

    try:
        def happy_path():
            out = registry.dispatch("find_files", {"name": "budget", "folder": "jarvis_find_smoke"})
            assert "budget_2026.xlsx" in out, out
            # nested file found via recursion
            deep = registry.dispatch("find_files", {"name": "cv", "folder": "jarvis_find_smoke"})
            assert "my_cv.pdf" in deep, deep
            return "found top-level + nested files"
        check("find happy path", happy_path)

        def wildcard():
            out = registry.dispatch("find_files", {"name": "*.xlsx", "folder": "jarvis_find_smoke"})
            assert "budget_2026.xlsx" in out, out
            return "wildcard match ok"
        check("find wildcard", wildcard)

        def prunes_noise_dirs():
            # node_modules is pruned, so its budget_junk.xlsx must not appear
            out = registry.dispatch("find_files", {"name": "budget", "folder": "jarvis_find_smoke"})
            assert "budget_junk.xlsx" not in out, f"node_modules not pruned: {out}"
            return "noise dirs pruned"
        check("find prunes noise dirs", prunes_noise_dirs)

        def containment_guard():
            # searching outside the home folder must be refused, not run
            r = registry.dispatch("find_files", {"name": "config", "folder": "C:\\Windows"})
            assert "only search inside your own folders" in r, r
            return "escape outside home blocked"
        check("find containment guard", containment_guard)

        def hallucination_guards():
            assert "Error" in registry.dispatch("find_files", {"name": ""})
            assert "Error" in registry.dispatch("find_files", {})           # missing arg
            assert "too broad" in registry.dispatch("find_files", {"name": "*"})
            # wrong types / missing folder must not raise
            registry.dispatch("find_files", {"name": 123, "folder": "jarvis_find_smoke"})
            miss = registry.dispatch("find_files", {"name": "x", "folder": "jarvis_find_smoke/nope"})
            assert "does not exist" in miss, miss
            return "guards held"
        check("find hallucination guards", hallucination_guards)

        def no_match_is_friendly():
            out = registry.dispatch("find_files", {"name": "zzzznotathing", "folder": "jarvis_find_smoke"})
            assert "No files matching" in out, out
            return "no-match message ok"
        check("find no-match message", no_match_is_friendly)
    finally:
        import shutil
        shutil.rmtree(sandbox, ignore_errors=True)


def t_clipboard():
    """Exercises the clipboard tools + their defenses against 8B
    hallucinations. No model needed, so it lives in the safe set. The user's
    current clipboard text is saved and restored so the cycle is non-invasive."""
    from jarvis.tools import clipboard as clip  # noqa: F401  (register)
    from jarvis.tools import registry

    # save whatever the user currently has, to restore afterwards
    saved_text, _ = clip._read_clipboard_text()

    try:
        def round_trip():
            marker = "Jarvis clipboard smoke test 12345"
            out = registry.dispatch("set_clipboard", {"text": marker})
            assert "Copied" in out, out
            back = registry.dispatch("get_clipboard", {})
            assert marker in back, back
            return "set -> get round-trip ok"
        check("clipboard round-trip", round_trip)

        def hallucination_guards():
            # empty / missing / wrong-type text must not crash or store junk
            assert "Error" in registry.dispatch("set_clipboard", {"text": ""})
            assert "Error" in registry.dispatch("set_clipboard", {})
            # wrong type is coerced, not crashed
            assert "Copied" in registry.dispatch("set_clipboard", {"text": 42})
            assert "42" in registry.dispatch("get_clipboard", {})
            # oversized write is rejected, not dumped into memory
            big = registry.dispatch("set_clipboard", {"text": "x" * (clip.MAX_WRITE + 10)})
            assert "too much" in big, big
            return f"guards held (max_write={clip.MAX_WRITE})"
        check("clipboard hallucination guards", hallucination_guards)

        def read_is_bounded():
            # a huge clipboard is truncated on read, never returned unbounded
            registry.dispatch("set_clipboard", {"text": "y" * (clip.MAX_READ + 500)})
            out = registry.dispatch("get_clipboard", {})
            assert "truncated" in out, "large clipboard not truncated"
            assert len(out) < clip.MAX_READ + 200, "read not bounded"
            return "large read truncated"
        check("clipboard read bounded", read_is_bounded)
    finally:
        # restore the user's original clipboard text if we had it
        if saved_text:
            clip._write_clipboard_text(saved_text)


def t_tasks():
    """Exercises the to-do list tools + their defenses against 8B
    hallucinations. No model needed, so it lives in the safe set."""
    from jarvis.tools import tasks as tk
    from jarvis.tools import registry

    # isolate: use a temp store so we never touch the user's real to-do list
    import tempfile, os, pathlib
    tk._STORE = pathlib.Path(tempfile.gettempdir()) / "jarvis_tasks_smoke.json"
    for p in (tk._STORE, tk._STORE.with_name("tasks.corrupt.json")):
        if p.exists():
            os.remove(p)

    def happy_path():
        assert "Added" in registry.dispatch("add_task", {"task": "buy milk"})
        assert "Added" in registry.dispatch("add_task", {"task": "call the plumber"})
        assert tk.open_count() == 2
        out = registry.dispatch("list_tasks", {})
        assert "buy milk" in out and "call the plumber" in out, out
        # open tasks show up in the injected preamble
        assert "buy milk" in tk.tasks_preamble()
        return "add/list/preamble ok"
    check("tasks happy path", happy_path)

    def dedup():
        registry.dispatch("add_task", {"task": "buy milk"})
        return f"count still {tk.open_count()} (deduped)" if tk.open_count() == 2 \
            else (_ for _ in ()).throw(AssertionError("duplicate stored"))
    check("tasks dedup", dedup)

    def complete_flow():
        # by substring
        assert "Marked done" in registry.dispatch("complete_task", {"task": "milk"})
        assert tk.open_count() == 1
        # completed one no longer counts as open, shows under done
        done = registry.dispatch("list_tasks", {"which": "done"})
        assert "buy milk" in done and "[x]" in done, done
        # by number (1-based, against the open list)
        assert "Marked done" in registry.dispatch("complete_task", {"task": "1"})
        assert tk.open_count() == 0
        assert "all clear" in registry.dispatch("list_tasks", {})
        return "complete by text + number ok"
    check("tasks complete", complete_flow)

    def hallucination_guards():
        # empty / whitespace / wrong-type args must NOT crash or store junk
        assert "Error" in registry.dispatch("add_task", {"task": "   "})
        assert "Error" in registry.dispatch("add_task", {"task": ""})
        assert registry.dispatch("add_task", {}).startswith(("Error", "Added", "That is"))
        assert "Error" in registry.dispatch("complete_task", {"task": ""})
        assert "Error" in registry.dispatch("remove_task", {"task": ""})
        # wrong types must not raise
        registry.dispatch("add_task", {"task": 123})
        registry.dispatch("list_tasks", {"which": 5})
        # over-long task is truncated, not rejected or unbounded
        long = registry.dispatch("add_task", {"task": "x" * 5000})
        assert "shortened" in long, long
        # a bad number is a friendly message, not a crash
        assert "no task number" in registry.dispatch("complete_task", {"task": "999"})
        return f"guards held, open={tk.open_count()}"
    check("tasks hallucination guards", hallucination_guards)

    def remove_flow():
        # add a known removable task, then delete it by substring
        registry.dispatch("add_task", {"task": "return library book"})
        before = tk.open_count()
        assert "Removed" in registry.dispatch("remove_task", {"task": "library"})
        assert tk.open_count() == before - 1
        # a no-match delete is a friendly message, not a crash
        assert "Nothing" in registry.dispatch("remove_task", {"task": "zzzznope"})
        return "remove ok"
    check("tasks remove", remove_flow)

    def corrupt_store_recovers():
        tk._STORE.write_text("{ not valid json ", encoding="utf-8")
        # _load must not raise; corrupt file set aside, store treated as empty
        assert tk.open_count() == 0
        assert tk._STORE.with_name("tasks.corrupt.json").exists()
        return "corrupt store recovered"
    check("tasks corrupt-store recovery", corrupt_store_recovers)


def t_calc():
    """Exercises the calculate tool + its defenses against 8B hallucinations.
    No model needed, so it lives in the safe set."""
    from jarvis.tools import calc  # noqa: F401  (register)
    from jarvis.tools import registry

    def happy_path():
        assert registry.dispatch("calculate", {"expression": "2 + 2"}).endswith("4")
        assert registry.dispatch("calculate", {"expression": "(1250 * 1.2) / 3"}).endswith("500")
        assert registry.dispatch("calculate", {"expression": "3 ** 2"}).endswith("9")
        assert registry.dispatch("calculate", {"expression": "sqrt(144)"}).endswith("12")
        assert registry.dispatch("calculate", {"expression": "15/100 * 240"}).endswith("36")
        return "arithmetic + functions ok"
    check("calc happy path", happy_path)

    def constants_and_rounding():
        out = registry.dispatch("calculate", {"expression": "round(pi, 2)"})
        assert "3.14" in out, out
        # a whole-valued float renders as an int, not '12.0'
        assert registry.dispatch("calculate", {"expression": "10 / 2"}).endswith("5")
        return "constants + rounding ok"
    check("calc constants and formatting", constants_and_rounding)

    def rejects_code_execution():
        # hallucinated code-injection attempts must be refused, never run
        for evil in ("__import__('os').system('dir')", "open('x','w')",
                     "1 if True else 2", "[i for i in range(9)]",
                     "os.getcwd()", "eval('2+2')", "pi.__class__"):
            r = registry.dispatch("calculate", {"expression": evil})
            assert "Error" in r, f"{evil!r} not refused: {r}"
        return "code execution refused"
    check("calc rejects code", rejects_code_execution)

    def bounds_and_guards():
        # divide by zero -> friendly, not a crash
        assert "zero" in registry.dispatch("calculate", {"expression": "1/0"})
        # runaway power / factorial are capped, not hung
        assert "Error" in registry.dispatch("calculate", {"expression": "9 ** 9 ** 9"})
        assert "Error" in registry.dispatch("calculate", {"expression": "factorial(999999)"})
        # over-long expression is rejected, not evaluated
        assert "too long" in registry.dispatch("calculate", {"expression": "1+" * 400 + "1"})
        # empty / missing / wrong-type args must not crash
        assert "Error" in registry.dispatch("calculate", {"expression": ""})
        assert "Error" in registry.dispatch("calculate", {})
        registry.dispatch("calculate", {"expression": 123})  # coerced, no raise
        assert "Error" in registry.dispatch("calculate", {"expression": "2 +"})
        return "bounds + guards held"
    check("calc bounds and guards", bounds_and_guards)


def t_agent():
    from jarvis import config as c
    from jarvis.agent import Agent
    from jarvis.tools import apps, files, system, web, camera  # noqa: F401
    cfg = c.load()
    a = Agent(cfg["models"]["chat"])
    check("agent chat (no tools)", lambda: a.chat("Say exactly: systems online"))
    check("agent chat (tool: time)", lambda: a.chat("what time is it?"))


def t_camera():
    from jarvis import config as c
    from jarvis.vision.cameras import CameraManager
    cfg = c.load()
    m = CameraManager(cfg["cameras"], cfg["default_camera"])
    def grab():
        f = m.grab_frame()
        return f"frame {f.shape}"
    check("webcam frame grab", grab)


def t_vision():
    from jarvis import config as c
    from jarvis.vision.cameras import CameraManager
    from jarvis.vision.describe import describe_frame
    cfg = c.load()
    m = CameraManager(cfg["cameras"], cfg["default_camera"])
    check("vision describe", lambda: describe_frame(
        m.grab_frame(), cfg["models"]["vision"], unload=cfg["models"]["chat"]))


def t_tts():
    import time
    from jarvis.voice.tts import Speaker
    def speak():
        s = Speaker()
        s.say("Systems online, sir.")
        time.sleep(4)
        s.stop()
        return f"speaker ok={s.ok}"
    check("tts speak", speak)


def t_hud():
    import time
    from jarvis import config as c
    from jarvis.voice.hud import create
    cfg = c.load()
    def demo():
        h = create(cfg)
        for st in ("idle", "listening", "thinking", "speaking"):
            h.state(st)
            for i in range(12):
                h.level((i % 10) / 10.0)
                time.sleep(0.05)
        ok = getattr(h, "ok", False)
        h.shutdown()
        time.sleep(0.3)
        return f"hud drew window ok={ok}"
    check("hud orb cycle", demo)


def t_watch():
    from jarvis import config as c
    from jarvis.vision.cameras import CameraManager
    cfg = c.load()
    m = CameraManager(cfg["cameras"], cfg["default_camera"])
    def yolo():
        from ultralytics import YOLO
        frame = m.grab_frame()
        results = YOLO("yolov8n.pt").predict(frame, classes=[0], conf=0.5, verbose=False)
        return f"persons detected: {sum(len(r.boxes) for r in results)}"
    check("yolo person detection", yolo)


def t_e2e():
    import os
    from jarvis import config as c
    from jarvis.agent import Agent
    from jarvis.tools import apps, files, system, web  # noqa: F401
    from jarvis.tools import camera
    cfg = c.load()
    camera.init(cfg, None)
    a = Agent(cfg["models"]["chat"])
    target = os.path.join(os.path.expanduser("~"), "Desktop", "jarvis_test_note.txt")
    if os.path.exists(target):
        os.remove(target)
    check("e2e write file", lambda: a.chat(
        "make a file on my desktop called jarvis_test_note.txt containing a "
        "two line hello note"))
    check("e2e file exists", lambda: f"exists={os.path.exists(target)}" if os.path.exists(target)
          else (_ for _ in ()).throw(AssertionError(f"{target} missing")))
    check("e2e start working", lambda: a.chat("start working"))
    import time; time.sleep(3)
    check("e2e stop working", lambda: a.chat("stop working"))
    camera.shutdown()


SECTIONS = {"imports": t_imports, "tools": t_tools, "memory": t_memory,
            "shell": t_shell, "find": t_find, "clipboard": t_clipboard,
            "tasks": t_tasks, "calc": t_calc, "agent": t_agent,
            "camera": t_camera, "vision": t_vision, "tts": t_tts,
            "hud": t_hud, "watch": t_watch, "e2e": t_e2e}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "safe"
    if which == "all":
        for fn in SECTIONS.values():
            fn()
    elif which == "safe":
        t_imports(); t_tools(); t_memory(); t_shell(); t_find(); t_clipboard()
        t_tasks(); t_calc()
    else:
        SECTIONS[which]()
    print("\nFAILURES:", failures if failures else "none")
    sys.exit(1 if failures else 0)
