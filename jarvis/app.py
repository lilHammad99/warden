import datetime
import sys
import threading

from . import config as config_mod
from .agent import Agent


def _greeting() -> str:
    """A short, time-of-day greeting with today's date (pure ASCII)."""
    now = datetime.datetime.now()
    h = now.hour
    part = ("morning" if 5 <= h < 12 else
            "afternoon" if 12 <= h < 18 else
            "evening" if 18 <= h < 22 else "night")
    stamp = now.strftime("%A, %d %B %Y").replace(" 0", " ")
    clock = now.strftime("%I:%M %p").lstrip("0")
    return (f"Good {part}, sir. Jarvis is online and ready.\n"
            f"It is {clock} on {stamp}.")

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
    from .tools import archive  # noqa: F401
    from .tools import calc  # noqa: F401
    from .tools import camera  # noqa: F401
    from .tools import clipboard  # noqa: F401
    from .tools import convert  # noqa: F401
    from .tools import dates  # noqa: F401
    from .tools import disk  # noqa: F401
    from .tools import document  # noqa: F401
    from .tools import explorer  # noqa: F401
    from .tools import extract  # noqa: F401
    from .tools import find  # noqa: F401
    from .tools import memory as memory_store  # noqa: F401
    from .tools import organize  # noqa: F401
    from .tools import recent  # noqa: F401
    from .tools import recycle  # noqa: F401
    from .tools import reminders as reminder_store  # noqa: F401
    from .tools import search  # noqa: F401
    from .tools import shell  # noqa: F401
    from .tools import tasks as task_list  # noqa: F401
    from .tools import textstats  # noqa: F401
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

    # background reminder poller: fires due reminders on its own, so Jarvis can
    # speak up later without being asked again. Daemon thread; never crashes.
    stop_reminders = threading.Event()

    def _reminder_watch():
        while not stop_reminders.is_set():
            try:
                for text in reminder_store.due_reminders():
                    line = f"Reminder, sir: {text}"
                    print(f"\njarvis> {line}\nyou> ", end="", flush=True)
                    hud.state("speaking")
                    speaker.say(line)
                    hud.state(resting)
            except Exception:
                pass
            stop_reminders.wait(15)  # check about every 15 seconds

    threading.Thread(target=_reminder_watch, daemon=True).start()

    n_mem = memory_store.count()
    mem_status = f"{n_mem} fact{'s' if n_mem != 1 else ''} remembered" if n_mem else "empty"
    n_todo = task_list.open_count()
    todo_status = f"{n_todo} open task{'s' if n_todo != 1 else ''}" if n_todo else "clear"
    n_rem = reminder_store.pending_count()
    if n_rem:
        nxt = reminder_store.next_due_phrase()
        rem_status = f"{n_rem} pending" + (f" ({nxt})" if nxt else "")
    else:
        rem_status = "none"
    print(BANNER)
    rule = "-" * 64
    print(rule)
    print(f"model: {cfg['models']['chat']} | vision: {cfg['models']['vision']}"
          f" | voice: {voice_status} | browser tools: {'on' if browser_ok else 'off'}")
    print(f"memory: {mem_status} | to-do: {todo_status} | reminders: {rem_status}"
          f"  ({len(registry.specs())} tools online)")
    print(rule)
    print(_greeting())
    if n_todo:
        print(f"Reminder: you have {n_todo} thing{'s' if n_todo != 1 else ''} "
              "on your to-do list. Say 'what's on my list' to hear it.")
    print("Type your command ('exit' to quit). Try: what is 15% of 240 / "
          "convert 5 miles to km / remind me in 10 minutes to stretch / "
          "how many days until christmas / add milk to my to-do list / "
          "how many words is my essay.txt / "
          "find my resume / read my resume.docx / "
          "which file mentions the wifi password / "
          "what did I work on today / rename that file to notes_final.txt / "
          "make a folder called taxes in documents / "
          "move my taxes folder into documents / "
          "copy my taxes folder into backups / "
          "how big is my downloads folder / "
          "open my downloads folder / "
          "back up my documents into a zip / unzip my backup / "
          "delete that old draft to the recycle bin / "
          "actually my wifi password changed to hunter2\n")

    while True:
        try:
            text = input("you> ").strip().lstrip("﻿").strip()
        except (EOFError, KeyboardInterrupt):
            text = "exit"
        if not text:
            continue
        if text.lower() in ("exit", "quit", "bye"):
            print("jarvis> Goodbye, sir.")
            stop_reminders.set()
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
        used = ", ".join(dict.fromkeys(agent.last_tools))  # de-dup, keep order
        tail = f" using {used}" if used else ""
        print(f"  (answered in {_dt:.1f}s{tail})\n")
        hud.state("speaking")
        speaker.say(reply)
        hud.state(resting)


if __name__ == "__main__":
    main()
