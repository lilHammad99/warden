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
        from jarvis.tools import apps, browser, camera, files, registry, system, web  # noqa
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
    check("vision describe", lambda: describe_frame(m.grab_frame(), cfg["models"]["vision"]))


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


SECTIONS = {"imports": t_imports, "tools": t_tools, "agent": t_agent,
            "camera": t_camera, "vision": t_vision, "tts": t_tts}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "safe"
    if which == "all":
        for fn in SECTIONS.values():
            fn()
    elif which == "safe":
        t_imports(); t_tools()
    else:
        SECTIONS[which]()
    print("\nFAILURES:", failures if failures else "none")
    sys.exit(1 if failures else 0)
