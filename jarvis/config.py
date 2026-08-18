import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.path.expanduser("~"))
DESKTOP = HOME / "Desktop"

DEFAULTS = {
    "models": {"chat": "qwen3:8b", "vision": "qwen2.5vl:3b"},
    "cameras": {"webcam": 0},
    "default_camera": "webcam",
    "watch": {
        "alert_cooldown_seconds": 30,
        "snapshot_dir": "data/snapshots",
        "person_confidence": 0.5,
    },
    "voice": {
        "enabled": True,
        "wake_word": "hey_jarvis_v0.1",
        "wake_threshold": 0.4,
        "stt_model": "small",
        "stt_language": "en",
        "engine": "auto",                  # auto | piper | sapi
        # refined RP British male (the film-JARVIS accent). en_GB-alan-medium is
        # the warmer alternative — both are in models/piper/voices.
        "piper_voice": "en_GB-northern_english_male-medium",
        # --- delivery & tone (Piper only): the "calm, cinematic JARVIS" feel ---
        "piper_length_scale": 1.15,        # >1 = slower, more measured
        "piper_noise_scale": 0.5,          # lower = steadier/composed (default 0.667)
        "piper_noise_w": 0.7,              # phoneme-timing variability
        "piper_sentence_pause": 0.45,      # seconds of silence between sentences
        "warmth": True,                    # warm EQ + a touch of room reverb
        "warmth_reverb": 0.18,             # 0 = dry; wet mix of the subtle reverb
        "barge_in": True,                  # interrupt speech by saying "Hey Jarvis"
        "follow_up": "question",           # question | always | off
        "follow_up_seconds": 9,
    },
    "hud": {"enabled": True, "corner": "bottom-right"},
    "apps": {},
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    path = PROJECT_ROOT / "config.yaml"
    data = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, data)
    snap = PROJECT_ROOT / cfg["watch"]["snapshot_dir"]
    snap.mkdir(parents=True, exist_ok=True)
    cfg["watch"]["snapshot_dir"] = str(snap)
    return cfg
