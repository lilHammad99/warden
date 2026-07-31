"""Current weather for Jarvis.

`web_search` on "what's the weather" only returns page DESCRIPTIONS ("get
accurate forecasts...") -- never the actual temperature -- so the model had
nothing to tell the user. `get_weather` pulls real, current conditions from
wttr.in, a free, no-API-key weather service that geolocates this PC by its IP
when no city is given. Answers "what's the weather like", "is it going to rain
today", "how hot is it in London".

Offline-degrading and hardened like the other tools: a network failure, an
unknown place, or junk input all come back as a friendly, pure-ASCII string;
never raises.
"""

import re
from urllib.parse import quote

import requests

from .find import _coerce
from .organize import _ascii, _first_str
from .registry import tool

WTTR = "https://wttr.in"
MAX_LOC = 80

# Words a small model dumps into `location` that are NOT a place. If what it
# passes is only these (e.g. "today", "whats the weather like now"), we drop it
# and let wttr.in geolocate this PC by IP instead of resolving junk to some
# random city.
_FILLER = {
    "weather", "forecast", "today", "tonight", "tomorrow", "now", "currently",
    "current", "like", "is", "it", "the", "a", "whats", "what", "hows", "how",
    "going", "to", "be", "my", "area", "here", "outside", "right", "this",
    "rain", "raining", "hot", "cold", "cool", "warm", "temperature", "temp",
    "sunny", "cloudy", "in", "at", "for", "of", "and", "please", "sir", "will",
}


def _clean_location(loc: str) -> str:
    """Keep only the words that look like a place name; drop weather/question
    filler. 'weather in London' -> 'London'; 'today' -> ''."""
    kept = [w for w in loc.split()
            if re.sub(r"[^a-z]", "", w.lower()) not in _FILLER]
    return " ".join(kept).strip()


def _pick(d, *keys):
    """First present, non-empty value for a wttr JSON key (values are often a
    one-item list of {'value': ...})."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            v = v[0].get("value")
        if v not in (None, "", []):
            return v
    return None


@tool(
    "get_weather",
    "Get the CURRENT weather and today's forecast. Use this WHENEVER the user "
    "asks about the weather ('what's the weather like today', 'is it going to "
    "rain', 'how hot is it', 'weather in London') -- NOT web_search, which only "
    "returns page descriptions, not real conditions. Optional location (a city "
    "or place); if omitted it uses this PC's own location.",
    {
        "type": "object",
        "properties": {
            "location": {"type": "string",
                         "description": "City/place, e.g. 'London'. Omit for here."},
        },
        "required": [],
    },
)
def get_weather(location: str = "", **extra) -> str:
    loc = _first_str(location, extra.get("city"), extra.get("place"),
                     extra.get("where"), extra.get("query"))
    loc = _clean_location(_coerce(loc, MAX_LOC))
    path = quote(loc) if loc else ""
    url = f"{WTTR}/{path}?format=j1"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "curl/8"})
    except Exception:
        return ("Error: I couldn't reach the weather service, sir -- check the "
                "internet connection.")
    if r.status_code != 200:
        return (f"Error: I couldn't get the weather for '{_ascii(loc)}', sir; I "
                "may not know that place." if loc else
                "Error: the weather service is unavailable right now, sir.")
    try:
        j = r.json()
        cur = j["current_condition"][0]
        area = j["nearest_area"][0]
        today = (j.get("weather") or [{}])[0]
    except Exception:
        return "Error: the weather service gave me something I couldn't read, sir."

    city = _pick(area, "areaName") or loc or "your area"
    region = _pick(area, "country")
    where = f"{city}, {region}" if region and region != city else str(city)

    desc = _pick(cur, "weatherDesc") or "unclear"
    temp = cur.get("temp_C")
    feels = cur.get("FeelsLikeC")
    hum = cur.get("humidity")
    wind = cur.get("windspeedKmph")
    hi = today.get("maxtempC")
    lo = today.get("mintempC")
    hourly = today.get("hourly") or []
    try:
        rain = max((int(h.get("chanceofrain", 0)) for h in hourly), default=None)
    except Exception:
        rain = None

    parts = [f"{_ascii(where)}: {_ascii(str(desc)).lower()}"]
    if temp is not None:
        parts[0] += f", {temp}C"
        if feels is not None and feels != temp:
            parts[0] += f" (feels like {feels}C)"
    if hi is not None and lo is not None:
        parts.append(f"today {lo}-{hi}C")
    if rain is not None:
        parts.append(f"{rain}% chance of rain")
    if hum is not None:
        parts.append(f"humidity {hum}%")
    if wind is not None:
        parts.append(f"wind {wind} km/h")
    return _ascii(". ".join(parts) + ".")
