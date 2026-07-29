"""Wake-word detection ("Hey Jarvis") using openWakeWord (ONNX, local)."""

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHUNK = 1280  # 80 ms, what openWakeWord expects


class WakeListener:
    def __init__(self, wake_word: str = "hey_jarvis_v0.1", threshold: float = 0.5):
        from openwakeword.model import Model

        self.model = Model(
            wakeword_models=[wake_word], inference_framework="onnx"
        )
        self.threshold = threshold

    def wait_for_wake(self, should_stop=lambda: False) -> bool:
        """Block until the wake word is heard. Returns False if stopped."""
        self.model.reset()
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=CHUNK) as stream:
            while not should_stop():
                data, _ = stream.read(CHUNK)
                scores = self.model.predict(np.frombuffer(data.tobytes(), dtype=np.int16))
                if any(v >= self.threshold for v in scores.values()):
                    return True
        return False
