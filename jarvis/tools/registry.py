"""Tool registry: @tool registers a function with its JSON schema so the
agent can offer it to the model and dispatch calls back to Python."""

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


def dispatch(name: str, args: dict) -> str:
    entry = _TOOLS.get(name)
    if entry is None:
        return f"Error: unknown tool '{name}'."
    try:
        result = entry["fn"](**(args or {}))
        return str(result) if result is not None else "Done."
    except TypeError as e:
        return f"Error: bad arguments for {name}: {e}"
    except Exception as e:
        traceback.print_exc()
        return f"Error while running {name}: {e}"
