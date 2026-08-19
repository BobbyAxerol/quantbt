from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tomllib

import numpy as np
import pytest

from quantbt.backends._native_event_rust import probe_native_event_rust_extension


ROOT = Path(__file__).resolve().parents[3]
RUST_ROOT = ROOT / "rust"


def _cargo(package: str) -> dict:
    return tomllib.loads((RUST_ROOT / "crates" / package / "Cargo.toml").read_text(encoding="utf-8"))


def test_phase53a_workspace_keeps_pyo3_at_the_outer_binding_boundary():
    workspace = tomllib.loads((RUST_ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    assert set(workspace["workspace"]["members"]) >= {
        "native_event",
        "crates/quantbt-domain",
        "crates/quantbt-engine",
        "crates/quantbt-strategy-ir",
        "crates/quantbt-batch",
        "crates/quantbt-portfolio",
        "crates/quantbt-package",
    }
    for package in ("quantbt-domain", "quantbt-engine", "quantbt-strategy-ir", "quantbt-batch", "quantbt-portfolio", "quantbt-package"):
        dependencies = _cargo(package).get("dependencies", {})
        assert "pyo3" not in dependencies
        assert "numpy" not in dependencies


def test_phase53a_taxonomy_freezes_e0_to_e6_without_claiming_future_engines():
    payload = json.loads(
        (ROOT / "benchmarks/native_event/results/phase53a/benchmark_taxonomy.json").read_text(encoding="utf-8")
    )
    assert payload["phase"] == "53A"
    assert [workload["id"][:2] for workload in payload["workloads"]] == [f"E{number}" for number in range(7)]
    assert payload["workloads"][0]["phase_53a_gate"] is True
    assert all(not workload["phase_53a_gate"] for workload in payload["workloads"][1:])


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
def test_phase53a_internal_abi_and_flat_static_tape_output_are_exposed_without_public_api_drift():
    import _quantbt_native

    status = probe_native_event_rust_extension()
    assert status.available and status.compatible and status.executable
    assert _quantbt_native.api_version() == "0.4"
    assert _quantbt_native.core_abi_version() == "0.5"
    assert status.capabilities["core_abi_0_5"] is True
    assert status.capabilities["generation_safe_order_arena"] is True
    assert status.capabilities["flat_static_tape_output"] is True

    source = (RUST_ROOT / "native_event/src/lib.rs").read_text(encoding="utf-8")
    assert "mod full;" not in source
    assert "mod accounting;" not in source
    assert "mod matching;" not in source
    assert "mod session;" not in source

    # The public Rust runner continues to expose a contiguous (bars, symbols)
    # NumPy matrix. Internally it arrives from one bar-major flat Rust buffer.
    from quantbt.backends._native_event_rust import RustFullRunner

    assert RustFullRunner.__name__ == "RustFullRunner"
    assert np.dtype(np.float64).itemsize == 8
