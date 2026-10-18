"""Compatibility import of the packaged environment owner; no duplicate mathematics."""
from importlib import import_module as _import_module
_canonical = _import_module("quantbt.diagnostics.environments.manifests")
globals().update({k: v for k, v in vars(_canonical).items() if not k.startswith("__")})
