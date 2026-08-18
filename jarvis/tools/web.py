"""Web tools for Jarvis: search the web, and fetch a page as readable text.

``web_search`` returns a short list of results (title/link/snippet).
``web_fetch`` is the tool that actually reaches OUTSIDE this machine: it does a
plain HTTP(S) GET of one URL and returns the page's readable text (HTML stripped
to text), so Jarvis can read documentation, an article, or a result found by
web_search.

This is the ONE tool that opens a network connection to an arbitrary address,
so it is guarded like a network tool, not a file tool, because an 8B local
model WILL eventually be handed a hostile or foolish URL:

- **http/https only.** Any other scheme (file://, ftp://, gopher://, data:...) is
  refused, so it can never be tricked into reading a local file off the disk.
- **No private / local targets (SSRF guard).** The host is resolved to its IP
  address(es) and the fetch is REFUSED if any of them is loopback, private
  (RFC1918), link-local (169.254 / fe80::), unique-local, multicast, reserved or
  unspecified. That blocks ``localhost``, ``127.0.0.1``, ``[::1]``, ``10.x``,
  ``192.168.x``, ``169.254.x`` and a router's admin page -- the classic ways a
  fetch tool gets turned against the machine it runs on.
- **Redirects are capped AND re-checked.** Redirects are followed manually up to
  a small limit, and every hop is re-validated against the SSRF guard, so a
  public URL can't 302 its way to ``http://127.0.0.1/...``.
- **Bounded download + time.** The body is streamed and hard-capped in bytes, a
  connect/read timeout applies, and only text-like content types are rendered
  (a binary type is reported, not dumped). The returned text is length-capped.
- **Never raises.** A bad URL, a DNS failure, a timeout, a dead host or any
  unexpected error comes back as a friendly string the model can read and
  recover from.

Pure standard library (urllib + html.parser + socket + ipaddress) -- no new
dependency. (web_search still uses the already-present ddgs package.)
"""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .find import _coerce
from .registry import tool

MAX_URL_LEN = 2000
TIMEOUT = 15.0              # connect/read timeout (seconds)
MAX_BYTES = 2_000_000       # hard cap on bytes downloaded (2 MB)
MAX_REDIRECTS = 5           # most redirect hops followed
MAX_TEXT_CHARS = 6000       # readable text returned to the model
CHUNK = 65536

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/1.0"
_ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5"

# content types we will render as text; anything else (image/*, video/*,
# application/pdf, application/octet-stream, ...) is reported, not dumped.
_TEXT_TYPES = (
    "text/", "application/xhtml", "application/xml", "text/xml",
    "application/json", "application/javascript", "application/rss",
    "application/atom",
)


