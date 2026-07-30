"""Unit / measurement converter for Jarvis.

An 8B local model is unreliable at unit conversions - ask it "how many km is 5
miles", "convert 32 F to C", or "how many ml in a cup" and it will confidently
give a wrong number. This gives Jarvis a real, exact converter so it can answer
everyday "convert X to Y" questions instead of guessing. It rounds out the
"exact computation" family alongside ``calculate`` (numbers) and the date tools
(the calendar), with the same promise: exact answers, never a crash.

Supported categories: length, mass, volume, temperature, time, speed, area and
data. Pure standard library (no new dependency); conversions are simple factor
maths (to/from a base unit per category), with temperature handled specially
because it is an affine (offset) scale, not a plain ratio.

Safety model (strict, because the 8B model WILL eventually pass junk):

- **Unknown units are refused, not guessed.** Every unit is resolved against an
  allowlist of names/symbols/aliases; an unrecognised unit comes back as a
  friendly message, never a wrong answer.
- **Cross-category conversions are refused.** "miles to kilograms" is rejected
  with a clear note rather than producing nonsense.
- **Sizes are bounded.** The value's magnitude is capped (so a hallucinated
  ``1e400``/non-finite value can't overflow), and the unit/phrase strings are
  length-limited.
- **Forgiving input.** Wrong-type args are coerced; the model may pass the
  units under ``from``/``to`` instead of ``from_unit``/``to_unit``, or dump a
  whole phrase like "5 miles to km" into one field - both are handled.
- **Never raises.** Every bad input returns a plain, pure-ASCII message the
  model can read and recover from.
"""

import math
import re

from .registry import tool

MAX_MAGNITUDE = 1e18   # refuse absurd/overflowing values (1e400, inf, ...)
MAX_UNIT_LEN = 40      # a unit name, not a paragraph
MAX_PHRASE_LEN = 120   # a "5 miles to km" phrase, not an essay

