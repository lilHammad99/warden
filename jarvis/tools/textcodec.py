"""Encode / decode text: Base64, hexadecimal, and URL (percent) encoding.

A text/data-TRANSFORMATION win, and one that is squarely on-brand for a
"local - private - yours" assistant. Decoding a Base64 blob, a hex string or a
percent-encoded URL is an everyday chore -- a token someone pasted, a value out
of a log, a link with %20 in it -- and the usual answer is to paste it into some
website that SEES (and may log) whatever you hand it. The 8B model itself is
hopeless at these encodings (it invents or drops characters), so Jarvis now does
it EXACTLY, right here on the machine, and nothing ever leaves the PC:

    "decode this base64: aGVsbG8="        -> hello
    "base64 encode hello world"           -> aGVsbG8gd29ybGQ=
    "convert this to hex"                 -> 68656c6c6f
    "url decode hello%20world%21"         -> hello world!

Pure standard library (``base64`` / ``binascii`` / ``urllib.parse``), so there is
NO new dependency, and it pairs naturally with ``get_clipboard`` / ``set_clipboard``
("decode my clipboard", then "copy that").

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or a value that isn't valid for the chosen operation):

- **Bounded.** The input text is length-capped (``MAX_TEXT``); an over-long input
  is REFUSED rather than silently truncated (a truncated Base64/hex string would
  decode to corrupt bytes -- better to say no than to mislead).
- **Pure ASCII out.** Encoded output is ASCII by construction; DECODED output is
  forced to readable pure ASCII (curly quotes/accents transliterated, other bytes
  dropped) so a decoded binary blob can never corrupt the console/context.
- **Never raises.** Invalid Base64/hex, an unknown operation, empty/missing/
  wrong-type args are all coerced or turned into a friendly ASCII message; a bare
  "encode"/"decode" (which way? which format?) lists the choices so the model can
  self-correct.
"""

import base64
import binascii
import urllib.parse

from .registry import tool
from . import document

MAX_TEXT = 200_000   # generous; keeps input (and so output) bounded


# ---- operation resolution --------------------------------------------------
# Canonical operations and a forgiving alias map. The model may say any of a
# dozen things ("base64", "to base64", "b64 encode", "decode base64", ...); we
# normalise its phrasing to one of these six.
_OPS = ("base64_encode", "base64_decode", "hex_encode", "hex_decode",
        "url_encode", "url_decode")

_ALIASES = {
    # base64 encode
    "base64": "base64_encode", "b64": "base64_encode",
    "base64 encode": "base64_encode", "encode base64": "base64_encode",
    "base64 to": "base64_encode", "to base64": "base64_encode",
    "encode to base64": "base64_encode", "b64 encode": "base64_encode",
    "base 64": "base64_encode", "base64encode": "base64_encode",
    # base64 decode
    "base64 decode": "base64_decode", "decode base64": "base64_decode",
    "from base64": "base64_decode", "unbase64": "base64_decode",
    "b64 decode": "base64_decode", "b64decode": "base64_decode",
    "base64decode": "base64_decode", "base64 from": "base64_decode",
    # hex encode
    "hex": "hex_encode", "hexadecimal": "hex_encode",
    "hex encode": "hex_encode", "encode hex": "hex_encode",
    "to hex": "hex_encode", "encode to hex": "hex_encode",
    "hexencode": "hex_encode",
    # hex decode
    "hex decode": "hex_decode", "decode hex": "hex_decode",
    "from hex": "hex_decode", "unhex": "hex_decode",
    "hexdecode": "hex_decode",
    # url encode
    "url": "url_encode", "url encode": "url_encode", "urlencode": "url_encode",
    "encode url": "url_encode", "percent encode": "url_encode",
    "to url": "url_encode", "url escape": "url_encode",
    # url decode
    "url decode": "url_decode", "urldecode": "url_decode",
    "decode url": "url_decode", "from url": "url_decode",
    "percent decode": "url_decode", "unquote": "url_decode",
    "url unescape": "url_decode",
}


def _norm(s: str) -> str:
    """Normalise an operation phrase: lower-case, drop underscores/hyphens, and
    collapse runs of whitespace to a single space."""
    s = s.strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(s.split())


def _resolve_op(operation, fmt, direction) -> str | None:
    """Work out the canonical operation from whatever the model supplied.

    Prefers an explicit ``operation``; falls back to a separate ``format`` +
    ``direction`` pair. Returns one of ``_OPS`` or None if it can't be pinned
    down (e.g. a bare "decode" with no format)."""
    op = _norm(operation) if isinstance(operation, str) else ""
    if op:
        if op.replace(" ", "_") in _OPS:      # already canonical-ish
            return op.replace(" ", "_")
        if op in _ALIASES:
            return _ALIASES[op]
    # try to assemble from a format + direction pair the model may have split out
    f = _norm(fmt) if isinstance(fmt, str) else ""
    d = _norm(direction) if isinstance(direction, str) else ""
    # a direction word may be sitting in the operation field on its own
    if not d and op in ("encode", "decode"):
        d = op
    if not f and op in ("base64", "b64", "base 64"):
        f = "base64"
    elif not f and op in ("hex", "hexadecimal"):
        f = "hex"
    elif not f and op in ("url", "percent"):
        f = "url"
    fam = ("base64" if f in ("base64", "b64", "base 64") else
           "hex" if f in ("hex", "hexadecimal") else
           "url" if f in ("url", "percent") else "")
    if fam and d in ("encode", "decode"):
        return f"{fam}_{d}"
    return None


