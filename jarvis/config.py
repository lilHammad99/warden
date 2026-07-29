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
        "stt_model": "small",
        "stt_language": "en",
    },
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
