"""Compatibility import; canonical implementation ships under src/quantbt."""
from importlib import import_module as _import_module
_canonical = _import_module("quantbt.mode5.selection.advisory")
globals().update({k: v for k, v in vars(_canonical).items() if not k.startswith("__")})
