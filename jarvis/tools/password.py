"""Generate a strong, random password for Jarvis -- fully local and private.

A real everyday productivity / safe-automation win, and one that is squarely
on-brand for a "local - private - yours" assistant: instead of the user going
to some website (which sees, and may log, the password it hands back), Jarvis
mints a strong random password right here on the machine and it never leaves.
The user can say "generate a password", "make me a 20 character password",
"give me a password with no symbols", "create 5 passwords" and then "copy that"
(``set_clipboard``) to paste it wherever it's needed.

The randomness comes from ``secrets`` (the cryptographically-strong source the
standard library provides for exactly this), so it is pure standard library
with NO new dependency, and nothing is ever stored.

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or an absurd length):

- **Bounded.** ``length`` is coerced and clamped to a sane range
  (``MIN_LEN``..``MAX_LEN``) so a hallucinated ``length=1e9`` can't hang or
  exhaust memory, and ``count`` is clamped to ``MAX_COUNT`` so it can't be
  asked for a million passwords at once.
- **At least one of each requested class.** When it fits, the password is
  guaranteed to contain a character from every enabled class (lower/upper/
  digits/symbols), so it actually meets typical strength rules.
- **Never all-empty.** If the model turns every class off, we fall back to a
  sensible default set rather than failing or looping forever.
- **Pure ASCII out** by construction (every character comes from an ASCII
  pool), so it can never corrupt the console/context.
- **Never raises, never persists.** Wrong-type / empty / missing args are
  coerced or defaulted; the password is returned and immediately forgotten.
"""

import secrets

from .registry import tool

MIN_LEN = 4       # anything shorter isn't a password worth the name
MAX_LEN = 128     # plenty; keeps output bounded
DEFAULT_LEN = 16
MAX_COUNT = 20    # most passwords we'll mint in one call

# Character pools. Ambiguous look-alikes (0/O, 1/l/I, o) are dropped from the
# base pools when avoid_ambiguous is on (the default) so a human can read the
# password back without guessing.
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DIGITS = "0123456789"
# a curated symbol set: no space, quotes, backslash or backtick (they trip up
# shells, CSVs and copy/paste), just widely-accepted punctuation.
_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?"
_AMBIGUOUS = set("O0oIl1")


def _as_int(value, default: int) -> int:
    """Coerce a model-supplied value to an int, or fall back to default."""
    if isinstance(value, bool):        # True/False must not read as 1/0 here
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(value)
        except (ValueError, OverflowError):
            return default
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        # pull the leading integer out of things like "20 characters"
        neg = s.startswith("-")
        digits = "".join(c for c in s if c.isdigit())
        if not digits:
            return default
        try:
            n = int(digits)
        except ValueError:
            return default
        return -n if neg else n
    return default


_TRUE = {"1", "true", "yes", "y", "on", "with", "include", "t"}
_FALSE = {"0", "false", "no", "n", "off", "without", "none", "exclude", "f"}


