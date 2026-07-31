"""Extract items (emails, links, phone numbers, IPs, numbers) from text or a
file -- a productivity / text-handling tool for Jarvis.

Pulling every email address, link, or phone number out of a wall of text is an
everyday chore ("get all the email addresses from this", "pull the links out of
my clipboard", "find all the phone numbers in this document") -- and an 8B local
model is unreliable at it: it silently drops some, invents others, or mangles
the formatting. ``extract_items`` finds them EXACTLY with real pattern matching,
de-duplicates them, and lists them, so Jarvis answers with a real list rather
than a hallucinated one. A text/productivity win that pairs with ``get_clipboard``
(pull items out of what the user just copied) and ``find_files`` / ``read_document``
(locate a document, then harvest its contacts/links).

It works on EITHER some text passed directly OR a file -- a plain-text file
read straight, or a Word (.docx) / OpenDocument (.odt) document, reusing
``count_words``'s bounded, binary-sniffed reader (no duplicated parsing, no new
dependency).

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, an unknown kind, or point this at something enormous):

- **Rooted in the user's home only.** A file path is resolved and REJECTED
  unless it lives inside the user's home directory (same boundary as
  ``find_files``), so it can never read a file from ``C:\\Windows``.
- **Bounded everywhere.** Directly-passed text is capped, an over-large or
  binary/PDF file is refused before reading, the number of listed items is
  capped, and every item is length-bounded -- a giant or hostile input can't
  exhaust memory or flood the agent's context.
- **Pure ASCII out.** Every returned item is forced to safe single-line ASCII,
  so output can never corrupt the console/context.
- **Never raises.** An unknown kind, a missing/empty argument, a binary/PDF or
  missing file, a folder, or the wrong type -- every one comes back as a
  friendly, pure-ASCII string the model can read and recover from.
"""

import re

from .find import _coerce
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool
from .textstats import (MAX_PATH_LEN, MAX_TEXT_LEN, _looks_like_path,
                        _read_file_text)

MAX_ITEMS = 200        # how many distinct items to list before summarising
MAX_ITEM_LEN = 200     # cap a single item's length (a runaway URL, say)

# --- patterns -------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?\.[A-Za-z]{2,24}")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]{}\"'`]+", re.IGNORECASE)
# candidate phone runs; validated (digit count + real separators) afterwards
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{5,}\d")
_IP_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

_URL_TRAIL = ".,;:!?)>]}'\"`"   # punctuation that clings to the end of a URL

# every spelling the 8B might use for a kind -> the canonical kind
_KIND_ALIASES = {
    "email": "emails", "emails": "emails", "e-mail": "emails",
    "e-mails": "emails", "mail": "emails", "mails": "emails",
    "address": "emails", "addresses": "emails", "email address": "emails",
    "email addresses": "emails",
    "url": "urls", "urls": "urls", "link": "urls", "links": "urls",
    "website": "urls", "websites": "urls", "web address": "urls",
    "web addresses": "urls", "site": "urls", "sites": "urls",
    "phone": "phones", "phones": "phones", "phone number": "phones",
    "phone numbers": "phones", "telephone": "phones", "tel": "phones",
    "mobile": "phones", "mobiles": "phones", "cell": "phones",
    "cell number": "phones", "number to call": "phones",
    "ip": "ips", "ips": "ips", "ip address": "ips", "ip addresses": "ips",
    "ipv4": "ips", "ip addr": "ips",
    "number": "numbers", "numbers": "numbers", "figure": "numbers",
    "figures": "numbers", "digit": "numbers", "digits": "numbers",
    "amount": "numbers", "amounts": "numbers",
}
_KIND_LABEL = {
    "emails": "email address", "urls": "link", "phones": "phone number",
    "ips": "IP address", "numbers": "number",
}
_KIND_ORDER = ["emails", "urls", "phones", "ips", "numbers"]


def _resolve_kind(raw: str) -> str:
    """Map whatever the model asked for to a canonical kind, or '' if unknown."""
    k = _coerce(raw, 40).lower().strip()
    if not k:
        return ""
    if k in _KIND_ALIASES:
        return _KIND_ALIASES[k]
    # word-level fallback so "all the emails" / "phone numbers please" still map,
    # WITHOUT the false positives a raw substring test would cause ("hotel"->tel)
    words = re.findall(r"[a-z]+", k)
    for w in words:
        if w in _KIND_ALIASES:
            return _KIND_ALIASES[w]
    return ""


def _find_emails(text):
    return [m.group(0) for m in _EMAIL_RE.finditer(text)]


def _find_urls(text):
    out = []
    for m in _URL_RE.finditer(text):
        u = m.group(0).rstrip(_URL_TRAIL)
        if u and (u.lower().startswith("http") or "." in u[4:]):
            out.append(u)
    return out


