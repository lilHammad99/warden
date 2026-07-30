"""Count words / measure text for Jarvis -- a productivity & text-handling tool.

The 8B local model is genuinely bad at counting: ask it "how many words is my
essay" or "is my cover letter under 300 words" and it guesses, usually wrong.
``count_words`` measures text EXACTLY instead -- words, characters, lines, a
rough sentence count, and how long it takes to read or say aloud -- so Jarvis
can answer length questions the way ``calculate`` answers arithmetic ones: with
a real number, not a hallucinated one. A real accuracy/autonomy win, and a
natural partner to ``find_files`` / ``read_document`` (locate the essay, then
size it up).

It measures EITHER some text passed directly ("count the words in this: ...")
OR a file -- a plain-text file (.txt/.md/.csv/...) read straight, or a Word
(.docx) / OpenDocument (.odt) document whose real text is pulled out by reusing
``read_document``'s extractor. So it covers both "count this paragraph" and
"how long is my resume".

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point this at something enormous):

- **Rooted in the user's home only.** A file path is resolved and REJECTED
  unless it lives inside the user's home directory (same boundary as
  ``find_files``), so it can never read a file from ``C:\\Windows``.
- **Bounded everywhere.** Directly-passed text is capped, an over-large file is
  refused before reading, and the document extractor is already zip-bomb
  bounded, so a giant input can't exhaust memory.
- **Pure ASCII out.** Only counts and the (ASCII-forced) file name are ever
  returned, so output can never corrupt the console/context.
- **Never raises.** A binary/PDF file, a missing file, a folder, the wrong
  type, an empty or missing argument -- every one comes back as a friendly,
  pure-ASCII string the model can read and recover from.
"""

import re
import zipfile
from pathlib import Path

from .document import (MAX_FILE_BYTES, _ascii_body, _extract_docx,
                       _extract_odt, _tidy)
from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400                 # a path, not an essay
MAX_TEXT_LEN = 200_000             # cap directly-passed text (~40k words)
READ_WPM = 200                     # average adult silent reading speed
SPEAK_WPM = 130                    # average speaking-aloud pace

# file types that clearly are NOT plain text -- refuse rather than count the
# garbage that decoding their bytes would produce.
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif", ".tiff",
    ".zip", ".gz", ".7z", ".rar", ".tar", ".exe", ".dll", ".msi", ".bin",
    ".mp3", ".wav", ".mp4", ".mov", ".avi", ".mkv", ".ttf", ".otf", ".woff",
    ".xlsx", ".pptx", ".doc", ".xls", ".ppt",
}
_SENTENCE_RE = re.compile(r"[.!?]+")
# a real file extension: a dot then a letter then up to 7 more letters/digits,
# at the very end (so "3.14" / "test." are NOT treated as file references).
_EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")


def _dur(words: int, wpm: int) -> str:
    """A short, pure-ASCII duration phrase for reading/speaking ``words``."""
    if words <= 0:
        return "under 1 min"
    mins = words / float(wpm)
    if mins < 1:
        return "under 1 min"
    return f"about {round(mins)} min"


def _stats_line(label: str, text: str, note: str = "") -> str:
    """Turn measured text into the friendly, pure-ASCII stats sentence."""
    words = len(text.split())
    chars = len(text)
    chars_ns = sum(1 for c in text if not c.isspace())
    lines = len(text.splitlines()) if text else 0
    sentences = len(_SENTENCE_RE.findall(text))

    def s(n):
        return "" if n == 1 else "s"

    head = (f"{label}: {words} word{s(words)}, {chars} character{s(chars)} "
            f"({chars_ns} without spaces), {lines} line{s(lines)}, "
            f"{sentences} sentence{s(sentences)} (approx). "
            f"Reading time {_dur(words, READ_WPM)}; "
            f"speaking aloud {_dur(words, SPEAK_WPM)}.")
    if note:
        head += " " + note
    return head


def _looks_like_path(value: str) -> bool:
    """True if a directly-passed 'text' value is really a file reference the
    model dropped into the wrong field: a single line, no spaces, with a path
    separator or an extension. Prose (spaces / newlines) is never matched, so a
    real paragraph is always counted as text."""
    v = value.strip()
    if not v or len(v) > MAX_PATH_LEN:
        return False
    if any(c.isspace() for c in v):
        return False
    return ("/" in v) or ("\\" in v) or bool(_EXT_RE.search(v))


