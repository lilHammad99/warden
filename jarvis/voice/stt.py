"""Record from the mic until silence, transcribe locally with faster-whisper."""

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
FRAME_MS = 30
SILENCE_AFTER_S = 1.2
MAX_UTTERANCE_S = 15
ENERGY_THRESHOLD = 0.01  # RMS on float32 [-1, 1]


class Transcriber:
    def __init__(self, model_size: str = "small", language: str = "en"):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.language = language

    def record_utterance(self, on_level=None) -> np.ndarray | None:
        frame_len = int(SAMPLE_RATE * FRAME_MS / 1000)
        chunks, started, silent_s, total_s = [], False, 0.0, 0.0
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=frame_len) as stream:
            while total_s < MAX_UTTERANCE_S:
                data, _ = stream.read(frame_len)
                mono = data[:, 0]
                chunks.append(mono)
                total_s += FRAME_MS / 1000
                rms = float(np.sqrt(np.mean(mono**2)))
                if on_level is not None:
                    on_level(min(1.0, rms / 0.12))
                if rms > ENERGY_THRESHOLD:
                    started = True
                    silent_s = 0.0
                elif started:
                    silent_s += FRAME_MS / 1000
                    if silent_s > SILENCE_AFTER_S:
                        break
                elif total_s > 5.0:  # nobody spoke
                    return None
        return np.concatenate(chunks) if started else None

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio, language=self.language, beam_size=1, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def listen(self, on_level=None) -> str:
        audio = self.record_utterance(on_level=on_level)
        if audio is None:
            return ""
        return self.transcribe(audio)
