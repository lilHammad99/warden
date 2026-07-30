"""Read Word / OpenDocument documents for Jarvis.

``read_file`` only understands plain text, so the moment Jarvis is pointed at a
real Word document ("read my resume", "what does that letter say", "summarise
this report") it gets a wall of binary zip bytes and can say nothing useful.
This closes that gap: ``read_document`` pulls the actual readable text out of a
``.docx`` (Microsoft Word) or ``.odt`` (LibreOffice / OpenDocument) file so the
model can read, summarise, or answer questions about it -- a real autonomy win,
and the natural partner to ``find_files`` (locate the document, then read it).

Pure standard library: a ``.docx`` / ``.odt`` is a ZIP of XML, so ``zipfile`` +
``xml.etree`` are all it takes -- NO new dependency.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point this at something enormous):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless
  it lives inside the user's home directory (same boundary as ``find_files``),
  so the model can never read a document from ``C:\\Windows``.
- **Bounded everywhere.** The file on disk, the uncompressed document XML, the
  paragraph count, and the returned text are all capped, so a zip-bomb or a
  giant document can't exhaust memory or flood the agent's context.
- **Pure ASCII out.** Word's curly quotes, dashes and accents are transliterated
  to plain ASCII, so the extracted text can never corrupt the console/context.
- **Never raises.** A corrupt/non-zip file, a missing document part, the wrong
  type, an empty or missing path -- every one comes back as a friendly,
  pure-ASCII string the model can read and recover from.
"""

import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400                     # a path, not an essay
MAX_FILE_BYTES = 25 * 1024 * 1024      # refuse a document file bigger than this
MAX_XML_BYTES = 60 * 1024 * 1024       # cap the UNCOMPRESSED document xml (zip-bomb guard)
MAX_PARAGRAPHS = 20000                 # cap how many paragraphs we walk
MAX_CHARS = 10000                      # cap the returned text (like read_file)

# Word / OpenDocument punctuation that would otherwise become '?' noise once
# forced to ASCII -- map it to a sensible plain-ASCII equivalent first.
_PUNCT = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "―": "-",
    "…": "...", "•": "* ", "·": "*",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
}


def _ascii_body(text: str) -> str:
    """Force extracted document text to safe, bounded pure ASCII while KEEPING
    line and tab structure (unlike the single-line ``_ascii`` used for messages).
    Curly quotes/dashes are transliterated and accents are stripped (cafe, not
    caf?) so real Word text stays readable."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for bad, good in _PUNCT.items():
        text = text.replace(bad, good)
    # NFKD splits accented letters into base + combining mark; dropping the
    # non-ASCII marks leaves the readable base letter behind.
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")


def _local(tag) -> str:
    """Local XML tag name without its namespace ('{ns}p' -> 'p')."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _read_part(zf: "zipfile.ZipFile", name: str) -> bytes:
    """Read one entry from the zip, refusing an entry whose UNCOMPRESSED size is
    over the cap (a lying/huge document part can't blow up memory). Returns the
    bytes, or b'' if the entry is missing or too large."""
    try:
        info = zf.getinfo(name)
    except KeyError:
        return b""
    if info.file_size > MAX_XML_BYTES:
        return b""
    try:
        return zf.read(name)
    except Exception:
        return b""


def _extract_docx(zf: "zipfile.ZipFile") -> str:
    """Pull readable text out of a Word .docx (WordprocessingML). Text lives in
    <w:t>; <w:tab>/<w:br>/<w:cr> mark whitespace; each <w:p> is one paragraph."""
    xml = _read_part(zf, "word/document.xml")
    if not xml:
        return ""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    lines: list[str] = []
    count = 0
    for para in (el for el in root.iter() if _local(el.tag) == "p"):
        parts: list[str] = []
        for el in para.iter():
            tag = _local(el.tag)
            if tag == "t":
                parts.append(el.text or "")
            elif tag == "tab":
                parts.append("\t")
            elif tag in ("br", "cr"):
                parts.append("\n")
        lines.append("".join(parts))
        count += 1
        if count >= MAX_PARAGRAPHS:
            break
    return "\n".join(lines)