def _read_file_text(p: Path):
    """Pull readable text out of a file for counting. Returns (text, error).
    Plain-text files are read straight (bounded + binary-sniffed); Word/ODT
    documents reuse read_document's extractor. Never raises."""
    suffix = p.suffix.lower()

    if suffix == ".pdf":
        return "", ("Error: I can't read PDF files yet, sir, so I can't count "
                    "their words.")
    if suffix in _BINARY_EXT:
        return "", (f"Error: '{_ascii(p.name)}' isn't a text file, sir, so I "
                    "can't count its words.")

    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    if size > MAX_FILE_BYTES:
        return "", (f"Error: '{_ascii(p.name)}' is too large for me to measure "
                    "safely, sir.")

    if suffix in (".docx", ".odt"):
        try:
            with zipfile.ZipFile(str(p)) as zf:
                raw = _extract_docx(zf) if suffix == ".docx" else _extract_odt(zf)
        except zipfile.BadZipFile:
            return "", (f"Error: '{_ascii(p.name)}' isn't a valid {suffix} "
                        "document, sir; it may be corrupt.")
        except Exception as e:
            return "", f"Error: couldn't read that document, sir ({_ascii(str(e))})."
        return _tidy(_ascii_body(raw)), ""

    # anything else: treat as plain text
    try:
        data = p.read_bytes()
    except Exception as e:
        return "", f"Error: couldn't read that file, sir ({_ascii(str(e))})."
    if b"\x00" in data:  # NUL byte -> almost certainly binary, not text
        return "", (f"Error: '{_ascii(p.name)}' doesn't look like text, sir, so "
                    "I can't count its words.")
    return data.decode("utf-8", "replace"), ""


@tool(
    "count_words",
    "Count the words (and characters, lines, sentences, and reading time) in "
    "some text or a file. Use this whenever the user asks how long something is "
    "or how many words/characters it has ('how many words is my essay', 'is my "
    "cover letter under 300 words', 'word count of this'); your own counting is "
    "unreliable, this is exact. Give text with the words to measure OR path to a "
    "file (a plain-text file, or a Word .docx / OpenDocument .odt document -- "
    "locate it first with find_files if you don't have the path). Only the "
    "user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to measure, when counting words in "
                "text the user gave you directly.",
            },
            "path": {
                "type": "string",
                "description": "A file to measure instead, e.g. "
                "'Documents/essay.txt' or 'Desktop/resume.docx'.",
            },
        },
        "required": [],
    },
)
def count_words(text: str = "", path: str = "", **extra) -> str:
    path_raw = _first_str(path, extra.get("file"), extra.get("document"),
                          extra.get("doc"), extra.get("source"),
                          extra.get("filename"))
    path_raw = _coerce(path_raw, MAX_PATH_LEN)

    text_raw = _first_str(text, extra.get("content"), extra.get("string"),
                          extra.get("body"), extra.get("words"))

    # a filename dropped into the 'text' field (a common 8B slip) -> treat as a
    # file, so "count the words in essay.txt" still works.
    if not path_raw and text_raw and _looks_like_path(text_raw):
        path_raw = _coerce(text_raw, MAX_PATH_LEN)
        text_raw = ""

    if path_raw:
        p, err = _resolve_under_home(path_raw)
        if p is None:
            return err or "Error: that file path isn't valid, sir."
        if not p.exists():
            return f"Error: I can't find '{_ascii(str(p))}', sir."
        if p.is_dir():
            return (f"Error: '{_ascii(p.name)}' is a folder, sir; give me a "
                    "file or some text to count.")
        body, err = _read_file_text(p)
        if err:
            return err
        if not body.strip():
            return (f"'{_ascii(p.name)}' has no words to count, sir (it may be "
                    "empty or only images).")
        return _stats_line(_ascii(p.name), body)

    if not text_raw:
        return ("Error: give me some text or a file to count, sir.")

    note = ""
    if len(text_raw) > MAX_TEXT_LEN:
        text_raw = text_raw[:MAX_TEXT_LEN]
        note = "(measured the first part; the rest was too long to take in.)"
    return _stats_line("That text", text_raw, note)
