"""Smoke tests: run with  .venv\\Scripts\\python -m tests.smoke [section]
Sections: imports, tools, agent, camera, vision, tts, all (default: safe set)
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
        from jarvis.tools import apps, browser, camera, files, memory, registry, system, web  # noqa
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
            "agent": t_agent, "camera": t_camera, "vision": t_vision,
            "tts": t_tts, "hud": t_hud, "watch": t_watch, "e2e": t_e2e}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "safe"
    if which == "all":
        for fn in SECTIONS.values():
            fn()
    elif which == "safe":
        t_imports(); t_tools(); t_memory()
    else:
        SECTIONS[which]()
    print("\nFAILURES:", failures if failures else "none")
    sys.exit(1 if failures else 0)