# --------------------------------------------------------------------------
# Unit tables. Each linear unit maps to (category, factor-to-base-unit).
# Base units: length=metre, mass=gram, volume=litre, time=second,
# speed=metre/second, area=square-metre, data=byte. Temperature is special
# (handled via Celsius) and lives in _TEMP, not here.
#
# _GROUPS is (category, canonical-symbol, factor, [aliases]); it is expanded
# below into the fast lookup tables _INDEX (canonical -> (cat, factor)) and
# _ALIASES (any spelling -> canonical). Regular plurals are handled by a
# trailing-'s' fallback at lookup time, so only irregular plurals (feet,
# inches, ...) need to be listed explicitly.
# --------------------------------------------------------------------------
_GROUPS = [
    # length (base: metre)
    ("length", "m", 1.0, ["meter", "metre", "metres"]),
    ("length", "km", 1000.0, ["kilometer", "kilometre", "klick"]),
    ("length", "cm", 0.01, ["centimeter", "centimetre"]),
    ("length", "mm", 0.001, ["millimeter", "millimetre"]),
    ("length", "um", 1e-6, ["micrometer", "micron"]),
    ("length", "nm", 1e-9, ["nanometer"]),
    ("length", "mi", 1609.344, ["mile"]),
    ("length", "yd", 0.9144, ["yard"]),
    ("length", "ft", 0.3048, ["foot", "feet"]),
    ("length", "in", 0.0254, ["inch", "inches"]),
    ("length", "nmi", 1852.0, ["nautical mile"]),
    # mass (base: gram)
    ("mass", "g", 1.0, ["gram", "gramme"]),
    ("mass", "kg", 1000.0, ["kilogram", "kilo"]),
    ("mass", "mg", 0.001, ["milligram"]),
    ("mass", "ug", 1e-6, ["microgram"]),
    ("mass", "t", 1e6, ["tonne", "ton", "metric ton", "metric tonne"]),
    ("mass", "lb", 453.59237, ["pound", "lbs"]),
    ("mass", "oz", 28.349523125, ["ounce"]),
    ("mass", "st", 6350.29318, ["stone"]),
    # volume (base: litre)
    ("volume", "l", 1.0, ["liter", "litre"]),
    ("volume", "ml", 0.001, ["milliliter", "millilitre"]),
    ("volume", "cl", 0.01, ["centiliter", "centilitre"]),
    ("volume", "dl", 0.1, ["deciliter", "decilitre"]),
    ("volume", "m3", 1000.0, ["cubic meter", "cubic metre", "cubic meters"]),
    ("volume", "cm3", 0.001, ["cubic centimeter", "cc"]),
    ("volume", "gal", 3.785411784, ["gallon", "us gallon"]),
    ("volume", "qt", 0.946352946, ["quart"]),
    ("volume", "pt", 0.473176473, ["pint"]),
    ("volume", "cup", 0.2365882365, ["cups"]),
    ("volume", "floz", 0.0295735295625, ["fluid ounce", "fl oz"]),
    ("volume", "tbsp", 0.01478676478125, ["tablespoon"]),
    ("volume", "tsp", 0.00492892159375, ["teaspoon"]),
    # time (base: second)
    ("time", "s", 1.0, ["sec", "second", "secs"]),
    ("time", "ms", 0.001, ["millisecond"]),
    ("time", "min", 60.0, ["minute", "mins"]),
    ("time", "h", 3600.0, ["hr", "hour", "hrs"]),
    ("time", "day", 86400.0, ["days"]),
    ("time", "week", 604800.0, ["wk", "weeks"]),
    # speed (base: metre/second)
    ("speed", "mps", 1.0, ["m/s", "meters per second", "metres per second"]),
    ("speed", "kmh", 1000.0 / 3600.0, ["km/h", "kph", "kmph",
                                       "kilometers per hour", "km per hour"]),
    ("speed", "mph", 0.44704, ["mi/h", "miles per hour"]),
    ("speed", "knot", 1852.0 / 3600.0, ["knots", "kn"]),
    ("speed", "fps", 0.3048, ["ft/s", "feet per second"]),
    # area (base: square metre)
    ("area", "m2", 1.0, ["square meter", "square metre", "sqm", "sq m"]),
    ("area", "km2", 1e6, ["square kilometer", "sq km"]),
    ("area", "cm2", 1e-4, ["square centimeter"]),
    ("area", "mm2", 1e-6, ["square millimeter"]),
    ("area", "ha", 1e4, ["hectare"]),
    ("area", "acre", 4046.8564224, ["acres"]),
    ("area", "ft2", 0.09290304, ["square foot", "square feet", "sq ft"]),
    ("area", "in2", 0.00064516, ["square inch"]),
    ("area", "mi2", 2589988.110336, ["square mile"]),
    ("area", "yd2", 0.83612736, ["square yard"]),
    # data (base: byte; decimal kB/MB and binary KiB/MiB both offered)
    ("data", "b", 1.0, ["byte", "bytes"]),
    ("data", "bit", 0.125, ["bits"]),
    ("data", "kb", 1e3, ["kilobyte"]),
    ("data", "mb", 1e6, ["megabyte"]),
    ("data", "gb", 1e9, ["gigabyte"]),
    ("data", "tb", 1e12, ["terabyte"]),
    ("data", "kib", 1024.0, ["kibibyte"]),
    ("data", "mib", 1024.0 ** 2, ["mebibyte"]),
    ("data", "gib", 1024.0 ** 3, ["gibibyte"]),
    ("data", "tib", 1024.0 ** 4, ["tebibyte"]),
]

_INDEX: dict[str, tuple[str, float]] = {}
_ALIASES: dict[str, str] = {}
for _cat, _sym, _factor, _aliases in _GROUPS:
    _INDEX[_sym] = (_cat, _factor)
    _ALIASES[_sym] = _sym
    for _a in _aliases:
        _ALIASES[_a] = _sym

# temperature: canonical -> display symbol. Handled via Celsius, not a factor.
_TEMP = {"c", "f", "k"}
_TEMP_ALIASES = {
    "c": "c", "celsius": "c", "centigrade": "c", "degc": "c",
    "f": "f", "fahrenheit": "f", "degf": "f",
    "k": "k", "kelvin": "k",
}
_ALIASES.update(_TEMP_ALIASES)

