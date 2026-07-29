"""Voice loop thread: wake word -> listen -> agent -> speak."""

import threading
import time


class VoiceLoop(threading.Thread):
    def __init__(self, cfg: dict, agent, speaker):
        super().__init__(daemon=True, name="voice")
        from .stt import Transcriber
        from .wake import WakeListener

        vcfg = cfg["voice"]
        self.wake = WakeListener(vcfg["wake_word"])
        self.stt = Transcriber(vcfg["stt_model"], vcfg["stt_language"])
        self.agent = agent
        self.speaker = speaker

    def run(self):
        while True:
            try:
                if not self.wake.wait_for_wake():
                    return
                # don't listen to Jarvis's own voice
                while self.speaker.speaking.is_set():
                    time.sleep(0.1)
                print("\n  [wake] Yes, sir?")
                self.speaker.say("Yes, sir?")
                while self.speaker.speaking.is_set():
                    time.sleep(0.1)
                text = self.stt.listen()
                if not text:
                    continue
                print(f"you (voice)> {text}")
                reply = self.agent.chat(text, status=lambda s: print(f"  {s}", flush=True))
                print(f"jarvis> {reply}\nyou> ", end="", flush=True)
                self.speaker.say(reply)
            except Exception as e:
                print(f"  [voice error] {e} — voice loop restarting in 5s")
                time.sleep(5)
