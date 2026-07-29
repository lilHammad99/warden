import ctypes
import datetime
import platform
from pathlib import Path

import psutil

from ..config import DESKTOP
from .registry import tool


@tool(
    "get_time",
    "Get the current date and time on this PC.",
)
def get_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("It is %A, %B %d %Y, %I:%M %p.")


@tool(
    "system_info",
    "Get PC status: battery, CPU load, RAM usage, disk space.",
)
def system_info() -> str:
    parts = [f"OS: {platform.system()} {platform.release()}"]
    batt = psutil.sensors_battery()
    if batt:
        state = "charging" if batt.power_plugged else "on battery"
        parts.append(f"Battery: {batt.percent}% ({state})")
    parts.append(f"CPU: {psutil.cpu_percent(interval=0.5)}%")
    ram = psutil.virtual_memory()
    parts.append(f"RAM: {ram.percent}% used ({ram.used // (1024**3)}/{ram.total // (1024**3)} GB)")
    disk = psutil.disk_usage("C:\\")
    parts.append(f"Disk C: {disk.percent}% used ({disk.free // (1024**3)} GB free)")
    return "\n".join(parts)


@tool(
    "take_screenshot",
    "Take a screenshot of the screen and save it as a PNG on the Desktop.",
)
def take_screenshot() -> str:
    import mss
    import mss.tools

    name = datetime.datetime.now().strftime("screenshot_%Y%m%d_%H%M%S.png")
    path = Path(DESKTOP) / name
    with mss.mss() as sct:
        img = sct.grab(sct.monitors[1])
        mss.tools.to_png(img.rgb, img.size, output=str(path))
    return f"Screenshot saved to {path}"


def _volume_endpoint():
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


@tool(
    "set_volume",
    "Set the speaker volume to a percentage from 0 to 100, or mute/unmute.",
    {
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume 0-100"},
            "mute": {"type": "boolean", "description": "true to mute, false to unmute"},
        },
        "required": [],
    },
)
def set_volume(level: int | None = None, mute: bool | None = None) -> str:
    vol = _volume_endpoint()
    if mute is not None:
        vol.SetMute(1 if mute else 0, None)
        return "Muted." if mute else "Unmuted."
    if level is not None:
        level = max(0, min(100, int(level)))
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Volume set to {level}%."
    cur = round(vol.GetMasterVolumeLevelScalar() * 100)
    return f"Volume is at {cur}%."


@tool(
    "lock_pc",
    "Lock the Windows session (lock screen). Only when the user clearly asks.",
)
def lock_pc() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "PC locked."
