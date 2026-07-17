from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from quantbt.adapters.nautilus import NautilusBacktestEngine


def _load_smoke_module():
    path = Path(__file__).resolve().parents[1] / "benchmarks" / "run_pct_equity_nautilus_smoke.py"
    spec = importlib.util.spec_from_file_location("pct_equity_nautilus_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pct_equity_nautilus_smoke_explains_aligned_and_user_like_diff():
    try:
        NautilusBacktestEngine.check_available()
    except ImportError as exc:
        pytest.skip(f"NautilusTrader is not installed: {exc}")

    smoke = _load_smoke_module()
    report = smoke.run_smoke(rows=300)
    scenarios = {item["name"]: item for item in report["scenarios"]}
    aligned = scenarios["aligned_fee_no_funding_no_slippage"]
    mismatch = scenarios["user_like_mismatch"]

    assert report["status"] == "pass"
    assert abs(aligned["final_equity_diff"]) < 1.0
    assert aligned["native"]["num_trades"] == aligned["nautilus"]["num_trades"]
    assert aligned["diagnostic"]["checks"]["fee_convention_matches_native"] is True
    assert aligned["diagnostic"]["checks"]["funding_matches_native"] is True
    assert aligned["diagnostic"]["checks"]["slippage_matches_native"] is True

    assert mismatch["diagnostic"]["checks"]["fee_convention_matches_native"] is False
    assert mismatch["diagnostic"]["checks"]["funding_matches_native"] is False
    assert mismatch["diagnostic"]["checks"]["slippage_matches_native"] is False
    assert mismatch["diagnostic"]["checks"]["custom_fee_rate_applied_to_nautilus"] is False
    assert mismatch["diagnostic"]["checks"]["custom_slippage_applied_to_nautilus"] is False
