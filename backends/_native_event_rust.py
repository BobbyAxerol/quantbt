"""Optional PyO3 capability probe for the native-event accelerator.

Phase 44A deliberately keeps this module free of matching or accounting
logic.  The Python/Numba implementation remains the execution backend until a
future Rust slice has passed lifecycle and accounting parity certification.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from types import ModuleType
from typing import Callable, Mapping, Optional


RUST_NATIVE_API_VERSION = "0.3"
_VALID_BACKENDS = frozenset({"auto", "python", "rust", "replay_certified"})


class NativeEventRustBackendError(RuntimeError):
    """Raised when an explicitly requested Rust backend cannot be used."""


@dataclass(frozen=True)
class NativeEventRustExtensionStatus:
    """Import and compatibility state of the optional ``_quantbt_native`` wheel."""

    available: bool
    compatible: bool
    executable: bool
    version: Optional[str]
    api_version: Optional[str]
    capabilities: Mapping[str, bool]
    reason: Optional[str] = None


@dataclass(frozen=True)
class NativeEventBackendSelection:
    """Internal backend decision without changing the public endpoint API."""

    requested: str
    resolved: str
    extension: NativeEventRustExtensionStatus


def _empty_status(reason: str) -> NativeEventRustExtensionStatus:
    return NativeEventRustExtensionStatus(
        available=False,
        compatible=False,
        executable=False,
        version=None,
        api_version=None,
        capabilities={},
        reason=reason,
    )


def _load_extension() -> Optional[ModuleType]:
    return importlib.import_module("_quantbt_native")


def _read_native_value(module: ModuleType, name: str) -> Optional[object]:
    value = getattr(module, name, None)
    return value() if callable(value) else value


def probe_native_event_rust_extension(
    module: Optional[ModuleType] = None,
    *,
    module_loader: Optional[Callable[[], Optional[ModuleType]]] = None,
) -> NativeEventRustExtensionStatus:
    """Return extension compatibility without enabling a Rust execution path.

    ``module`` and ``module_loader`` are test seams.  Runtime callers should
    leave both unset so the optional extension is imported normally.
    """
    if module is None:
        loader = _load_extension if module_loader is None else module_loader
        try:
            module = loader()
        except (ImportError, OSError) as exc:
            return _empty_status(f"unable to import _quantbt_native: {exc}")
    if module is None:
        return _empty_status("quantbt-native is not installed; install a compatible native wheel first")

    try:
        version_value = _read_native_value(module, "version")
        version = str(version_value if version_value is not None else getattr(module, "__version__", "")) or None
        api_value = _read_native_value(module, "api_version")
        api_version = str(api_value) if api_value is not None else None
        raw_capabilities = _read_native_value(module, "capabilities")
    except Exception as exc:  # pragma: no cover - protects optional binary imports.
        return _empty_status(f"failed to query _quantbt_native metadata: {exc}")

    if not isinstance(raw_capabilities, Mapping):
        raw_capabilities = {}
    capabilities = {str(name): bool(enabled) for name, enabled in raw_capabilities.items()}
    compatible = api_version == RUST_NATIVE_API_VERSION
    if not compatible:
        return NativeEventRustExtensionStatus(
            available=True,
            compatible=False,
            executable=False,
            version=version,
            api_version=api_version,
            capabilities=capabilities,
            reason=(
                "_quantbt_native API version mismatch: "
                f"expected {RUST_NATIVE_API_VERSION!r}, received {api_version!r}"
            ),
        )

    executable = bool(capabilities.get("reactive_session", False))
    reason = None if executable else "_quantbt_native R0 is import-only; reactive execution is not implemented yet"
    return NativeEventRustExtensionStatus(
        available=True,
        compatible=True,
        executable=executable,
        version=version,
        api_version=api_version,
        capabilities=capabilities,
        reason=reason,
    )


def resolve_native_event_backend(
    requested: Optional[str] = None,
    *,
    extension_status: Optional[NativeEventRustExtensionStatus] = None,
) -> NativeEventBackendSelection:
    """Resolve the internal native-event backend under the R0 rollout policy.

    ``auto`` intentionally resolves to Python during R0, even with the wheel
    installed.  ``rust`` is explicit and therefore fails loudly until a later
    Rust feature slice certifies an executable reactive session.
    """
    selected = str(requested or os.getenv("QUANTBT_NATIVE_BACKEND", "auto")).lower().strip()
    if selected not in _VALID_BACKENDS:
        valid = ", ".join(sorted(_VALID_BACKENDS))
        raise ValueError(f"QUANTBT_NATIVE_BACKEND must be one of: {valid}")

    status = extension_status
    if selected == "rust":
        status = status or probe_native_event_rust_extension()
        if not status.available or not status.compatible or not status.executable:
            detail = status.reason or "unknown native extension state"
            raise NativeEventRustBackendError(f"native-event backend='rust' is unavailable: {detail}")
        return NativeEventBackendSelection(requested=selected, resolved="rust", extension=status)

    # R0 rollout contract: never auto-enable a just-built extension.
    status = status or _empty_status("Rust extension was not queried because the Python backend was selected")
    resolved = "replay_certified" if selected == "replay_certified" else "python"
    return NativeEventBackendSelection(requested=selected, resolved=resolved, extension=status)


__all__ = [
    "NativeEventBackendSelection",
    "NativeEventRustBackendError",
    "NativeEventRustExtensionStatus",
    "RUST_NATIVE_API_VERSION",
    "probe_native_event_rust_extension",
    "resolve_native_event_backend",
]