class _NoRedirect(HTTPRedirectHandler):
    """Return the 3xx response instead of auto-following it, so we can follow
    redirects ourselves and re-check each hop against the SSRF guard."""

    def _keep(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = _keep
    http_error_302 = _keep
    http_error_303 = _keep
    http_error_307 = _keep
    http_error_308 = _keep


_OPENER = build_opener(_NoRedirect())


class _TextExtractor(HTMLParser):
    """Collect the human-readable text of an HTML page.

    Content inside script/style/head-noise tags is dropped; block-level tags
    become line breaks so paragraphs and list items don't run together. The
    first <title> is captured separately."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK = {
        "p", "br", "div", "li", "tr", "section", "article", "header", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote",
        "pre", "hr", "nav", "aside", "figure", "form",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip:
            self.parts.append(data)


def _clean_text(text: str) -> str:
    """Tidy extracted text: drop control chars, collapse runs of spaces, and
    fold blank lines, keeping paragraph structure but bounding the length."""
    text = text.replace("\r", "\n")
    text = "".join(c for c in text if c == "\n" or c >= " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rstrip() + " ...[truncated]"
    return text


def _charset(content_type: str) -> str:
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.IGNORECASE)
    return m.group(1) if m else "utf-8"


def _is_text_type(content_type: str) -> bool:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if not ct:
        return True  # no header: assume text and let extraction handle it
    return ct.startswith(_TEXT_TYPES)


def _ip_blocked(ip: str) -> bool:
    """Is this resolved IP a local/private/otherwise-non-public address?"""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return True  # can't parse it -> refuse, don't guess
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (addr.is_loopback or addr.is_private or addr.is_link_local
            or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def _host_status(host: str) -> str:
    """'' if the host resolves only to public addresses; otherwise a reason
    ('blocked' for a private/local target, 'unresolved' if DNS fails)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return "unresolved"
    if not infos:
        return "unresolved"
    for info in infos:
        if _ip_blocked(info[4][0]):
            return "blocked"
    return ""


def _validate(url: str) -> tuple[str, str]:
    """Check scheme + SSRF for one URL. Returns ('', '') if safe to fetch,
    otherwise ('', error_message)."""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return "", ("Error: I can only fetch http:// or https:// web pages, sir "
                    f"-- not '{scheme or url[:40]}'.")
    host = parsed.hostname
    if not host:
        return "", "Error: that doesn't look like a web address, sir."
    status = _host_status(host)
    if status == "blocked":
        return "", ("Error: I won't fetch that address, sir -- it points to a "
                    "local or private-network host (localhost / 127.x / 10.x / "
                    "192.168.x / link-local), which is off limits for safety.")
    if status == "unresolved":
        return "", (f"Error: I couldn't resolve the host '{host}', sir -- check "
                    "the address is spelled right and the site exists.")
    return "", ""


def _render(resp, final_url: str, redirected: bool) -> str:
    """Read the (already-validated) response, bounded, and turn it into text."""
    content_type = resp.headers.get("Content-Type", "")
    if not _is_text_type(content_type):
        ct = content_type.split(";", 1)[0].strip() or "unknown"
        return (f"Fetched {final_url} but it is not a readable text page "
                f"(content type: {ct}), so there's nothing to read out, sir.")

    chunks: list[bytes] = []
    total = 0
    while total <= MAX_BYTES:
        try:
            chunk = resp.read(CHUNK)
        except Exception:
            break
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    truncated = total > MAX_BYTES
    raw = b"".join(chunks)[:MAX_BYTES]
    try:
        resp.close()
    except Exception:
        pass

    body = raw.decode(_charset(content_type), errors="replace")
    ct = content_type.lower()
    title = ""
    if "html" in ct or (not ct and "<html" in body[:2000].lower()):
        parser = _TextExtractor()
        try:
            parser.feed(body)
        except Exception:
            pass
        title = " ".join(parser.title.split())[:200]
        text = _clean_text("".join(parser.parts))
    else:
        text = _clean_text(body)

    if not text:
        return f"Fetched {final_url} but it had no readable text, sir."

    head = final_url
    if title:
        head = f"{title}\n{final_url}"
    if redirected:
        head += " (after redirect)"
    if truncated:
        text += "\n[page was longer; truncated]"
    return f"{head}\n\n{text}"


@tool(
    "web_fetch",
    "Fetch a single web page over http/https and return its readable text (HTML "
    "stripped to plain text). Use this to READ a specific URL -- documentation, "
    "an article, or a promising link from web_search. Give the full address "
    "(e.g. 'https://example.com/page'). Only public websites can be fetched: "
    "local or private-network addresses (localhost, 127.0.0.1, 192.168.x, etc.) "
    "are refused for safety. Use web_search first if you don't have a URL.",
    {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full web address to fetch, e.g. "
                "'https://en.wikipedia.org/wiki/Iron_Man'.",
            },
        },
        "required": ["url"],
    },
)
def web_fetch(url: str = "", **extra) -> str:
    if not url:
        url = extra.get("link") or extra.get("address") or \
            extra.get("page") or extra.get("href") or extra.get("uri") or ""
    url = _coerce(url, MAX_URL_LEN)
    if not url:
        return ("Error: tell me which web address to fetch, sir (a full "
                "http/https URL like 'https://example.com').")
    if "://" not in url and not url.lower().startswith(("http:", "https:")):
        url = "https://" + url  # forgiving: bare 'example.com' -> https://

    current = url
    redirected = False
    for _hop in range(MAX_REDIRECTS + 1):
        _, err = _validate(current)
        if err:
            return err
        req = Request(current, headers={"User-Agent": _UA, "Accept": _ACCEPT})
        try:
            resp = _OPENER.open(req, timeout=TIMEOUT)
        except HTTPError as e:
            return (f"Error: the page returned HTTP {e.code} "
                    f"({getattr(e, 'reason', '')}), sir.")
        except (URLError, socket.timeout, TimeoutError) as e:
            reason = getattr(e, "reason", e)
            return (f"Error: I couldn't reach that page, sir "
                    f"({str(reason)[:120]}). It may be down or the address wrong.")
        except Exception as e:  # last-resort: never crash the agent
            return f"Error while fetching that page, sir: {str(e)[:120]}"

        code = resp.getcode()
        if code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            try:
                resp.close()
            except Exception:
                pass
            if not location:
                return "Error: the page tried to redirect without a destination, sir."
            current = urljoin(current, location)
            redirected = True
            continue
        return _render(resp, current, redirected)

    return (f"Error: that page redirected too many times (more than "
            f"{MAX_REDIRECTS}), sir -- I stopped to avoid a loop.")


@tool(
    "web_search",
    "Search the web and return top results (title, link, snippet). Use for "
    "current events, weather, facts you are unsure about.",
    {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)
def web_search(query: str) -> str:
    from ddgs import DDGS

    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"- {r.get('title')}\n  {r.get('href')}\n  {r.get('body')}")
    return "\n".join(lines)
