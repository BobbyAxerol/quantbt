"""Lazy backend registry for immutable execution plans."""

from __future__ import annotations

from typing import Callable

from ..planning import BackendKind
from .native_event import PythonNativeEventBackend, RustNativeEventBackend


_BACKENDS: dict[BackendKind, Callable[[], object]] = {
    BackendKind.PYTHON: PythonNativeEventBackend,
    BackendKind.RUST: RustNativeEventBackend,
}


def registered_backends() -> tuple[str, ...]:
    return tuple(kind.value for kind in _BACKENDS)


def create_backend(kind: BackendKind | str):
    backend_kind = kind if isinstance(kind, BackendKind) else BackendKind(str(kind).lower().strip())
    return _BACKENDS[backend_kind]()


__all__ = ["create_backend", "registered_backends"]
