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

    def wait_for_wake(self, should_stop=lambda: False, on_level=None,
                      threshold=None) -> bool:
        """Block until the wake word is heard. Returns False if stopped.

        on_level(0..1), if given, is called each chunk with the current mic
        loudness so a UI can show that the mic is picking up sound.

        threshold overrides the default detection threshold for this call --
        used for barge-in, where Jarvis's own voice is in the mic and we want a
        stricter bar so his speech can't accidentally trigger the wake word.
        """
        thr = self.threshold if threshold is None else threshold
        self.model.reset()
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=CHUNK) as stream:
            while not should_stop():
                data, _ = stream.read(CHUNK)
                samples = np.frombuffer(data.tobytes(), dtype=np.int16)
                if on_level is not None:
                    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                    on_level(min(1.0, rms / 4000.0))
                scores = self.model.predict(samples)
                if any(v >= thr for v in scores.values()):
                    return True
        return False