_DISP = {"c": "C", "f": "F", "k": "K"}  # nicer display for temperature
_CATEGORY_NAMES = {
    "length": "length", "mass": "mass", "volume": "volume",
    "temperature": "temperature", "time": "time", "speed": "speed",
    "area": "area", "data": "data",
}

_PHRASE_RE = re.compile(
    r"^\s*(?:convert\s+)?(-?\d+(?:\.\d+)?)\s*"
    r"([a-z0-9/^ ]+?)\s+(?:to|into|in|as|=)\s+([a-z0-9/^ ]+?)\s*$"
)


# --------------------------------------------------------------------------
# coercion / parsing helpers -- none of these raise
# --------------------------------------------------------------------------
def _first_str(*values) -> str:
    """First value that is a non-empty string once stripped, else ''."""
    for v in values:
        if isinstance(v, str) and v.strip():
            return v
        if v is not None and not isinstance(v, str):
            s = str(v).strip()
            if s:
                return s
    return ""


def _clean_unit(v) -> str:
    """Any model-supplied unit -> a bounded, lower-case, pure-ASCII token.
    Drops decoration the model adds ('degrees', 'of', stray punctuation, a
    degree symbol) so 'degrees Celsius' resolves to 'celsius'."""
    if v is None:
        s = ""
    elif isinstance(v, str):
        s = v
    else:
        s = str(v)
    s = s.encode("ascii", "ignore").decode("ascii")  # drop degree-sign etc.
    s = s.lower().strip().strip(".").strip("`").strip()
    s = s[:MAX_UNIT_LEN]
    for junk in ("degrees ", "degree ", "deg "):
        if s.startswith(junk):
            s = s[len(junk):]
    s = s.replace("degrees", "").replace("degree", "")
    return " ".join(s.split())


def _to_number(v):
    """Coerce a value to a finite float within bounds.
    Returns (value, ok). Rejects bool, non-finite, absurd magnitude, and any
    string that is not purely numeric (a phrase like '5 miles' is handled
    elsewhere)."""
    if isinstance(v, bool):
        return None, False
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        s = v.strip().strip("`").strip()
        if not s:
            return None, False
        try:
            f = float(s)
        except ValueError:
            return None, False
    else:
        return None, False
    if not math.isfinite(f) or abs(f) > MAX_MAGNITUDE:
        return None, False
    return f, True


