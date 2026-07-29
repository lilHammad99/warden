"""Camera tools exposed to the agent. `init()` wires config + speaker."""

from ..vision.cameras import CameraManager
from ..vision.watcher import Watcher
from .registry import tool

_state: dict = {"manager": None, "watchers": {}, "speaker": None, "cfg": None}


def init(cfg: dict, speaker):
    _state["cfg"] = cfg
    _state["speaker"] = speaker
    _state["manager"] = CameraManager(cfg["cameras"], cfg["default_camera"])


def shutdown():
    for w in _state["watchers"].values():
        w.stop()
    _state["watchers"] = {}


def _alert(text, frame):
    print(f"\njarvis> {text}")
    if _state["speaker"]:
        _state["speaker"].say(text)


@tool(
    "start_working",
    "Start watch mode: continuously monitor a camera and alert the user "
    "when a person appears. Use when the user says 'start working', 'watch "
    "the camera', 'guard the room', etc.",
    {
        "type": "object",
        "properties": {"camera": {"type": "string", "description": "Camera name, default if omitted"}},
        "required": [],
    },
)
def start_working(camera: str | None = None) -> str:
    m = _state["manager"]
    cam = m.resolve(camera)
    if cam in _state["watchers"] and _state["watchers"][cam].is_alive():
        return f"Watch mode is already running on {cam}."
    w = Watcher(m, cam, _state["cfg"]["watch"], _alert)
    w.start()
    _state["watchers"][cam] = w
    return (f"Watch mode started on camera '{cam}'. I will alert you when I "
            f"see someone, and save snapshots.")


@tool(
    "stop_working",
    "Stop watch mode / camera monitoring. Use when the user says 'stop "
    "working' or 'stop watching'.",
    {
        "type": "object",
        "properties": {"camera": {"type": "string", "description": "Camera name, all if omitted"}},
        "required": [],
    },
)
def stop_working(camera: str | None = None) -> str:
    watchers = _state["watchers"]
    if not watchers:
        return "Watch mode was not running."
    if camera:
        cam = _state["manager"].resolve(camera)
        w = watchers.pop(cam, None)
        if w:
            w.stop()
            return f"Stopped watching {cam}."
        return f"{cam} was not being watched."
    for w in watchers.values():
        w.stop()
    watchers.clear()
    return "Watch mode stopped on all cameras."


@tool(
    "describe_view",
    "Look through a camera right now and describe what is visible. Use for "
    "'what do you see', 'look at the camera', 'check the front door cam'. "
    "Pass the user's specific question if they asked one.",
    {
        "type": "object",
        "properties": {
            "camera": {"type": "string", "description": "Camera name, default if omitted"},
            "question": {"type": "string", "description": "Specific question about the view"},
        },
        "required": [],
    },
)
def describe_view(camera: str | None = None, question: str | None = None) -> str:
    from ..vision.describe import describe_frame

    frame = _state["manager"].grab_frame(camera)
    return describe_frame(frame, _state["cfg"]["models"]["vision"], question)


@tool(
    "list_cameras",
    "List the cameras Jarvis can use, and which are being watched.",
)
def list_cameras() -> str:
    m = _state["manager"]
    lines = []
    for name in m.names():
        watching = name in _state["watchers"] and _state["watchers"][name].is_alive()
        default = " (default)" if name == m.default else ""
        lines.append(f"- {name}{default}{' — watching' if watching else ''}")
    lines.append("Add IP cameras in config.yaml under 'cameras' with their RTSP URL.")
    return "\n".join(lines)
