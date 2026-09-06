"""Tests for utils.safe_expr — run with: python -m pytest tests/test_safe_expr.py -q"""

import types

import pytest

from utils.safe_expr import (
    UnsafeExpressionError,
    build_sa_namespace,
    safe_eval_expression,
    validate_expression,
)


# --- a tiny fake arcpy.sa so the tests run without ArcGIS Pro --------------
class FakeRaster:
    def __init__(self, path):
        self.path = path
        self.value = float(len(path))  # deterministic stand-in

    def _bin(self, other, op):
        o = other.value if isinstance(other, FakeRaster) else other
        return FakeRaster(str(op(self.value, o)))

    __add__ = lambda s, o: s._bin(o, lambda a, b: a + b)
    __sub__ = lambda s, o: s._bin(o, lambda a, b: a - b)
    __mul__ = lambda s, o: s._bin(o, lambda a, b: a * b)
    __truediv__ = lambda s, o: s._bin(o, lambda a, b: a / b if b else 0)
    __gt__ = lambda s, o: s._bin(o, lambda a, b: float(a > b))


def fake_con(cond, a, b=0):
    return FakeRaster(f"con({cond.path},{a},{b})")


FAKE_SA = types.SimpleNamespace(Raster=FakeRaster, Con=fake_con, Abs=lambda r: r)
NS = build_sa_namespace(FAKE_SA)


# --- valid expressions -----------------------------------------------------
@pytest.mark.parametrize(
    "expr",
    [
        '(Raster("nir.tif") - Raster("red.tif")) / (Raster("nir.tif") + Raster("red.tif"))',
        'Con(Raster("slope.tif") > 25, 1, 0)',
        'Raster("dem_2024.tif") - Raster("dem_2020.tif")',
        'Raster("ndvi.tif") * 10000',
        'Abs(Raster("a.tif")) + 1.5',
        'Con(Raster("s.tif") > 25, 1)',
    ],
)
def test_valid_map_algebra_runs(expr):
    assert isinstance(safe_eval_expression(expr, NS), FakeRaster)


def test_namespace_only_contains_whitelisted_names():
    assert set(NS) == {"Raster", "Con", "Abs"}


# --- injection attempts must be rejected before evaluation -----------------
@pytest.mark.parametrize(
    "expr",
    [
        '__import__("os").system("calc")',
        'open("C:/secret.txt").read()',
        'Raster("a.tif").__class__.__mro__',
        'Raster.__init__.__globals__',
        '(lambda: 1)()',
        '[x for x in ()]',
        'getattr(Raster, "x")',
        'Raster("a.tif")[0]',
        'Con(**{"a": 1})',
        'exec("1")',
        'Raster("a.tif"); import os',
        'x = 1',
        'Raster(f"{1}")',
        '',
        '   ',
    ],
)
def test_unsafe_expressions_rejected(expr):
    with pytest.raises(UnsafeExpressionError):
        safe_eval_expression(expr, NS)


def test_unknown_function_rejected_even_if_harmless_looking():
    with pytest.raises(UnsafeExpressionError):
        validate_expression('Zonal("a.tif")', allowed_names=["Raster"])


def test_too_long_or_too_complex_rejected():
    with pytest.raises(UnsafeExpressionError):
        validate_expression("1+" * 3000 + "1")
    with pytest.raises(UnsafeExpressionError):
        validate_expression("+".join(["Raster('a')"] * 300))


def test_builtins_not_reachable():
    # Even a name that happens to exist in builtins is not in the namespace.
    with pytest.raises(UnsafeExpressionError):
        safe_eval_expression("print(1)", NS)
