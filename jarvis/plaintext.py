"""Normalise a reply into plain, speakable text.

The local model typesets maths in LaTeX even when the mind forbids markdown --
it does not consider TeX to be markdown -- so answers come back as
``The calculation $ \\frac{15}{100} \\times 240 $ results in 36.`` Every reply
is read aloud, where that is unintelligible, and it looks wrong in the console
too. This turns the TeX into prose: ``The calculation 15/100 times 240 results
in 36.``

Deliberately conservative, because this app talks about the user's files
constantly:

- A backslash is NOT evidence of TeX. ``C:\\times\\fraction\\left.txt`` is a
  perfectly ordinary Windows path and must survive untouched, so commands are
  only translated INSIDE a recognised math span.
- A lone dollar sign is money. ``$`` pairs are only treated as delimiters when
  what sits between them actually looks like maths.
- Underscores are file names (``my_budget_2026.xlsx``), not emphasis, so they
  are left alone. Only paired ``**bold**`` is unwrapped.

Never raises; anything that is not a string comes back as one.
"""

import re

# Translated only inside a math span. Longest first, so \leq wins over \le and
# \left is consumed before \le could match it.
_COMMANDS = [
    (re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}"), r"\1/\2"),
    (re.compile(r"\\sqrt\s*\{([^{}]*)\}"), r"square root of \1"),
    (re.compile(r"\\left|\\right"), ""),
    (re.compile(r"\\times|\\cdot"), " times "),
    (re.compile(r"\\div"), " divided by "),
    (re.compile(r"\\approx"), " approximately "),
    (re.compile(r"\\neq"), " != "),
    (re.compile(r"\\leq|\\le\b"), " <= "),
    (re.compile(r"\\geq|\\ge\b"), " >= "),
    (re.compile(r"\\pm"), " plus or minus "),
    (re.compile(r"\\pi\b"), "pi"),
    (re.compile(r"\\%"), "%"),
    (re.compile(r"\\[,;!]|\\ "), " "),
]

# What makes the text between two dollar signs maths rather than two prices.
_MATHS = re.compile(r"\\[A-Za-z]|[\^{}]|_\{")

_SUPERSUB = re.compile(r"([\^_])\{([^{}]*)\}")
_LEFTOVER_CMD = re.compile(r"\\([A-Za-z]+)")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_SPACES = re.compile(r"[ \t]{2,}")


def _render(inner: str) -> str:
    """Turn the contents of one math span into prose."""
    for pattern, replacement in _COMMANDS:
        inner = pattern.sub(replacement, inner)
    inner = _SUPERSUB.sub(r"\1\2", inner)      # 2^{10} -> 2^10
    inner = _LEFTOVER_CMD.sub(r"\1", inner)    # \alpha -> alpha
    inner = inner.replace("{", "").replace("}", "")
    return _SPACES.sub(" ", inner).strip()


def _dollar_span(match: re.Match) -> str:
    inner = match.group(1)
    if not _MATHS.search(inner):
        return match.group(0)                  # prices, not maths -- leave it
    return _render(inner)


def to_plain(text) -> str:
    """Return `text` with LaTeX and bold markdown reduced to plain prose."""
    try:
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        # unambiguous TeX delimiters first: \[ ... \] and \( ... \)
        text = re.sub(r"\\\[(.+?)\\\]", lambda m: _render(m.group(1)), text, flags=re.S)
        text = re.sub(r"\\\((.+?)\\\)", lambda m: _render(m.group(1)), text, flags=re.S)
        # then $$ ... $$ and $ ... $, but only where the contents look like maths
        text = re.sub(r"\$\$([^$]*)\$\$", _dollar_span, text)
        text = re.sub(r"\$([^$]*)\$", _dollar_span, text)
        text = _BOLD.sub(r"\1", text)
        return _SPACES.sub(" ", text).strip()
    except Exception:
        return str(text) if text is not None else ""