def _parse_phrase(v):
    """Recover (number, from_text, to_text) from a single phrase like
    '5 miles to km' or 'convert 60 mph into km/h'. Returns None if it does not
    look like a conversion phrase. Bounded; never raises."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or len(s) > MAX_PHRASE_LEN:
        return None
    m = _PHRASE_RE.match(s.lower())
    if not m:
        return None
    num, ok = _to_number(m.group(1))
    if not ok:
        return None
    return num, m.group(2), m.group(3)


def _resolve(unit_text: str):
    """Resolve a cleaned unit token to a canonical symbol, trying a trailing-'s'
    (plural) fallback. Returns the canonical symbol or None."""
    if not unit_text:
        return None
    key = _ALIASES.get(unit_text)
    if key is None and unit_text.endswith("s") and len(unit_text) > 1:
        key = _ALIASES.get(unit_text[:-1])
    return key


def _to_celsius(value: float, unit: str) -> float:
    if unit == "c":
        return value
    if unit == "f":
        return (value - 32.0) * 5.0 / 9.0
    return value - 273.15  # kelvin


def _from_celsius(celsius: float, unit: str) -> float:
    if unit == "c":
        return celsius
    if unit == "f":
        return celsius * 9.0 / 5.0 + 32.0
    return celsius + 273.15  # kelvin


def _fmt(value: float) -> str:
    """Render a numeric result cleanly (pure ASCII): whole values as ints,
    others trimmed to a sensible precision."""
    if not math.isfinite(value):
        return str(value)
    if abs(value) < 1e16 and float(value).is_integer():
        return str(int(value))
    return f"{round(value, 10):.10g}"


def _disp(canonical: str) -> str:
    return _DISP.get(canonical, canonical)


# --------------------------------------------------------------------------
# the tool exposed to the model
# --------------------------------------------------------------------------
@tool(
    "convert_units",
    "Convert a measurement from one unit to another and return the exact "
    "result. USE this for ANY unit conversion instead of working it out "
    "yourself, because it is always exact. Supports length (m, km, mi, ft, in), "
    "mass (g, kg, lb, oz), volume (l, ml, gal, cup), temperature (C, F, K), "
    "time (s, min, h, day), speed (kmh, mph, knot), area and data (kb, mb, gb). "
    "Give value (a number), from_unit and to_unit, e.g. value=5, from_unit='mi', "
    "to_unit='km'.",
    {
        "type": "object",
        "properties": {
            "value": {"type": "number",
                      "description": "The amount to convert, e.g. 5"},
            "from_unit": {"type": "string",
                          "description": "The unit to convert FROM, e.g. 'miles' or 'C'"},
            "to_unit": {"type": "string",
                        "description": "The unit to convert TO, e.g. 'km' or 'F'"},
        },
        "required": ["value", "from_unit", "to_unit"],
    },
)
def convert_units(value=None, from_unit="", to_unit="", **extra) -> str:
    # the model sometimes uses 'from'/'to' (or dumps everything in one field);
    # accept those spellings too rather than dead-ending the call.
    from_unit = _first_str(from_unit, extra.get("from"), extra.get("unit_from"),
                           extra.get("source"), extra.get("units_from"))
    to_unit = _first_str(to_unit, extra.get("to"), extra.get("unit_to"),
                         extra.get("target"), extra.get("units_to"))

    num, num_ok = _to_number(value)
    fu = _clean_unit(from_unit)
    tu = _clean_unit(to_unit)

    # fallback: a whole phrase ("5 miles to km") may have landed in any field.
    if not (num_ok and fu and tu):
        for cand in (value, from_unit, to_unit):
            parsed = _parse_phrase(cand)
            if parsed:
                pnum, pf, pt = parsed
                if not num_ok:
                    num, num_ok = pnum, True
                fu = fu or _clean_unit(pf)
                tu = tu or _clean_unit(pt)
                break

    if not num_ok:
        return "Error: give me a number to convert, sir (its value may be out of range)."
    if not fu or not tu:
        return ("Error: tell me both units, sir -- e.g. convert 5 miles to km.")

    from_c = _resolve(fu)
    to_c = _resolve(tu)
    if from_c is None:
        return f'Error: I do not know the unit "{fu}", sir.'
    if to_c is None:
        return f'Error: I do not know the unit "{tu}", sir.'

    from_temp = from_c in _TEMP
    to_temp = to_c in _TEMP

    # temperature is its own (affine) world; it can't mix with linear units.
    if from_temp != to_temp:
        a = "temperature" if from_temp else _INDEX[from_c][0]
        b = "temperature" if to_temp else _INDEX[to_c][0]
        return (f"Error: I can't convert {a} to {b} "
                f"({_disp(from_c)} to {_disp(to_c)}), sir.")

    if from_temp and to_temp:
        result = _from_celsius(_to_celsius(num, from_c), to_c)
        return (f"{_fmt(num)} {_disp(from_c)} = {_fmt(result)} "
                f"{_disp(to_c)}, sir.")

    cat_a, factor_a = _INDEX[from_c]
    cat_b, factor_b = _INDEX[to_c]
    if cat_a != cat_b:
        return (f"Error: I can't convert {_CATEGORY_NAMES.get(cat_a, cat_a)} to "
                f"{_CATEGORY_NAMES.get(cat_b, cat_b)} "
                f"({_disp(from_c)} to {_disp(to_c)}), sir.")

    result = num * factor_a / factor_b
    if not math.isfinite(result):
        return "Error: that conversion is out of range, sir."
    return f"{_fmt(num)} {_disp(from_c)} = {_fmt(result)} {_disp(to_c)}, sir."
