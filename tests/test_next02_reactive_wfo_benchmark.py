"""NEXT-02 benchmark-fixture contracts.

These tests do not treat benchmark timing as a unit-test assertion. They lock
the valid mode/schedule construction used by the public reactive WFO evidence,
including the nested causal Mode 1 descriptor that must satisfy the same
minimum fold contract as production WFO.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from quantbt.walkforward import WalkForwardEngine, _build_inner_folds


_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "benchmarks/native_event/benchmark_next02_reactive_wfo.py"


def _load_reactive_benchmark():
    name = "quantbt_next02_reactive_wfo_benchmark_test"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_next02_reactive_mode1_causal_fixture_builds_required_inner_folds():
    benchmark = _load_reactive_benchmark()
    profile = benchmark.PROFILE_SPECS["smoke"]
    data = benchmark._market(profile["bars"], frequency=profile["frequency"])
    mode = next(
        item
        for item in benchmark.MODE_SPECS
        if item.mode == "mode_1_decay" and item.schedule == "per_fold_causal"
    )
    config = benchmark._walkforward_config(data, spec=mode, profile=profile)
    folds = WalkForwardEngine(strategy=lambda *_args: None, config=config).build_folds(data.index)

    assert folds
    for fold in folds:
        assert len(_build_inner_folds(fold, config)) >= config.inner_min_folds