def _as_bool(value, default: bool) -> bool:
    """Coerce a model-supplied value to a bool, or fall back to default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    return default


def _pool(chars: str, avoid_ambiguous: bool) -> str:
    """A character pool, minus ambiguous look-alikes when asked."""
    if not avoid_ambiguous:
        return chars
    return "".join(c for c in chars if c not in _AMBIGUOUS)


def _one_password(length: int, pools: list[str]) -> str:
    """Build a single password: one char guaranteed from each pool (when it
    fits), the rest drawn from the combined pool, then securely shuffled."""
    combined = "".join(pools)
    chars: list[str] = []
    # guarantee one of each class only if there's room for all of them
    if length >= len(pools):
        chars.extend(secrets.choice(p) for p in pools)
    while len(chars) < length:
        chars.append(secrets.choice(combined))
    # cryptographically-strong in-place shuffle (Fisher-Yates via secrets)
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


@tool(
    "generate_password",
    "Generate a strong random password locally (it never leaves this PC and is "
    "not stored). Use when the user asks for a password ('generate a password', "
    "'make me a 20 character password', 'a password with no symbols', 'create 5 "
    "passwords'). Options: length (default 16), whether to include symbols, "
    "digits, uppercase and lowercase, avoid_ambiguous look-alike characters "
    "(0/O, 1/l/I; on by default), and count (how many to make). Tell the user "
    "they can say 'copy that' to put it on the clipboard.",
    {
        "type": "object",
        "properties": {
            "length": {
                "type": "integer",
                "description": "How many characters long (default 16, 4-128).",
            },
            "symbols": {
                "type": "boolean",
                "description": "Include punctuation like !@#$ (default true).",
            },
            "digits": {
                "type": "boolean",
                "description": "Include digits 0-9 (default true).",
            },
            "uppercase": {
                "type": "boolean",
                "description": "Include uppercase letters (default true).",
            },
            "lowercase": {
                "type": "boolean",
                "description": "Include lowercase letters (default true).",
            },
            "avoid_ambiguous": {
                "type": "boolean",
                "description": "Leave out look-alike characters 0/O/1/l/I "
                "(default true, so it's easy to read back).",
            },
            "count": {
                "type": "integer",
                "description": "How many passwords to generate (default 1, max 20).",
            },
        },
        "required": [],
    },
)
def generate_password(length=DEFAULT_LEN, symbols=True, digits=True,
                      uppercase=True, lowercase=True, avoid_ambiguous=True,
                      count=1, **extra) -> str:
    # --- coerce + bound every argument (never trust the 8B) ------------------
    length = _as_int(length, DEFAULT_LEN)
    if length < MIN_LEN:
        length = MIN_LEN
    elif length > MAX_LEN:
        length = MAX_LEN

    count = _as_int(count, 1)
    # a model may put the count under alt names
    if count == 1:
        for alt in ("count", "n", "number", "amount", "how_many", "quantity"):
            if alt in extra:
                count = _as_int(extra[alt], 1)
                break
    if count < 1:
        count = 1
    elif count > MAX_COUNT:
        count = MAX_COUNT

    symbols = _as_bool(symbols, True)
    digits = _as_bool(digits, True)
    uppercase = _as_bool(uppercase, True)
    lowercase = _as_bool(lowercase, True)
    avoid_ambiguous = _as_bool(avoid_ambiguous, True)

    # --- assemble the requested character pools ------------------------------
    pools: list[str] = []
    if lowercase:
        pools.append(_pool(_LOWER, avoid_ambiguous))
    if uppercase:
        pools.append(_pool(_UPPER, avoid_ambiguous))
    if digits:
        pools.append(_pool(_DIGITS, avoid_ambiguous))
    if symbols:
        pools.append(_SYMBOLS)

    fallback = ""
    # every class turned off (or a pool emptied by avoid_ambiguous) -> fall
    # back to a strong readable default rather than failing
    pools = [p for p in pools if p]
    if not pools:
        pools = [_pool(_LOWER, True), _pool(_UPPER, True),
                 _pool(_DIGITS, True), _SYMBOLS]
        fallback = (" (you turned every character type off, so I used a "
                    "strong default set)")

    try:
        passwords = [_one_password(length, pools) for _ in range(count)]
    except Exception as e:  # last-resort guard: never crash the agent
        return f"Sorry sir, I couldn't generate a password ({e})."

    # Password(s) go on their OWN line(s), so the value is never tangled up
    # with the surrounding sentence (and it reads cleanly in the console).
    note = f"\n{fallback.strip()}" if fallback else ""
    if count == 1:
        return (f"Here's a {length}-character password, sir:\n"
                f"{passwords[0]}{note}\n"
                "You can say 'copy that' to put it on your clipboard.")
    body = "\n".join(f"  {i}. {pw}" for i, pw in enumerate(passwords, 1))
    return (f"Here are {count} {length}-character passwords, sir:{note}\n"
            f"{body}\n"
            "Say 'copy the first one' to put it on your clipboard.")
