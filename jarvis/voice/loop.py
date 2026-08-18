"""Voice loop thread: wake word -> listen -> agent -> speak, with barge-in
and hands-free follow-up.

Beyond the basic cycle, this loop adds two things that make Jarvis feel like a
real conversation:

- **Barge-in.** While Jarvis is speaking you can cut in by saying "Hey Jarvis".
  He stops talking instantly and listens, so you never have to wait out a long
  reply. (We listen for the wake word specifically -- not just any sound --
  because on a laptop the mic also hears Jarvis's own voice; the wake word is
  what reliably distinguishes "the user wants in" from "Jarvis talking".)

- **Follow-up.** When Jarvis asks YOU a question, he keeps the mic open for a
  few seconds so you can just answer -- no "Hey Jarvis" needed. If you stay
  quiet, he drops back to waiting for the wake word.

Both are configurable under ``voice`` in config.yaml (``barge_in``,
``follow_up``, ``follow_up_seconds``).
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

        self.barge_in = bool(vcfg.get("barge_in", True))
        self.follow_up = str(vcfg.get("follow_up", "question")).lower()  # question|always|off
        self.follow_up_s = float(vcfg.get("follow_up_seconds", 9))
        # a stricter bar while Jarvis is talking, so his own voice can't self-trigger
        self._barge_threshold = max(0.6, self.wake.threshold + 0.2)

    def _wait_speech(self):
        """Block until the speaker is done, keeping the orb on 'speaking'."""
        time.sleep(0.05)
        while self.speaker.speaking.is_set():
            self.hud.state("speaking")
            time.sleep(0.1)

    def _speak_interruptible(self, text: str) -> bool:
        """Speak ``text``. If barge-in is on, listen for the wake word the whole
        time; if it's heard, stop speaking at once and return True (the user is
        cutting in). Return False if the reply finished on its own."""
        self.hud.state("speaking")
        self.speaker.say(text)
        if not self.barge_in:
            self._wait_speech()
            return False
        interrupted = self.wake.wait_for_wake(
            should_stop=lambda: not self.speaker.speaking.is_set(),
            on_level=self.hud.level,
            threshold=self._barge_threshold,
        )
        if interrupted:
            self.speaker.shutup()
            return True
        self._wait_speech()
        return False

    def _wants_follow_up(self, reply: str) -> bool:
        if self.follow_up == "off":
            return False
        if self.follow_up == "always":
            return True
        return reply.strip().endswith("?")  # "question": only after he asks one

    def run(self):
        self.hud.state("idle")
        while True:
            try:
                if not self.wake.wait_for_wake(on_level=self.hud.level):
                    return
                # flip to green the instant we hear the wake word
                self.hud.state("listening")
                self.speaker.shutup()  # kill any lingering speech
                print("\n  [wake] Yes, sir?")
                self.speaker.say("Yes, sir?")
                self._wait_speech()
                self._converse(onset_timeout=5.0)
                self.hud.state("idle")
            except Exception as e:
                print(f"  [voice error] {e} — voice loop restarting in 5s")
                self.hud.state("idle")
                time.sleep(5)

    def _converse(self, onset_timeout: float):
        """One or more exchanges without needing the wake word again: after a
        barge-in, or after Jarvis asks a follow-up question, we come straight
        back here to listen."""
        while True:
            self.hud.state("listening")
            text = self.stt.listen(on_level=self.hud.level, onset_timeout=onset_timeout)
            if not text:
                return  # silence -> back to waiting for the wake word
            print(f"you (voice)> {text}")
            self.hud.state("thinking")
            reply = self.agent.chat(text, status=lambda s: print(f"  {s}", flush=True))
            print(f"jarvis> {reply}\nyou> ", end="", flush=True)

            interrupted = self._speak_interruptible(reply)
            if interrupted:
                # the user cut in: listen again immediately, no wake word
                onset_timeout = 5.0
                continue
            if self._wants_follow_up(reply):
                # he asked something: keep the mic open a bit longer for the answer
                onset_timeout = self.follow_up_s
                continue
            return
