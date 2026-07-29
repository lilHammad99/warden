import sys

from . import config as config_mod
from .agent import Agent

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

    agent = Agent(cfg["models"]["chat"])

    voice_status = "off"
    if cfg["voice"]["enabled"]:
        try:
            from .voice.loop import VoiceLoop

            VoiceLoop(cfg, agent, speaker).start()
            voice_status = "on — say 'Hey Jarvis'"
        except Exception as e:
            voice_status = f"unavailable ({e})"

    print(BANNER)
    print(f"model: {cfg['models']['chat']} | vision: {cfg['models']['vision']}"
          f" | voice: {voice_status} | browser tools: {'on' if browser_ok else 'off'}")
    print("Type your command ('exit' to quit). Try: start working / what do you see\n")

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
            camera.shutdown()
            if browser_ok:
                from .tools import browser as b
                b.shutdown()
            sys.exit(0)
        reply = agent.chat(text, status=lambda s: print(f"  {s}", flush=True))
        print(f"jarvis> {reply}\n")
        speaker.say(reply)


if __name__ == "__main__":
    main()
