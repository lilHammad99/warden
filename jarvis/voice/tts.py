"""Text-to-speech on a dedicated thread (pyttsx3/SAPI5 is not thread-safe,
so all speaking goes through one queue + one engine)."""

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
            import pyttsx3
        except Exception:
            self.ok = False
            return
        while True:
            text = self.q.get()
            if text is None:
                break
            try:
                engine = pyttsx3.init()  # fresh engine per utterance: avoids SAPI5 stalls
                engine.setProperty("rate", 178)
                self.speaking.set()
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception:
                self.ok = False
            finally:
                self.speaking.clear()

    def say(self, text: str):
        if self.ok and text:
            self.q.put(text)

    def stop(self):
        self.q.put(None)
