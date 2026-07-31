"""Tool registry: @tool registers a function with its JSON schema so the
agent can offer it to the model and dispatch calls back to Python.

``dispatch`` is deliberately forgiving, because an 8B local model WILL
eventually hallucinate: it invents tool names that don't exist, passes a
JSON string where a dict is expected, or sprinkles extra junk arguments
("reason", "thought", ...) onto an otherwise-valid call. A dead-end error
leaves the model stuck. Instead dispatch tries to let the model recover:

- **Unknown/misspelled tool name** -> we don't just say "unknown"; we point
  at the closest real tool(s) so the next round can self-correct.
- **Args aren't a dict** (a JSON string, a list, None) -> normalised, not
  crashed.
- **Unexpected extra arguments** -> dropped (with a short note) so a valid
  call still goes through instead of failing on a stray key.
- **Genuinely missing required arguments** -> reported by name, so the model
  knows exactly what to supply, rather than seeing a raw ``TypeError``.

Nothing here can crash the agent: every path returns a plain string.
"""

import difflib
import inspect
import json
import re
import traceback

_TOOLS: dict[str, dict] = {}

# Tools always offered to the model, regardless of the question: the everyday
# ones and those whose trigger words are too vague to keyword-match reliably.
# Everything else is added per-turn by specs_for() when the question mentions
# it. dispatch() still runs ANY registered tool, so a tool left out of the
# offer is never truly lost -- the model can find it via list_tools.
_CORE = {
    "today", "calculate", "convert_units", "count_words",
    "write_file", "read_file", "find_files", "search_files",
    "open_app", "open_website", "web_search",
    "run_command", "remember", "recall", "add_task", "list_tasks",
    "describe_view", "start_working", "stop_working", "list_tools",
}

# words too common to signal a specific tool
_STOP = {
    "the", "and", "for", "you", "your", "what", "whats", "how", "many", "much",
    "can", "would", "could", "should", "please", "with", "this", "that", "these",
    "those", "from", "into", "out", "get", "got", "have", "has", "was", "are",
    "was", "were", "will", "them", "they", "any", "all", "some", "one", "two",
    "sir", "jarvis", "tell", "give", "show", "make", "want", "need", "about",
    "here", "there", "then", "now", "just", "like", "does", "did", "not",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


def _terms(entry: dict) -> set[str]:
    """Keyword set for a tool (its name + description), computed once."""
    terms = entry.get("_terms")
    if terms is None:
        f = entry["spec"]["function"]
        terms = _words(f["name"].replace("_", " ") + " " + f["description"])
        entry["_terms"] = terms
    return terms


def tool(name: str, description: str, parameters: dict | None = None):
    def deco(fn):
        _TOOLS[name] = {
            "fn": fn,
            "spec": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters
                    or {"type": "object", "properties": {}, "required": []},
                },
            },
        }
        return fn

    return deco


def specs() -> list[dict]:
    return [t["spec"] for t in _TOOLS.values()]


def specs_for(text: str, limit: int = 24) -> list[dict]:
    """The subset of tools to offer the model for THIS question.

    A small local model chooses badly when shown all ~70 tools at once, so we
    always offer the core set plus the non-core tools whose keywords the
    question actually mentions, ranked by overlap, up to `limit` total. Ties
    break alphabetically for a stable offer. dispatch() is unaffected -- it
    still runs any registered tool the model names."""
    core = [(n, t["spec"]) for n, t in _TOOLS.items() if n in _CORE]
    user_kw = _words(text)
    scored = []
    for n, t in _TOOLS.items():
        if n in _CORE:
            continue
        score = len(user_kw & _terms(t))
        if score:
            scored.append((-score, n, t["spec"]))
    scored.sort()  # highest score first, then name
    room = max(0, limit - len(core))
    extra = [spec for _, _, spec in scored[:room]]
    return [spec for _, spec in core] + extra


def names() -> list[str]:
    """All registered tool names (for suggestions / diagnostics)."""
    return list(_TOOLS.keys())


def _suggest(name: str) -> str:
    """A short, ASCII, self-correction hint for a bad tool name."""
    known = names()
    close = difflib.get_close_matches(str(name), known, n=3, cutoff=0.6)
    if close:
        return "Did you mean: " + ", ".join(close) + "?"
    # no near match: nudge without dumping all ~40 names
    return ("Use one of your available tools; call list_tools if you are "
            "unsure which exist.")


def _normalize_args(args) -> dict:
    """Coerce whatever the model handed us into a plain dict. A missing value,
    a JSON string, or the wrong type all become a (possibly empty) dict rather
    than blowing up the call."""
    if args is None:
        return {}
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _prepare_args(fn, args: dict):
    """Split the model's arguments against the function's real signature.

    Returns (clean_kwargs, dropped_names, missing_required). If the function
    accepts ``**kwargs`` we leave everything alone. Otherwise we keep only the
    parameters it actually declares and report the rest, plus any required
    parameter (no default) the model forgot."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return dict(args), [], []  # builtin / unintrospectable: pass through

    params = sig.parameters
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return dict(args), [], []  # fn takes **kwargs: nothing is "unexpected"

    valid = {
        n for n, p in params.items()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }
    clean = {k: v for k, v in args.items() if k in valid}
    dropped = [k for k in args if k not in valid]
    missing = [
        n for n, p in params.items()
        if p.default is p.empty
        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        and n not in clean
    ]
    return clean, dropped, missing


def dispatch(name, args) -> str:
    # 1) the tool name itself may be junk (wrong type, empty, hallucinated)
    if not isinstance(name, str) or not name.strip():
        return "Error: no tool name given. " + _suggest(name)
    name = name.strip()
    entry = _TOOLS.get(name)
    if entry is None:
        return f"Error: there is no tool called '{name}'. " + _suggest(name)

    fn = entry["fn"]
    args = _normalize_args(args)
    clean, dropped, missing = _prepare_args(fn, args)

    # 2) the model left out something the tool truly needs
    if missing:
        need = ", ".join(missing)
        return (f"Error: {name} needs {'an argument' if len(missing) == 1 else 'arguments'}: "
                f"{need}. Please call {name} again with {'it' if len(missing) == 1 else 'them'}.")

    # 3) run it, and never let it crash the agent
    try:
        result = fn(**clean)
    except TypeError as e:
        return f"Error: bad arguments for {name}: {e}"
    except Exception as e:
        traceback.print_exc()
        return f"Error while running {name}: {e}"

    out = str(result) if result is not None else "Done."
    # 4) if we silently ignored hallucinated extra args, say so quietly so the
    #    model learns the real parameter names without failing the call
    if dropped:
        out += (f" (note: ignored unexpected argument"
                f"{'s' if len(dropped) > 1 else ''}: {', '.join(dropped)})")
    return out


@tool(
    "list_tools",
    "List the names of every tool you can call. Use this if you are unsure "
    "whether a tool exists before calling it, or if a tool call failed with "
    "'there is no tool called ...'.",
    {"type": "object", "properties": {}, "required": []},
)
def list_tools() -> str:
    return "Available tools: " + ", ".join(sorted(names())) + "."
