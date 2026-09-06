"""
Sandboxed evaluation of map-algebra expressions for arcgis_raster_calculator.

The expression string comes from the LLM (and, indirectly, from whatever the
LLM has read), so it must never reach a bare ``eval``.  This module:

1. Parses the expression with ``ast`` and walks the tree, allowing only
   arithmetic / comparison / call nodes and a whitelist of names.
2. Evaluates it with ``__builtins__`` removed and a namespace that contains
   nothing but ``arcpy.sa`` functions (Raster, Con, Abs, Ln, ...).

Anything else — attribute access, subscripts, lambdas, comprehensions,
imports, dunder names, keyword arguments outside the whitelist — raises
``UnsafeExpressionError`` before any code runs.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, Iterable, Set

# Functions from arcpy.sa that make sense inside a raster calculator.
# Add to this list deliberately; never add anything from builtins/os/sys.
SA_FUNCTION_WHITELIST: Set[str] = {
    "Raster",
    "Con",
    "Pick",
    "SetNull",
    "IsNull",
    "Abs",
    "Exp",
    "Exp10",
    "Exp2",
    "Ln",
    "Log10",
    "Log2",
    "Power",
    "Square",
    "SquareRoot",
    "Int",
    "Float",
    "RoundDown",
    "RoundUp",
    "Mod",
    "Negate",
    "CellStatistics",
    "FocalStatistics",
    "Slope",
    "Aspect",
    "Hillshade",
    "Fill",
    "Reclassify",
    "Lookup",
    "Test",
    "Diff",
    "InList",
    "Over",
    "BooleanAnd",
    "BooleanOr",
    "BooleanNot",
    "BooleanXOr",
    "Cos",
    "Sin",
    "Tan",
    "ACos",
    "ASin",
    "ATan",
    "ATan2",
    "Plus",
    "Minus",
    "Times",
    "Divide",
    "EqualTo",
    "NotEqual",
    "GreaterThan",
    "GreaterThanEqual",
    "LessThan",
    "LessThanEqual",
    "NbrRectangle",
    "NbrCircle",
    "NbrAnnulus",
    "NbrWedge",
    "NbrIrregular",
    "NbrWeight",
    "RemapValue",
    "RemapRange",
}

# Boolean/None constants are the only bare names allowed besides functions.
_CONSTANT_NAMES: Set[str] = {"True", "False", "None"}

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.List,
    ast.Tuple,
    ast.keyword,
    # operators
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.Invert,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.BitAnd,
    ast.BitOr,
    ast.BitXor,
    ast.LShift,
    ast.RShift,
)

MAX_EXPRESSION_LENGTH = 4000
MAX_AST_NODES = 500


class UnsafeExpressionError(ValueError):
    """Raised when a map-algebra expression contains disallowed syntax or names."""


def validate_expression(expr: str, allowed_names: Iterable[str] = SA_FUNCTION_WHITELIST) -> ast.Expression:
    """Parse *expr* and reject anything outside the map-algebra subset.

    Returns the parsed ``ast.Expression`` so callers can compile it without
    re-parsing (avoids TOCTOU between validation and evaluation).
    """
    if not isinstance(expr, str) or not expr.strip():
        raise UnsafeExpressionError("Expression is empty.")
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise UnsafeExpressionError(f"Expression longer than {MAX_EXPRESSION_LENGTH} characters.")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpressionError(f"Syntax error in expression: {e.msg}") from e

    allowed = set(allowed_names) | _CONSTANT_NAMES
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_AST_NODES:
            raise UnsafeExpressionError("Expression is too complex.")
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpressionError(
                f"Disallowed syntax: {type(node).__name__}. "
                "Only arithmetic, comparisons and arcpy.sa function calls are permitted."
            )
        if isinstance(node, ast.Name):
            if node.id not in allowed or node.id.startswith("_"):
                raise UnsafeExpressionError(
                    f"Unknown or disallowed name: {node.id!r}. Use Raster(...) and arcpy.sa functions only."
                )
        elif isinstance(node, ast.Call):
            # Only direct calls to whitelisted names: Con(...), not x.y(...) or (lambda)(...)
            if not isinstance(node.func, ast.Name):
                raise UnsafeExpressionError("Only direct calls to arcpy.sa functions are allowed.")
        elif isinstance(node, ast.keyword):
            if node.arg is None or node.arg.startswith("_"):
                raise UnsafeExpressionError("**kwargs and dunder keyword arguments are not allowed.")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, str, bool, type(None))):
                raise UnsafeExpressionError(f"Disallowed constant type: {type(node.value).__name__}.")
    return tree


def build_sa_namespace(sa_module: Any, allowed_names: Iterable[str] = SA_FUNCTION_WHITELIST) -> Dict[str, Any]:
    """Collect whitelisted callables from ``arcpy.sa`` into an eval namespace."""
    ns: Dict[str, Any] = {}
    for name in allowed_names:
        obj = getattr(sa_module, name, None)
        if obj is not None:
            ns[name] = obj
    return ns


def safe_eval_expression(expr: str, namespace: Dict[str, Any]) -> Any:
    """Validate then evaluate *expr* with no builtins and only *namespace* visible."""
    tree = validate_expression(expr, allowed_names=namespace.keys())
    code = compile(tree, filename="<raster_calculator>", mode="eval")
    return eval(code, {"__builtins__": {}}, dict(namespace))  # noqa: S307 — AST-validated, no builtins
