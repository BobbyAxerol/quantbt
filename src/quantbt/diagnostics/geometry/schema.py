"""Compatibility import of the existing canonical owner; no duplicate math."""
from importlib import import_module as _import_module
_canonical = _import_module("quantbt.mode5.geometry.schema")
globals().update({k: v for k, v in vars(_canonical).items() if not k.startswith("__")})