def _extract_odt(zf: "zipfile.ZipFile") -> str:
    """Pull readable text out of an OpenDocument .odt. Paragraphs/headings are
    <text:p>/<text:h>; their text is captured with itertext()."""
    xml = _read_part(zf, "content.xml")
    if not xml:
        return ""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    lines: list[str] = []
    count = 0
    for para in (el for el in root.iter() if _local(el.tag) in ("p", "h")):
        lines.append("".join(para.itertext()))
        count += 1
        if count >= MAX_PARAGRAPHS:
            break
    return "\n".join(lines)


def _tidy(text: str) -> str:
    """Collapse runs of 3+ blank lines and trim, so the output reads cleanly."""
    out: list[str] = []
    blanks = 0
    for line in text.split("\n"):
        if line.strip():
            blanks = 0
            out.append(line.rstrip())
        else:
            blanks += 1
            if blanks <= 1:
                out.append("")
    return "\n".join(out).strip("\n")


@tool(
    "read_document",
    "Read the text of a Word (.docx) or OpenDocument (.odt) document and return "
    "its contents. Use this INSTEAD of read_file whenever the user wants you to "
    "read, summarise, or answer questions about a Word document ('read my "
    "resume', 'what does that letter say', 'summarise this report'); read_file "
    "only handles plain text and would return unreadable data for these. Locate "
    "the file first with find_files if you don't have its exact path. Only the "
    "user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The document to read, e.g. 'Documents/resume.docx'.",
            },
        },
        "required": ["path"],
    },
)
def read_document(path: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("document"),
                     extra.get("doc"), extra.get("source"), extra.get("name"),
                     extra.get("filename"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me which document to read, sir."

    p, err = _resolve_under_home(raw)
    if p is None:
        return err or "Error: that document path isn't valid, sir."
    if not p.exists():
        return f"Error: I can't find '{_ascii(str(p))}', sir."
    if p.is_dir():
        return (f"Error: '{_ascii(p.name)}' is a folder, sir; give me a "
                "document file to read.")

    suffix = p.suffix.lower()
    if suffix not in (".docx", ".odt"):
        if suffix == ".pdf":
            return ("Error: I can't read PDF files yet, sir; I can read Word "
                    "(.docx) and OpenDocument (.odt) documents.")
        if suffix in (".txt", ".md", ".csv", ".log", ".json", ".py", ".ini"):
            return (f"Error: '{_ascii(p.name)}' is a plain-text file, sir; use "
                    "read_file for that. read_document is for Word (.docx) and "
                    "OpenDocument (.odt) documents.")
        return (f"Error: I don't know how to read a '{_ascii(suffix or 'no-ext')}' "
                "file, sir; I read Word (.docx) and OpenDocument (.odt) documents "
                "(and read_file handles plain text).")

    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    if size > MAX_FILE_BYTES:
        return (f"Error: '{_ascii(p.name)}' is too large for me to read safely, "
                "sir.")

    try:
        with zipfile.ZipFile(str(p)) as zf:
            text = _extract_docx(zf) if suffix == ".docx" else _extract_odt(zf)
    except zipfile.BadZipFile:
        return (f"Error: '{_ascii(p.name)}' isn't a valid {suffix} document, "
                "sir; it may be corrupt or an older format.")
    except Exception as e:
        return f"Error: couldn't read that document, sir ({_ascii(str(e))})."

    body = _tidy(_ascii_body(text))
    if not body.strip():
        return (f"'{_ascii(p.name)}' appears to have no readable text, sir "
                "(it may be empty or only images).")

    words = len(body.split())
    truncated = ""
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS].rstrip() + "\n...[truncated]"
        truncated = " (start shown)"
    head = f"{_ascii(p.name)} -- {words} word{'s' if words != 1 else ''}{truncated}:"
    return f"{head}\n{body}"
