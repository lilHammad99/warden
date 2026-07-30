"""Read PDF documents for Jarvis.

``read_document`` (Phase 28) reads Word/OpenDocument files, but it deliberately
refuses a ``.pdf`` -- and PDFs are the single most common document a real user
has (resumes, letters, bank statements, reports). This closes that gap:
``read_pdf`` pulls the readable text out of a PDF so Jarvis can read, summarise
or answer questions about it ("read my resume.pdf", "summarise this report",
"what does this letter say"), the natural partner to ``find_files`` (locate the
PDF, then read it).

Dependency: this needs ``pypdf`` -- a well-established, pure-Python, offline
package (no compiler, no network). It is imported LAZILY inside the tool so it
never slows Jarvis's startup, and if it is somehow missing at runtime the tool
degrades to a friendly "install pypdf" message rather than crashing.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point this at something enormous):

- **Rooted in the user's home only.** The path is resolved and REJECTED unless
  it lives inside the user's home directory (same boundary as ``find_files``),
  so the model can never read a PDF from ``C:\\Windows``.
- **Bounded everywhere.** The file on disk, the number of pages walked, a
  wall-clock extraction budget, and the returned text are all capped, so a huge
  or pathological PDF can't exhaust memory, hang, or flood the agent's context.
- **Pure ASCII out.** Curly quotes, dashes and accents are transliterated to
  plain ASCII (reusing read_document's transliterator), so extracted text can
  never corrupt the console/context.
- **Never raises.** A corrupt/non-PDF file, a password-protected PDF, a scanned
  (image-only) PDF, a missing dependency, the wrong type, an empty or missing
  path -- every one comes back as a friendly, pure-ASCII string.
"""

import logging
import time
import warnings
from pathlib import Path

from .document import _ascii_body, _tidy
from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400                     # a path, not an essay
MAX_FILE_BYTES = 40 * 1024 * 1024      # refuse a PDF file bigger than this (40 MB)
MAX_PAGES = 500                        # cap how many pages we walk
MAX_CHARS = 10000                      # cap the returned text (like read_document)
EXTRACT_TIME_BUDGET = 20.0             # wall-clock cap while pulling text out


def _import_pypdf():
    """Import pypdf lazily. Returns the module, or None if it isn't installed.
    Kept as a tiny seam so startup pays nothing and the smoke test can simulate
    a missing dependency."""
    try:
        import pypdf  # noqa: F401
        return pypdf
    except Exception:
        return None


def _extract(reader) -> tuple[str, int, int]:
    """Pull text out of an open pypdf reader, bounded on pages, characters, and
    wall-clock time. Returns (text, pages_total, pages_read). Never raises: a
    page that won't extract is skipped, not fatal."""
    try:
        pages = reader.pages
        total = len(pages)
    except Exception:
        return "", 0, 0
    deadline = time.monotonic() + EXTRACT_TIME_BUDGET
    parts: list[str] = []
    chars = 0
    read = 0
    limit = min(total, MAX_PAGES)
    for i in range(limit):
        if time.monotonic() > deadline:
            break
        try:
            txt = pages[i].extract_text() or ""
        except Exception:
            txt = ""
        parts.append(txt)
        read += 1
        chars += len(txt)
        # Enough raw text to fill the returned-text budget several times over --
        # no point walking a 500-page book once we can't show more of it.
        if chars > MAX_CHARS * 3:
            break
    return "\n".join(parts), total, read


@tool(
    "read_pdf",
    "Read the text of a PDF (.pdf) document and return its contents. Use this "
    "whenever the user wants you to read, summarise, or answer questions about a "
    "PDF ('read my resume.pdf', 'summarise this report', 'what does this letter "
    "say'); read_file only handles plain text and read_document only handles "
    "Word/OpenDocument, so neither works for a PDF. Locate the file first with "
    "find_files if you don't have its exact path. Only the user's own folders "
    "are allowed.",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The PDF to read, e.g. 'Documents/resume.pdf'.",
            },
        },
        "required": ["path"],
    },
)
def read_pdf(path: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("document"),
                     extra.get("doc"), extra.get("source"), extra.get("name"),
                     extra.get("filename"), extra.get("pdf"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me which PDF to read, sir."

    p, err = _resolve_under_home(raw)
    if p is None:
        return err or "Error: that PDF path isn't valid, sir."
    if not p.exists():
        return f"Error: I can't find '{_ascii(str(p))}', sir."
    if p.is_dir():
        return (f"Error: '{_ascii(p.name)}' is a folder, sir; give me a PDF "
                "file to read.")

    suffix = p.suffix.lower()
    if suffix != ".pdf":
        if suffix in (".docx", ".odt"):
            return (f"Error: '{_ascii(p.name)}' is a Word/OpenDocument file, "
                    "sir; use read_document for that. read_pdf is for PDFs.")
        if suffix in (".txt", ".md", ".csv", ".log", ".json", ".py", ".ini"):
            return (f"Error: '{_ascii(p.name)}' is a plain-text file, sir; use "
                    "read_file for that. read_pdf is for PDF documents.")
        return (f"Error: I don't know how to read a '{_ascii(suffix or 'no-ext')}' "
                "file as a PDF, sir; read_pdf is for PDF documents.")

    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    if size > MAX_FILE_BYTES:
        return (f"Error: '{_ascii(p.name)}' is too large for me to read safely, "
                "sir.")

    pypdf = _import_pypdf()
    if pypdf is None:
        return ("Error: I can't read PDFs yet, sir -- the 'pypdf' package isn't "
                "installed. Install it with: pip install pypdf")

    # pypdf reports malformed files via BOTH warnings and the logging module
    # ("invalid pdf header", "EOF marker not found", ...); silence both so a
    # corrupt PDF comes back only as our friendly string, never console noise.
    pypdf_log = logging.getLogger("pypdf")
    saved_level = pypdf_log.level
    pypdf_log.setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # keep the console clean
            try:
                reader = pypdf.PdfReader(str(p))
            except Exception:
                return (f"Error: '{_ascii(p.name)}' isn't a valid PDF, sir; it "
                        "may be corrupt or not really a PDF.")

            if getattr(reader, "is_encrypted", False):
                # Try an empty password (covers owner-only encryption); if that
                # fails the PDF really needs a password we don't have.
                try:
                    ok = reader.decrypt("")
                except Exception:
                    ok = 0
                if not ok:
                    return (f"Error: '{_ascii(p.name)}' is password-protected, "
                            "sir; I can't open it without the password.")

            text, total_pages, pages_read = _extract(reader)
    except Exception as e:
        return f"Error: couldn't read that PDF, sir ({_ascii(str(e))})."
    finally:
        pypdf_log.setLevel(saved_level)

    body = _tidy(_ascii_body(text))
    if not body.strip():
        return (f"'{_ascii(p.name)}' has no readable text, sir (it may be a "
                "scanned document made of page images rather than text).")

    words = len(body.split())
    notes = []
    if total_pages > MAX_PAGES:
        notes.append(f"first {MAX_PAGES} of {total_pages} pages")
    elif pages_read < total_pages:
        notes.append(f"first {pages_read} of {total_pages} pages")
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS].rstrip() + "\n...[truncated]"
        notes.append("start shown")
    note = f" ({', '.join(notes)})" if notes else ""
    page_word = "page" if total_pages == 1 else "pages"
    head = (f"{_ascii(p.name)} -- {total_pages} {page_word}, "
            f"{words} word{'s' if words != 1 else ''}{note}:")
    return f"{head}\n{body}"
