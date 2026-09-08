"""Keep Phase 54B.2 benchmark labels aligned with the public routing policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from quantbt.backends._native_event_rust import probe_native_event_rust_extension


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "benchmarks" / "native_event" / "benchmark_phase54b2_public_routes.py"


def _load_benchmark_module():
    spec = importlib.util.spec_from_file_location("phase54b2_benchmark", BENCHMARK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive import guard
        raise RuntimeError(f"cannot load benchmark module: {BENCHMARK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not probe_native_event_rust_extension().executable,
    reason="quantbt-native executable extension is not installed in this environment",
)
def test_phase54b2_static_benchmark_records_auto_policy_but_times_explicit_rust() -> None:
    benchmark = _load_benchmark_module()
    frame = benchmark._frame(512)
    observation = benchmark._assert_static_parity(frame, benchmark._static_commands(frame.index))

    assert observation["auto_backend"] == "python"
    assert observation["auto_reason"] == "public_score_performance_not_stable_enough_for_auto"
    assert observation["explicit_rust_backend"] == "rust"


@pytest.mark.skipif(
    not probe_native_event_rust_extension().executable,
    reason="quantbt-native executable extension is not installed in this environment",
)
def test_phase54b2_ir_benchmark_separates_auto_score_from_explicit_rust_audit() -> None:
    benchmark = _load_benchmark_module()
    frame = benchmark._frame(2_000)
    phase = np.arange(len(frame), dtype=np.float64)
    signal = np.where(phase % 120 < 40, 1.0, np.where(phase % 120 < 80, 2.0, 0.0))
    observation = benchmark._assert_ir_parity(frame, signal, np.vstack((signal, signal)))

    assert observation["audit_auto_backend"] == "python"
    assert observation["audit_auto_reason"] == "workload_shape_not_certified"
    assert observation["batch_auto_backend"] == "rust"
    assert observation["batch_auto_reason"] == "auto_rust_certified"
