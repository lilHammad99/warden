from pathlib import Path

from ..config import HOME
from .registry import tool


def _resolve(path: str) -> Path:
    p = Path(path.strip().strip('"'))
    p = Path(str(p).replace("~", str(HOME)))
    if not p.is_absolute():
        p = HOME / p  # so "Desktop/essay.txt" lands on the Desktop
    return p


@tool(
    "write_file",
    "Create or overwrite a text file and write content into it. Use for "
    "essays, notes, code, lists — any time the user asks you to make or "
    "write a file. Relative paths resolve against the user's home folder, "
    "so 'Desktop/essay.txt' puts it on the Desktop.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, e.g. Desktop/essay.txt"},
            "content": {"type": "string", "description": "Full text to write"},
        },
        "required": ["path", "content"],
    },
)
def write_file(path: str, content: str) -> str:
    p = _resolve(path)
    suffix = p.suffix.lower()
    _real = {".pdf": ("create_pdf", "PDF"),
             ".docx": ("create_docx", "Word document"),
             ".xlsx": ("create_xlsx", "Excel spreadsheet")}
    if suffix in _real:
        # writing raw text into an Office/PDF file makes something no viewer can
        # open; send the model to the tool that writes a real one instead
        realtool, kind = _real[suffix]
        return (f"Error: I can't make a real {kind} with write_file, sir -- that "
                f"would create a file that won't open. Use {realtool} instead.")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {p}"


@tool(
    "append_file",
    "Append text to the end of an existing file (creates it if missing).",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
)
def append_file(path: str, content: str) -> str:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(content)
    return f"Appended {len(content)} characters to {p}"


@tool(
    "read_file",
    "Read a text file and return its content (truncated to 8000 chars).",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)
def read_file(path: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return f"Error: {p} does not exist."
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > 8000:
        text = text[:8000] + "\n...[truncated]"
    return text


@tool(
    "list_folder",
    "List files and folders inside a folder. Defaults to the Desktop.",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Folder path, default Desktop"}},
        "required": [],
    },
)
def list_folder(path: str = "Desktop") -> str:
    p = _resolve(path)
    if not p.is_dir():
        return f"Error: {p} is not a folder."
    items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    lines = [f"{'[dir] ' if i.is_dir() else ''}{i.name}" for i in items[:100]]
    return f"Contents of {p}:\n" + "\n".join(lines)
