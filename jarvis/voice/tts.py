"""Text-to-speech on a dedicated thread.

Speaks through Windows SAPI5 directly (``SAPI.SpVoice`` via comtypes). We used
to create a fresh ``pyttsx3`` engine per utterance to dodge SAPI stalls, but
``pyttsx3.init()`` actually returns a CACHED singleton engine that only speaks
its FIRST utterance and then goes silent -- so Jarvis would say one thing after
launch and never speak again. One persistent SpVoice on this thread speaks
every time.
"""

import queue
import threading


class Speaker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="tts")
        self.q: queue.Queue = queue.Queue()
        self.speaking = threading.Event()
        self.ok = True
        self.start()

    def run(self):
        try:
            import comtypes
            comtypes.CoInitialize()  # SAPI is COM; this thread must init it
            from comtypes.client import CreateObject

            voice = CreateObject("SAPI.SpVoice")
            voice.Rate = 1  # -10..10; slightly quicker than the default drawl
        except Exception:
            self.ok = False
            return
        while True:
            text = self.q.get()
            if text is None:
                break
            try:
                self.speaking.set()
                voice.Speak(text)  # blocking: returns when the utterance ends
            except Exception:
                self.ok = False
            finally:
                self.speaking.clear()

    def say(self, text: str):
        if self.ok and text:
            self.q.put(text)

    def stop(self):
        self.q.put(None)
