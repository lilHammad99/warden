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
import traceback

_TOOLS: dict[str, dict] = {}


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
