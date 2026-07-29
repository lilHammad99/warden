"""Headed browser controlled by the agent.

Playwright sync objects only work on the thread that created them, and tool
calls can come from the console or voice thread — so a single controller
thread owns the browser and executes queued actions.
"""

import queue
import re
import threading

from .registry import tool


class _BrowserThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="browser")
        self.q: queue.Queue = queue.Queue()
        self.started = threading.Event()
        self.error = None
        self.page = None

    def run(self):
        try:
            from playwright.sync_api import sync_playwright

            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=False)
            self.page = browser.new_page(viewport={"width": 1280, "height": 800})
        except Exception as e:
            self.error = e
            self.started.set()
            return
        self.started.set()
        while True:
            fn, result = self.q.get()
            if fn is None:
                break
            try:
                result["value"] = fn(self.page)
            except Exception as e:
                result["value"] = f"Browser error: {e}"
            result["done"].set()
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass


_controller: _BrowserThread | None = None
_lock = threading.Lock()


def _run(fn) -> str:
    global _controller
    with _lock:
        if _controller is None or not _controller.is_alive():
            _controller = _BrowserThread()
            _controller.start()
            _controller.started.wait(timeout=60)
            if _controller.error:
                err = _controller.error
                _controller = None
                return (f"Could not start the browser: {err}. "
                        f"Run 'playwright install chromium' if it is missing.")
    result = {"done": threading.Event(), "value": None}
    _controller.q.put((fn, result))
    if not result["done"].wait(timeout=90):
        return "Browser action timed out."
    return str(result["value"])


def shutdown():
    global _controller
    if _controller and _controller.is_alive():
        _controller.q.put((None, None))
    _controller = None


def _page_digest(page) -> str:
    title = page.title()
    url = page.url
    body = page.inner_text("body", timeout=5000)
    body = re.sub(r"\n{2,}", "\n", body).strip()
    if len(body) > 4000:
        body = body[:4000] + " ...[truncated]"
    links = page.eval_on_selector_all(
        "a[href], button, input[type=submit]",
        "els => els.slice(0, 40).map(e => (e.innerText || e.value || '').trim())"
        ".filter(t => t && t.length < 80)",
    )
    clickable = ", ".join(f"'{t}'" for t in dict.fromkeys(links))
    return (f"Page: {title}\nURL: {url}\n\nText:\n{body}\n\n"
            f"Clickable items: {clickable}")


@tool(
    "browser_open",
    "Open a URL in Jarvis's own visible browser window (which you control) "
    "and return the page content. Use this browser when the user wants you "
    "to browse, search, or interact with a website yourself.",
    {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
)
def browser_open(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    def act(page):
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        return _page_digest(page)
    return _run(act)


@tool(
    "browser_read",
    "Re-read the current page in Jarvis's browser (title, text, clickable items).",
)
def browser_read() -> str:
    return _run(_page_digest)


@tool(
    "browser_click",
    "Click a link or button in Jarvis's browser by its visible text "
    "(pick one from 'Clickable items').",
    {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Visible text of the element"}},
        "required": ["text"],
    },
)
def browser_click(text: str) -> str:
    def act(page):
        el = page.get_by_text(text, exact=False).first
        el.click(timeout=8000)
        page.wait_for_timeout(1500)
        return _page_digest(page)
    return _run(act)


@tool(
    "browser_type",
    "Type into an input field in Jarvis's browser and press Enter. "
    "Identify the field by its placeholder/label/name (e.g. 'Search').",
    {
        "type": "object",
        "properties": {
            "field": {"type": "string", "description": "Placeholder, label or name of the input"},
            "text": {"type": "string", "description": "Text to type"},
        },
        "required": ["field", "text"],
    },
)
def browser_type(field: str, text: str) -> str:
    def act(page):
        sel = (f"input[placeholder*='{field}' i], textarea[placeholder*='{field}' i], "
               f"input[name*='{field}' i], input[aria-label*='{field}' i], "
               f"textarea[aria-label*='{field}' i], input[title*='{field}' i], "
               f"textarea[title*='{field}' i]")
        el = page.locator(sel).first
        try:
            el.fill(text, timeout=5000)
        except Exception:
            el = page.locator("input:visible, textarea:visible").first
            el.fill(text, timeout=5000)
        el.press("Enter")
        page.wait_for_timeout(2000)
        return _page_digest(page)
    return _run(act)


@tool(
    "browser_back",
    "Go back one page in Jarvis's browser.",
)
def browser_back() -> str:
    def act(page):
        page.go_back(wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1000)
        return _page_digest(page)
    return _run(act)


@tool(
    "browser_close",
    "Close Jarvis's browser window.",
)
def browser_close() -> str:
    shutdown()
    return "Browser closed."