# ---- the six operations ----------------------------------------------------

def _do_base64_encode(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _do_base64_decode(text: str) -> bytes:
    # Be forgiving: strip whitespace, accept URL-safe (-/_) blobs, and repair
    # missing '=' padding. Validate strictly enough to reject real garbage.
    s = "".join(text.split())
    s = s.replace("-", "+").replace("_", "/")
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.b64decode(s, validate=True)


def _do_hex_encode(text: str) -> str:
    return text.encode("utf-8").hex()


def _do_hex_decode(text: str) -> bytes:
    # tolerate common separators/prefixes: "0x", spaces, colons, newlines
    s = "".join(text.split()).lower()
    if s.startswith("0x"):
        s = s[2:]
    for sep in (":", ",", ";"):
        s = s.replace(sep, "")
    return bytes.fromhex(s)


def _do_url_encode(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def _do_url_decode(text: str) -> str:
    return urllib.parse.unquote(text)


def _bytes_to_ascii(raw: bytes) -> tuple[str, bool]:
    """Render decoded bytes as readable pure ASCII. Returns (text, looks_binary).
    Undecodable/odd bytes become replacement marks; if there are many, the caller
    warns the user the source was probably binary, not text."""
    text = raw.decode("utf-8", "replace")
    binaryish = text.count("�")
    # also count raw control bytes (excluding tab/newline/carriage-return)
    ctrl = sum(1 for b in raw if b < 32 and b not in (9, 10, 13))
    looks_binary = (binaryish + ctrl) > max(4, len(raw) // 20)
    return document._ascii_body(text), looks_binary


@tool(
    "encode_text",
    "Encode or decode a piece of text using Base64, hexadecimal, or URL "
    "(percent) encoding -- exactly, and entirely on this PC (nothing is sent "
    "anywhere). Use when the user says things like 'decode this base64', "
    "'base64 encode this', 'convert this to hex', 'decode this hex', 'url encode "
    "this', or 'url decode hello%20world'. Pass operation as one of: "
    "base64_encode, base64_decode, hex_encode, hex_decode, url_encode, "
    "url_decode (plain phrasing like 'decode base64' or 'to hex' is understood "
    "too), and text as the string to transform. Never work the encoding out "
    "yourself -- your own guess is wrong; this is exact.",
    {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "What to do: base64_encode, base64_decode, "
                "hex_encode, hex_decode, url_encode, or url_decode.",
            },
            "text": {
                "type": "string",
                "description": "The text to encode or decode.",
            },
        },
        "required": ["operation", "text"],
    },
)
def encode_text(operation=None, text=None, format=None, direction=None,
                **extra) -> str:
    # --- pull the text out of whatever field the model used ------------------
    if not isinstance(text, str) or not text:
        for alt in ("text", "content", "string", "data", "input", "value",
                    "message", "s"):
            v = extra.get(alt)
            if isinstance(v, str) and v:
                text = v
                break
    if text is None:
        text = ""
    elif not isinstance(text, str):
        # coerce a stray non-string (number, bool, list) rather than crashing
        text = str(text)
    if not text.strip():
        return ("Sorry sir, there was no text to work with. Tell me the text "
                "to encode or decode (for example: decode this base64 aGVsbG8=).")

    if len(text) > MAX_TEXT:
        return (f"Sorry sir, that text is too large to encode or decode safely "
                f"(over {MAX_TEXT:,} characters). Try a smaller piece.")

    # --- work out which of the six operations was asked for ------------------
    if operation is None:
        operation = extra.get("op") or extra.get("mode") or extra.get("kind")
    if direction is None:
        direction = extra.get("way")
    if format is None:
        format = extra.get("fmt") or extra.get("encoding") or extra.get("scheme")
    op = _resolve_op(operation, format, direction)
    if op not in _OPS:
        return ("Sorry sir, I wasn't sure which encoding you meant. I can do: "
                "base64_encode, base64_decode, hex_encode, hex_decode, "
                "url_encode, url_decode. For example: "
                "operation='base64_decode', text='aGVsbG8='.")

    # --- run it, turning every failure into a friendly message ---------------
    try:
        if op == "base64_encode":
            return _do_base64_encode(text)
        if op == "hex_encode":
            return _do_hex_encode(text)
        if op == "url_encode":
            return _do_url_encode(text)
        if op == "url_decode":
            # url decoding always yields text; force it to readable ASCII
            return document._ascii_body(_do_url_decode(text))
        # the two byte-producing decoders
        raw = _do_base64_decode(text) if op == "base64_decode" \
            else _do_hex_decode(text)
    except (binascii.Error, ValueError):
        what = "Base64" if op == "base64_decode" else "hexadecimal"
        return (f"Sorry sir, that doesn't look like valid {what} text, so I "
                "couldn't decode it. Please double-check what you pasted.")
    except Exception as e:  # last-resort guard: never crash the agent
        return f"Sorry sir, I couldn't complete that ({e})."

    body, looks_binary = _bytes_to_ascii(raw)
    if not body:
        return ("That decoded to no readable text, sir -- it may have been "
                "binary data (an image or a file) rather than text.")
    if looks_binary:
        return ("That decoded to what looks like binary data rather than plain "
                "text, sir; here is a readable view of it:\n" + body)
    return body
