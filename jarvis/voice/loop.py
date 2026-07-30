"""Voice loop thread: wake word -> listen -> agent -> speak.

Drives the HUD orb through its states (idle -> listening -> thinking ->
speaking) and feeds it the live mic level so the user can see it hearing.
"""

import threading
import time


class VoiceLoop(threading.Thread):
    def __init__(self, cfg: dict, agent, speaker, hud=None):
        super().__init__(daemon=True, name="voice")
        from .hud import _NullHud
        from .stt import Transcriber
        from .wake import WakeListener

        vcfg = cfg["voice"]
        self.wake = WakeListener(vcfg["wake_word"], vcfg.get("wake_threshold", 0.5))
        self.stt = Transcriber(vcfg["stt_model"], vcfg["stt_language"])
        self.agent = agent
        self.speaker = speaker
        self.hud = hud or _NullHud()

    def _wait_speech(self):
        """Block until the speaker is done, keeping the orb on 'speaking'."""
        time.sleep(0.05)
        while self.speaker.speaking.is_set():
            self.hud.state("speaking")
            time.sleep(0.1)

    def run(self):
        self.hud.state("idle")
        while True:
            try:
                if not self.wake.wait_for_wake(on_level=self.hud.level):
                    return
                # flip to green the instant we hear the wake word
                self.hud.state("listening")
                self._wait_speech()  # let any current speech finish first
                print("\n  [wake] Yes, sir?")
                self.speaker.say("Yes, sir?")
                self._wait_speech()
                self.hud.state("listening")
                text = self.stt.listen(on_level=self.hud.level)
                if not text:
                    self.hud.state("idle")
                    continue
                print(f"you (voice)> {text}")
                self.hud.state("thinking")
                reply = self.agent.chat(text, status=lambda s: print(f"  {s}", flush=True))
                print(f"jarvis> {reply}\nyou> ", end="", flush=True)
                self.hud.state("speaking")
                self.speaker.say(reply)
                self._wait_speech()
                self.hud.state("idle")
            except Exception as e:
                print(f"  [voice error] {e} — voice loop restarting in 5s")
                self.hud.state("idle")
                time.sleep(5)
