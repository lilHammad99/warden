"""Safe calculator for Jarvis.

An 8B local model is unreliable at arithmetic - it will confidently give a
wrong sum or drop a digit. This gives Jarvis a real calculator so it can
compute instead of guessing: totals, percentages, roots, trig, logs. Answers
are exact, so it is a genuine autonomy / accuracy win.

Safety model (strict, because the 8B model WILL eventually pass junk or try
something dangerous):

- **No eval/exec.** The expression is parsed to an AST and walked by hand.
  ONLY numbers, arithmetic operators, a small allowlist of math functions, and
  the constants pi/e/tau are permitted. There are no names, no attribute
  access, and no calls to anything off the allowlist - so a hallucinated
  ``__import__('os').system('del *')`` is refused, never run.
- **Sizes are capped.** Expression length, AST node count, power exponent and
  factorial argument are all bounded, so ``9**9**9`` or ``factorial(999999)``
  can't hang the agent or exhaust memory.
- **Never raises.** Wrong types are coerced to a string, and every bad input
  (syntax error, divide-by-zero, domain error, overflow) comes back as a
  plain, friendly message the model can read and recover from.
"""

import ast
import math
import operator

from .registry import tool

MAX_EXPR_LEN = 500     # a calculation, not an essay
MAX_NODES = 200        # bound on expression complexity
MAX_POW_EXP = 1000     # refuse runaway exponents (9 ** 9 ** 9)
MAX_FACTORIAL = 1000   # refuse factorial(999999)

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_factorial(x):
    if isinstance(x, float) and not x.is_integer():
        raise ValueError("factorial needs a whole number")
    x = int(x)
    if x < 0 or x > MAX_FACTORIAL:
        raise ValueError("factorial argument out of range")
    return math.factorial(x)


_FUNCS = {
    "sqrt": math.sqrt, "cbrt": getattr(math, "cbrt", lambda v: v ** (1.0 / 3)),
    "abs": abs, "round": round, "min": min, "max": max,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "hypot": math.hypot,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "pow": math.pow,
    "floor": math.floor, "ceil": math.ceil, "trunc": math.trunc,
    "degrees": math.degrees, "radians": math.radians,
    "gcd": math.gcd, "fabs": math.fabs, "factorial": _safe_factorial,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval(node):
    """Recursively evaluate an allowlisted AST node. Raises ValueError (or a
    math error) on anything not permitted - callers translate that to a
    friendly string."""
    if isinstance(node, ast.Expression):
        return _eval(node.body)

    if isinstance(node, ast.Constant):
        # bool is a subclass of int - reject it so True/False can't sneak in
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numbers are allowed")
        return node.value

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError("that operator isn't allowed")
        left = _eval(node.left)
        right = _eval(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_POW_EXP:
                raise ValueError("exponent too large")
            if abs(left) > 1e6 and abs(right) > 100:
                raise ValueError("result too large")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("that operator isn't allowed")
        return op(_eval(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only simple function calls are allowed")
        fn = _FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"'{node.func.id}' is not an allowed function")
        if node.keywords:
            raise ValueError("keyword arguments aren't allowed")
        return fn(*[_eval(a) for a in node.args])

    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise ValueError(f"'{node.id}' isn't a known constant")

    raise ValueError("that part of the expression isn't allowed")


def _format(value) -> str:
    """Render a numeric result cleanly (pure ASCII): whole floats as ints,
    others trimmed to a sensible precision."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        if value.is_integer() and abs(value) < 1e16:
            return str(int(value))
        return f"{round(value, 10):.10g}"
    return str(value)


@tool(
    "calculate",
    "Evaluate a mathematical expression and return the exact result. USE this "
    "whenever the user asks for arithmetic or any math (sums, differences, "
    "products, percentages, etc.) instead of working it out yourself, because "
    "it is always exact. Supports + - * / // % ** parentheses and functions "
    "like sqrt, sin, cos, log, round, min, max, factorial, plus the constants "
    "pi and e. Example expression: '(1250 * 1.2) / 3'.",
    {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The math expression to evaluate, e.g. "
                "'3 * (4 + 5)', '15/100 * 240', or 'sqrt(2)'",
            },
        },
        "required": ["expression"],
    },
)
def calculate(expression="") -> str:
    # coerce any model-supplied value to a bounded string (it may pass a
    # number, list, dict, or None)
    if expression is None:
        raw = ""
    elif isinstance(expression, str):
        raw = expression
    else:
        raw = str(expression)
    # strip nulls, whitespace, and decoration the model sometimes adds
    expr = raw.replace("\x00", "").strip().strip("`").strip()
    if expr.startswith("="):
        expr = expr[1:].strip()

    if not expr:
        return "Error: give me something to calculate, sir."
    if len(expr) > MAX_EXPR_LEN:
        return (f"Error: that expression is too long, sir (limit "
                f"{MAX_EXPR_LEN} characters).")

    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, MemoryError):
        return f'Error: I could not read "{expr}" as a math expression, sir.'

    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        return "Error: that expression is too complex, sir."

    try:
        result = _eval(tree)
    except ZeroDivisionError:
        return "Error: that divides by zero, sir."
    except (ValueError, OverflowError, TypeError) as e:
        return f"Error: I can't compute that, sir ({e})."
    except Exception:
        return "Error: that isn't a valid calculation, sir."

    return f"{expr} = {_format(result)}"
