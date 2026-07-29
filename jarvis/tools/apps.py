import subprocess
import webbrowser

from .registry import tool

BUILTIN_APPS = {
    "chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "notepad": "notepad",
    "calculator": "calc",
    "explorer": "explorer",
    "file explorer": "explorer",
    "settings": "start ms-settings:",
    "task manager": "taskmgr",
    "paint": "mspaint",
    "word": "start winword",
    "excel": "start excel",
    "powerpoint": "start powerpnt",
    "spotify": "start spotify:",
    "vlc": "vlc",
    "cmd": "start cmd",
    "terminal": "start wt",
    "vs code": "code",
    "vscode": "code",
}

WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "whatsapp": "https://web.whatsapp.com",
    "netflix": "https://www.netflix.com",
    "github": "https://github.com",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
}

_extra_apps: dict = {}


def set_extra_apps(apps: dict):
    _extra_apps.update({k.lower(): v for k, v in (apps or {}).items()})


@tool(
    "open_app",
    "Open a program on the PC by name (e.g. chrome, notepad, calculator, "
    "spotify, word) or by full path to an .exe.",
    {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "App name or exe path"}},
        "required": ["name"],
    },
)
def open_app(name: str) -> str:
    key = name.strip().lower()
    cmd = _extra_apps.get(key) or BUILTIN_APPS.get(key) or name
    try:
        subprocess.Popen(cmd if cmd.startswith("start ") else f"start \"\" {cmd}", shell=True)
        return f"Opened {name}."
    except Exception as e:
        return f"Error opening {name}: {e}"


@tool(
    "open_website",
    "Open a website in the default browser. Accepts a URL or a known site "
    "name (youtube, google, gmail, netflix...).",
    {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL or site name"}},
        "required": ["url"],
    },
)
def open_website(url: str) -> str:
    u = WEBSITES.get(url.strip().lower(), url.strip())
    if not u.startswith("http"):
        u = "https://" + u
    webbrowser.open(u)
    return f"Opened {u} in the browser."