def _find_phones(text):
    out = []
    for m in _PHONE_RE.finditer(text):
        s = m.group(0).strip()
        digits = re.sub(r"\D", "", s)
        if not (7 <= len(digits) <= 15):
            continue
        # a bare run of digits with no separator is a number, not a phone
        if not (s.startswith("+") or any(c in " ().-" for c in s)):
            continue
        out.append(re.sub(r"\s+", " ", s))
    return out


def _find_ips(text):
    out = []
    for m in _IP_RE.finditer(text):
        s = m.group(0)
        if all(part.isdigit() and int(part) <= 255 for part in s.split(".")):
            out.append(s)
    return out


def _find_numbers(text):
    return [m.group(0).rstrip(",") for m in _NUMBER_RE.finditer(text)
            if m.group(0).rstrip(",")]


_FINDERS = {
    "emails": _find_emails, "urls": _find_urls, "phones": _find_phones,
    "ips": _find_ips, "numbers": _find_numbers,
}
# kinds whose items are matched case-insensitively for de-duplication
_CASELESS = {"emails", "urls"}


def _dedupe(items, caseless):
    """First-seen order, de-duplicated (case-insensitively for emails/urls)."""
    seen = set()
    out = []
    for it in items:
        it = _ascii(it)[:MAX_ITEM_LEN].strip()
        if not it:
            continue
        key = it.lower() if caseless else it
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _plural(n, label):
    return label if n == 1 else (label + "es" if label.endswith("s") else label + "s")


def _report(kind, items, where, note):
    label = _KIND_LABEL[kind]
    if not items:
        msg = f"I didn't find any {_plural(2, label)} in {where}, sir."
        return (msg + " " + note).strip()
    shown = items[:MAX_ITEMS]
    n = len(items)
    head = f"Found {n} {_plural(n, label)} in {where}: " + ", ".join(shown)
    if n > MAX_ITEMS:
        head += f", ... (and {n - MAX_ITEMS} more; showing the first {MAX_ITEMS})"
    else:
        head += "."
    if note:
        head += " " + note
    return head


@tool(
    "extract_items",
    "Pull all the email addresses, links/URLs, phone numbers, IP addresses, or "
    "numbers out of some text or a file. Use this whenever the user wants to "
    "collect or list every one of a kind of item from a block of text ('get all "
    "the email addresses from this', 'pull the links out of my clipboard', 'find "
    "all the phone numbers in this document'); your own extraction is unreliable, "
    "this is exact. Give kind (emails, urls, phones, ips, or numbers) and EITHER "
    "text with the words to search OR path to a file (plain text, or a Word .docx "
    "/ OpenDocument .odt -- locate it with find_files first if you don't have the "
    "path). Only the user's own folders are allowed.",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "What to extract: 'emails', 'urls' (links), "
                "'phones', 'ips', or 'numbers'.",
            },
            "text": {
                "type": "string",
                "description": "The text to search, when the user gave it to you "
                "directly (e.g. from the clipboard).",
            },
            "path": {
                "type": "string",
                "description": "A file to search instead, e.g. "
                "'Documents/contacts.txt' or 'Desktop/letter.docx'.",
            },
        },
        "required": ["kind"],
    },
)
def extract_items(kind: str = "", text: str = "", path: str = "", **extra) -> str:
    kind_raw = _first_str(kind, extra.get("type"), extra.get("what"),
                          extra.get("item"), extra.get("items"),
                          extra.get("target"))
    canon = _resolve_kind(kind_raw)
    if not canon:
        return ("Error: tell me what to pull out, sir -- one of: emails, urls "
                "(links), phones, ips, or numbers.")

    path_raw = _first_str(path, extra.get("file"), extra.get("document"),
                          extra.get("doc"), extra.get("source"),
                          extra.get("filename"))
    path_raw = _coerce(path_raw, MAX_PATH_LEN)

    text_raw = _first_str(text, extra.get("content"), extra.get("string"),
                          extra.get("body"), extra.get("input"))

    # a filename dropped into the 'text' field (a common 8B slip) -> read the file
    if not path_raw and text_raw and _looks_like_path(text_raw):
        path_raw = _coerce(text_raw, MAX_PATH_LEN)
        text_raw = ""

    note = ""
    if path_raw:
        p, err = _resolve_under_home(path_raw)
        if p is None:
            return err or "Error: that file path isn't valid, sir."
        if not p.exists():
            return f"Error: I can't find '{_ascii(str(p))}', sir."
        if p.is_dir():
            return (f"Error: '{_ascii(p.name)}' is a folder, sir; give me a "
                    "file or some text to search.")
        body, err = _read_file_text(p)
        if err:
            return err
        where = f"'{_ascii(p.name)}'"
    else:
        if not text_raw:
            return "Error: give me some text or a file to search, sir."
        body = text_raw
        where = "that text"
        if len(body) > MAX_TEXT_LEN:
            body = body[:MAX_TEXT_LEN]
            note = "(searched the first part; the rest was too long to take in.)"

    items = _dedupe(_FINDERS[canon](body), canon in _CASELESS)
    return _report(canon, items, where, note)
