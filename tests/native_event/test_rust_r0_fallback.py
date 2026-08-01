from __future__ import annotations

from pathlib import Path
from types import ModuleType
import tomllib

import pytest

from quantbt.backends._native_event_rust import (
    NativeEventRustBackendError,
    probe_native_event_rust_extension,
    resolve_native_event_backend,
)

from .conftest import ScheduledCommandStrategy, bars, run_reactive


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _native_module(*, api_version: str = "0.3", reactive_session: bool = False) -> ModuleType:
    module = ModuleType("_quantbt_native")
    module.version = lambda: "0.3.0"
    module.api_version = lambda: api_version
    module.capabilities = lambda: {"r0_import_smoke": True, "reactive_session": reactive_session}
    return module


def test_native_event_auto_resolves_to_python_without_importing_extension() -> None:
    selection = resolve_native_event_backend(requested="auto")
    assert selection.requested == "auto"
    assert selection.resolved == "python"


def test_native_event_r1_crate_declares_reactive_session_capability() -> None:
    cargo = (PROJECT_ROOT / "rust" / "native_event" / "Cargo.toml").read_text(encoding="utf-8")
    metadata = tomllib.loads((PROJECT_ROOT / "rust" / "native_event" / "pyproject.toml").read_text(encoding="utf-8"))
    source = (PROJECT_ROOT / "rust" / "native_event" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert 'name = "quantbt-native"' in cargo
    assert 'name = "_quantbt_native"' in cargo
    assert metadata["project"]["name"] == "quantbt-native"
    assert metadata["tool"]["maturin"]["module-name"] == "_quantbt_native"
    assert '"r0_import_smoke", true' in source
    assert '"reactive_session", true' in source
    assert "ReactiveSessionCore" in source


def test_native_event_explicit_rust_fails_clearly_when_extension_is_absent() -> None:
    status = probe_native_event_rust_extension(module_loader=lambda: None)
    with pytest.raises(NativeEventRustBackendError, match="not installed"):
        resolve_native_event_backend(requested="rust", extension_status=status)


def test_native_event_version_mismatch_is_never_silently_accepted() -> None:
    status = probe_native_event_rust_extension(module=_native_module(api_version="0.2"))
    assert status.available
    assert not status.compatible
    with pytest.raises(NativeEventRustBackendError, match="version mismatch"):
        resolve_native_event_backend(requested="rust", extension_status=status)


def test_native_event_r0_extension_is_compatible_but_not_executable() -> None:
    status = probe_native_event_rust_extension(module=_native_module())
    assert status.compatible
    assert not status.executable
    with pytest.raises(NativeEventRustBackendError, match="reactive_session"):
        resolve_native_event_backend(requested="rust", extension_status=status)


def test_native_event_replay_certified_environment_preserves_replay_mode(monkeypatch) -> None:
    monkeypatch.setenv("QUANTBT_NATIVE_BACKEND", "replay_certified")
    result = run_reactive("single_pass", ScheduledCommandStrategy({}), data=bars(4))
    assert result.metadata["reactive_kernel_mode"] == "replay_certified"
    assert result.metadata["native_event_backend_requested"] == "replay_certified"
    assert result.metadata["native_event_backend_resolved"] == "replay_certified"
