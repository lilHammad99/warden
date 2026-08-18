"""Let Jarvis shut himself down on command.

This closes the Jarvis program itself -- it does NOT turn off or restart the
PC. The tool only raises a shutdown flag; a watcher thread in app.main lets the
farewell finish speaking, then tears everything down and exits cleanly.
"""

from .. import control
from .registry import tool


@tool(
    "shutdown_jarvis",
    "Shut yourself (Jarvis) down and close the program. Use ONLY when the user "
    "clearly asks you to shut down, power off, turn yourself off, go to sleep, "
    "stand down, sign off, dismiss you, rest, close, quit, or says that's all "
    "for now. This closes Jarvis, not the PC -- it does not shut down or "
    "restart Windows. Before calling it, give a short spoken goodbye like "
    "'Powering down. Goodbye, sir.'",
    {"type": "object", "properties": {}, "required": []},
)
def shutdown_jarvis() -> str:
    control.request_shutdown()
    return "Powering down. Goodbye, sir."
