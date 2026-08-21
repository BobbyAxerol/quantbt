"""Phase 54A.5.1 conformance for the legacy Rust compatibility facade.

The public R1/R2 PyO3 names stay available for old callers, but their
eight-column command ABI must be an ingress/egress adapter over the same
``FullSession`` lifecycle implementation used by the API-0.4 route.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _market(n_bars: int = 6):
    import _quantbt_native

    index = pd.date_range("2024-01-01", periods=n_bars, freq="1h", tz="UTC")
    close = np.ascontiguousarray(100.0 + np.arange(n_bars, dtype=np.float64))
    opens = np.ascontiguousarray(close.copy())
    highs = np.ascontiguousarray(close + 2.0)
    lows = np.ascontiguousarray(close - 2.0)
    zeros = np.zeros(n_bars, dtype=np.float64)
    mask = np.zeros(n_bars, dtype=np.bool_)
    legacy = _quantbt_native.PreparedMarketCore(index.asi8, opens, highs, lows, close, zeros, zeros, mask)
    full = _quantbt_native.FullPreparedMarketCore(
        index.asi8,
        opens[:, None],
        highs[:, None],
        lows[:, None],
        close[:, None],
        zeros[:, None],
        zeros[:, None],
        mask,
    )
    return index, legacy, full


def _legacy_rows(*, action: int, side: int = -1, order_type: int = -1, flags: int = 0,
                 order_id: int = -1, target_id: int = -1, mutate_mask: int = 0,
                 sequence: int = 0, qty: float = 0.0, price: float = 0.0,
                 trigger: float = 0.0):
    codes = np.full((1, 8), -1, dtype=np.int64)
    values = np.zeros((1, 3), dtype=np.float64)
    expiry = np.full(1, -1, dtype=np.int64)
    codes[0] = [action, side, order_type, flags, order_id, target_id, mutate_mask, sequence]
    values[0] = [qty, price, trigger]
    return codes, values, expiry


def _empty_legacy_rows():
    return (
        np.empty((0, 8), dtype=np.int64),
        np.empty((0, 3), dtype=np.float64),
        np.empty(0, dtype=np.int64),
    )


def _full_from_legacy(codes: np.ndarray, values: np.ndarray, expiry: np.ndarray):
    """Independent test-side projection of the frozen 8-column contract."""

    out_codes = np.full((len(codes), 16), -1, dtype=np.int64)
    out_values = np.ascontiguousarray(values.copy(), dtype=np.float64)
    out_expiry = np.ascontiguousarray(expiry.copy(), dtype=np.int64)
    action_map = {0: 0, 1: 1, 2: 3, 3: 2}
    for row, old in enumerate(codes):
        action = int(old[0])
        out_codes[row, 0] = action_map.get(action, action)
        out_codes[row, 1] = 0 if action in {0, 3} else -1
        out_codes[row, 2] = old[1]
        out_codes[row, 3] = old[2]
        out_codes[row, 4] = 0
        out_codes[row, 5] = int(bool(old[3] & 1))
        out_codes[row, 6] = old[4]
        out_codes[row, 7] = old[5]
        out_codes[row, 8:11] = -1
        out_codes[row, 11] = 0
        out_codes[row, 12] = max(0, int(old[7]))
        if action == 2:
            if not old[6] & 1:
                out_values[row, 0] = 0.0
            if not old[6] & 2:
                out_values[row, 1] = 0.0
            if not old[6] & 4:
                out_values[row, 2] = 0.0
    return out_codes, out_values, out_expiry


def _legacy_events_from_full(rows):
    kind_map = {0: 0, 1: 1, 2: 5, 3: 4, 4: 2, 7: 3}
    projected = []
    for row in rows:
        kind = int(row[0])
        if kind == 2:
            projected.append([5, 2, int(row[2]), int(row[3])])
        if kind in kind_map:
            projected.append([kind_map[kind], int(row[1]), int(row[2]), int(row[3])])
    return projected


def _legacy_fills_from_full(rows):
    return [[float(row[0]), float(row[2]), float(row[3]), float(row[4]), float(row[5])] for row in rows]


def _legacy_active_from_full(rows):
    return [[float(row[0]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[6]), float(row[8])]
            for row in rows]


def test_legacy_reactive_core_is_full_session_compatibility_adapter() -> None:
    import _quantbt_native

    index, legacy_market, full_market = _market()
    legacy = _quantbt_native.ReactiveSessionCore.from_prepared(
        legacy_market,
        1.0,
        5.0,
        0.0002,
        10_000.0,
        0.0,
        0.0001,
        False,
    )
    full = _quantbt_native.FullReactiveSessionCore.from_prepared(
        full_market,
        np.array([1.0], dtype=np.float64),
        np.array([5.0], dtype=np.float64),
        np.array([0.0002], dtype=np.float64),
        10_000.0,
        0.0,
        0.0001,
        False,
    )

    # Commands exercise bar-zero handling, mask-aware AMEND, REPLACE and a
    # reduce-only market exit. None uses a feature outside the frozen R2 ABI.
    batches = {
        0: _legacy_rows(action=0, side=1, order_type=1, order_id=11, qty=1.0, price=90.0),
        1: _legacy_rows(action=2, target_id=11, mutate_mask=2, sequence=1, price=100.5),
        2: _legacy_rows(action=0, side=-1, order_type=1, order_id=12, qty=1.0, price=110.0),
        3: _legacy_rows(action=3, side=-1, order_type=1, order_id=13, target_id=12, sequence=3, qty=1.0, price=102.5),
        4: _legacy_rows(action=0, side=-1, order_type=0, flags=1, order_id=14, qty=3.0),
    }

    legacy_steps = []
    for bar in range(len(index)):
        legacy_codes, legacy_values, expiry = batches.get(bar, _empty_legacy_rows())
        full_codes, full_values, full_expiry = _full_from_legacy(legacy_codes, legacy_values, expiry)
        legacy_step = legacy.step(bar, legacy_codes, legacy_values, expiry)
        full_step = full.step(bar, full_codes, full_values, full_expiry)
        legacy_steps.append(legacy_step)

        for key in ("equity", "fee", "turnover", "initial_margin", "maintenance_margin"):
            np.testing.assert_allclose(legacy_step[key], full_step[key], rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(legacy_step["position"], full_step["positions"][0], rtol=0.0, atol=1e-12)
        assert legacy_step["fills"] == _legacy_fills_from_full(full_step["fills"])
        assert legacy_step["events"] == _legacy_events_from_full(full_step["events"])
        assert legacy_step["active_orders"] == _legacy_active_from_full(full_step["active_orders"])

    assert legacy_steps[-1]["position"] == 0.0
    assert legacy_steps[-1]["active_orders"] == []

    legacy.reset()
    reset_step = legacy.step(0, *_empty_legacy_rows())
    assert reset_step["equity"] == 10_000.0
    assert reset_step["position"] == 0.0


def test_legacy_reactive_core_fails_closed_for_uncertified_accounting() -> None:
    import _quantbt_native

    _, legacy_market, _ = _market()
    with pytest.raises(ValueError, match="funding"):
        _quantbt_native.ReactiveSessionCore.from_prepared(
            legacy_market, 1.0, 5.0, 0.0002, 10_000.0, 0.0, 0.0, True
        )
    with pytest.raises(ValueError, match="liquidation"):
        _quantbt_native.ReactiveSessionCore.from_prepared(
            legacy_market, 1.0, 5.0, 0.0002, 10_000.0, 0.005, 0.0, False
        )


def test_binding_does_not_import_the_legacy_execution_runtime() -> None:
    root = Path(__file__).parents[2]
    source = (root / "rust" / "native_event" / "src" / "lib.rs").read_text()
    legacy_module = (root / "rust" / "crates" / "quantbt-engine" / "src" / "legacy" / "mod.rs").read_text()
    assert "use quantbt_engine::legacy::{PreparedMarketData, ReactiveSession};" not in source
    assert "struct LegacyFullSessionAdapter" in source
    assert "inner: FullSession" in source
    assert "translate_legacy_command_batch" in source
    assert "pub mod session;" not in legacy_module
    assert "pub mod matching;" not in legacy_module
    assert "pub mod accounting;" not in legacy_module
