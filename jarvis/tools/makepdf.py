"""Create a real PDF document for Jarvis.

Before this, asking Jarvis to "write my CV as a PDF" made it call ``write_file``
with a ``.pdf`` name and dump plain text inside -- the bytes are NOT a PDF, so
no viewer can open the file. ``create_pdf`` writes a genuine, openable PDF
(cover title + wrapped body text) so "make me a CV / cover letter / report as a
PDF" actually produces a document the user can open, print, or email.

Dependency: ``fpdf2`` -- a small, pure-Python, offline PDF writer (no compiler,
no network), imported LAZILY so startup pays nothing and a missing install
degrades to a friendly message instead of crashing.

Safety mirrors the other file tools: the path is resolved and REFUSED unless it
stays inside the user's home; content is bounded; text is transliterated to
plain ASCII (fpdf's built-in fonts are Latin-1 only, and this reuses
read_document's transliterator) so odd characters can never crash the writer;
the tool never raises.
"""

from pathlib import Path

from .document import _ascii_body
from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400
MAX_CONTENT = 200000   # refuse an absurd amount of text (a document, not a book)
MAX_TITLE = 200


def _import_fpdf():
    try:
        from fpdf import FPDF
        return FPDF
    except Exception:
        return None


@tool(
    "create_pdf",
    "Create a real, openable PDF document and save it. Use this WHENEVER the "
    "user wants something written AS A PDF -- a CV/resume, cover letter, report, "
    "letter, or essay 'as a pdf' / 'in pdf' ('make me a CV as a PDF', 'write a "
    "cover letter and save it as pdf'). Do NOT use write_file for a .pdf -- that "
    "produces a broken file that won't open; create_pdf writes a genuine PDF. "
    "Give path (e.g. 'Desktop/CV.pdf'), content (the FULL text of the document), "
    "and optionally title (a heading shown at the top). Only the user's own "
    "folders are allowed.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "Where to save it, e.g. 'Desktop/CV.pdf'."},
            "content": {"type": "string",
                        "description": "The full text of the document."},
            "title": {"type": "string",
                      "description": "Optional heading shown at the top."},
        },
        "required": ["path", "content"],
    },
)
def create_pdf(path: str = "", content: str = "", title: str = "", **extra) -> str:
    raw = _first_str(path, extra.get("file"), extra.get("filename"),
                     extra.get("dest"), extra.get("document"), extra.get("output"),
                     extra.get("name"))
    raw = _coerce(raw, MAX_PATH_LEN)
    if not raw:
        return "Error: tell me where to save the PDF, sir (e.g. Desktop/CV.pdf)."

    body = _first_str(content, extra.get("text"), extra.get("body"),
                      extra.get("essay"), extra.get("message"))
    if not isinstance(body, str) or not body.strip():
        return "Error: tell me what to put in the PDF, sir."

    head = _first_str(title, extra.get("heading"), extra.get("header"))

    p, err = _resolve_under_home(raw)
    if p is None:
        return err or "Error: that PDF path isn't valid, sir."
    if p.suffix.lower() != ".pdf":
        p = p.with_suffix(".pdf")
    if p.is_dir():
        return f"Error: '{_ascii(p.name)}' is a folder, sir; give me a file name."

    FPDF = _import_fpdf()
    if FPDF is None:
        return ("Error: I can't make PDFs yet, sir -- the 'fpdf2' package isn't "
                "installed. Install it with: pip install fpdf2")

    # fpdf's core fonts are Latin-1: transliterate everything to plain ASCII so
    # curly quotes, bullets, accents, emoji etc. can never crash the writer.
    text = _ascii_body(body[:MAX_CONTENT])
    heading = _ascii(head[:MAX_TITLE]) if head else ""

    try:
        pdf = FPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.set_margins(20, 20, 20)
        pdf.add_page()
        # keep the cursor returning to the left margin after each block, else the
        # next full-width multi_cell has zero space ("can't render a character")
        nl = {"new_x": "LMARGIN", "new_y": "NEXT"}
        if heading:
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 9, heading, **nl)
            pdf.ln(3)
        pdf.set_font("Helvetica", size=12)
        for line in text.split("\n"):
            line = line.rstrip()
            if not line:
                pdf.ln(4)
            else:
                pdf.multi_cell(0, 6, line, **nl)
        p.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(p))
        pages = pdf.pages_count if hasattr(pdf, "pages_count") else len(pdf.pages)
    except Exception as e:
        return f"Error: couldn't create that PDF, sir ({_ascii(str(e))})."

    page_word = "page" if pages == 1 else "pages"
    return f"Created a {pages}-{page_word} PDF at {_ascii(str(p))}."
