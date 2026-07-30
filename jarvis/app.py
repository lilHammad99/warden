import datetime
import sys

from . import config as config_mod
from .agent import Agent


def _greeting() -> str:
    """A short, time-of-day greeting for the console (pure ASCII)."""
    h = datetime.datetime.now().hour
    part = ("morning" if 5 <= h < 12 else
            "afternoon" if 12 <= h < 18 else
            "evening" if 18 <= h < 22 else "night")
    return f"Good {part}, sir. Jarvis is online and ready."

BANNER = r"""
      _   _    ______     _____ ____
     | | / \  |  _ \ \   / /_ _/ ___|
  _  | |/ _ \ | |_) \ \ / / | |\___ \
 | |_| / ___ \|  _ < \ V /  | | ___) |
  \___/_/   \_\_| \_\ \_/  |___|____/
        local - private - yours
"""


def main():
    cfg = config_mod.load()

    # importing tool modules registers their tools
    from .tools import apps, files, system, web  # noqa: F401
    from .tools import camera  # noqa: F401
    from .tools import clipboard  # noqa: F401
    from .tools import find  # noqa: F401
    from .tools import memory as memory_store  # noqa: F401
    from .tools import shell  # noqa: F401
    from .tools import registry
    try:
        from .tools import browser  # noqa: F401
        browser_ok = True
    except Exception as e:
        browser_ok = False
        print(f"(browser tools unavailable: {e})")

    apps.set_extra_apps(cfg.get("apps") or {})

    from .voice.tts import Speaker
    speaker = Speaker()
    camera.init(cfg, speaker)

    from .voice.hud import create as create_hud
    hud = create_hud(cfg)

    agent = Agent(cfg["models"]["chat"])

    voice_status = "off"
    if cfg["voice"]["enabled"]:
        try:
            from .voice.loop import VoiceLoop

            VoiceLoop(cfg, agent, speaker, hud).start()
            voice_status = "on — say 'Hey Jarvis'"
        except Exception as e:
            voice_status = f"unavailable ({e})"

    resting = "idle" if cfg["voice"]["enabled"] else "off"
    hud.state(resting)

    n_mem = memory_store.count()
    mem_status = f"{n_mem} fact{'s' if n_mem != 1 else ''} remembered" if n_mem else "empty"
    print(BANNER)
    print(f"model: {cfg['models']['chat']} | vision: {cfg['models']['vision']}"
          f" | voice: {voice_status} | browser tools: {'on' if browser_ok else 'off'}")
    print(f"memory: {mem_status}  ({len(registry.specs())} tools online)")
    print(_greeting())
    print("Type your command ('exit' to quit). Try: start working / find my "
          "resume / read my clipboard / what do you see\n")

    while True:
        try:
            text = input("you> ").strip().lstrip("﻿").strip()
        except (EOFError, KeyboardInterrupt):
            text = "exit"
        if not text:
            continue
        if text.lower() in ("exit", "quit", "bye"):
            print("jarvis> Goodbye, sir.")
            speaker.say("Goodbye, sir.")
            speaker.stop()
            hud.shutdown()
            camera.shutdown()
            if browser_ok:
                from .tools import browser as b
                b.shutdown()
            sys.exit(0)
        hud.state("thinking")
        import time as _time
        _t0 = _time.monotonic()
        reply = agent.chat(text, status=lambda s: print(f"  {s}", flush=True))
        _dt = _time.monotonic() - _t0
        print(f"jarvis> {reply}")
        print(f"  (answered in {_dt:.1f}s)\n")
        hud.state("speaking")
        speaker.say(reply)
        hud.state(resting)


if __name__ == "__main__":
    main()
