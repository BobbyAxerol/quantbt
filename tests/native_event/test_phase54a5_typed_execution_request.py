"""Phase 54A.5.2 typed native execution-request conformance.

The frozen API-0.4 arrays remain accepted by ``FullReactiveSessionCore``.
They must now be translated once to ABI-0.5 ``CommandTapeV5`` before the one
authoritative ``FullSession`` lifecycle runs.  The additive request class locks
that same path for immutable static and strategy-IR workloads.
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


NEXT_OPEN = 3


def _prepared(n_bars: int = 6):
    import _quantbt_native

    index = pd.date_range("2025-01-01", periods=n_bars, freq="1h", tz="UTC")
    close = np.ascontiguousarray(100.0 + np.arange(n_bars, dtype=np.float64))
    opens = np.ascontiguousarray(close.copy())
    highs = np.ascontiguousarray(close + 1.0)
    lows = np.ascontiguousarray(close - 1.0)
    volume = np.ascontiguousarray(10.0 + np.arange(n_bars, dtype=np.float64))
    funding = np.zeros(n_bars, dtype=np.float64)
    funding[3] = 0.0001
    funding_mask = np.zeros(n_bars, dtype=np.bool_)
    funding_mask[3] = True
    prepared = _quantbt_native.FullPreparedMarketCore(
        index.asi8,
        opens[:, None],
        highs[:, None],
        lows[:, None],
        close[:, None],
        volume[:, None],
        funding[:, None],
        funding_mask,
    )
    return prepared, close


def _tape(n_bars: int = 6):
    ptr = np.zeros(n_bars + 1, dtype=np.int64)
    ptr[2:] = 1
    ptr[3:] = 2
    codes = np.full((2, 16), -1, dtype=np.int64)
    values = np.zeros((2, 3), dtype=np.float64)
    expiry = np.full(2, -1, dtype=np.int64)

    # PLACE long one unit at bar 1, then reduce-only exit at bar 2.
    codes[0] = [0, 0, 1, 0, 0, 0, 11, -1, -1, -1, -1, 0, 0, 0, 0, 0]
    values[0, 0] = 1.0
    codes[1] = [0, 0, -1, 0, 0, 1, 12, -1, -1, -1, -1, 0, 1, 0, 0, 0]
    values[1, 0] = 1.0
    return ptr, np.ascontiguousarray(codes), np.ascontiguousarray(values), expiry


def _account_arrays():
    return (
        np.array([1.0], dtype=np.float64),
        np.array([5.0], dtype=np.float64),
        np.array([0.0002], dtype=np.float64),
    )


def _request(prepared, *, output_profile: int = 2):
    import _quantbt_native

    ptr, codes, values, expiry = _tape()
    contract_sizes, leverages, fee_rates = _account_arrays()
    return _quantbt_native.NativeExecutionRequestCore.from_command_tape(
        prepared,
        ptr,
        codes,
        values,
        expiry,
        contract_sizes,
        leverages,
        fee_rates,
        10_000.0,
        0.005,
        0.0001,
        True,
        event_contract_code=NEXT_OPEN,
        output_profile=output_profile,
    )


def _session(prepared):
    import _quantbt_native

    contract_sizes, leverages, fee_rates = _account_arrays()
    session = _quantbt_native.FullReactiveSessionCore.from_prepared(
        prepared,
        contract_sizes,
        leverages,
        fee_rates,
        10_000.0,
        0.005,
        0.0001,
        True,
    )
    session.set_event_contract(NEXT_OPEN)
    return session


def test_typed_command_request_matches_api04_full_session_and_reuses_fresh_account():
    prepared, _ = _prepared()
    request = _request(prepared, output_profile=2)
    ptr, codes, values, expiry = _tape()
    direct = _session(prepared).run_tape_audit(ptr, codes, values, expiry)

    first = request.execute()
    second = request.execute()
    assert request.request_version == 1
    assert request.protocol_version == 1
    assert request.workload_kind == "command_tape_v5"
    assert request.output_profile == "audit"
    assert request.command_count == 2
    assert request.bars == 6
    assert len(request.fingerprint) == 64
    assert first["native_execution_request_fingerprint"] == request.fingerprint
    assert first["native_execution_workload"] == "command_tape_v5"
    assert first["native_execution_output_profile"] == "audit"
    assert first["python_callbacks"] == 0
    assert first["boundary_calls"] == 1

    for key in (
        "equity",
        "positions",
        "fees",
        "turnover",
        "funding",
        "initial_margin",
        "maintenance_margin",
        "fill_bar",
        "fill_order_id",
        "fill_symbol",
        "fill_side",
        "fill_qty",
        "fill_price",
        "fill_fee",
        "event_bar",
        "event_kind",
        "event_status",
    ):
        np.testing.assert_allclose(first[key], direct[key], rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(second[key], first[key], rtol=0.0, atol=1e-12)
    for key in (
        "total_fee",
        "total_turnover",
        "total_funding",
        "fill_count",
        "event_count",
        "rejected_count",
        "canceled_count",
        "liquidated",
        "liquidation_bar",
        "liquidation_reason",
    ):
        assert first[key] == direct[key]
        assert second[key] == first[key]
    assert first["final_equity"] == pytest.approx(float(direct["equity"][-1]), abs=1e-12)
    np.testing.assert_allclose(
        first["final_positions"],
        np.asarray(direct["positions"])[-1:],
        rtol=0.0,
        atol=1e-12,
    )


def test_typed_request_score_omits_paths_and_fingerprint_covers_volume_and_funding():
    prepared, _ = _prepared()
    score = _request(prepared, output_profile=0)
    payload = score.execute()
    assert score.output_profile == "score"
    assert "equity" not in payload
    assert "fill_bar" not in payload

    # Volume and funding do not have to affect this particular trade outcome,
    # but both must invalidate a prepared-request fingerprint.
    import _quantbt_native

    index = pd.date_range("2025-01-01", periods=6, freq="1h", tz="UTC")
    close = np.ascontiguousarray(100.0 + np.arange(6, dtype=np.float64))
    base_volume = np.ascontiguousarray(10.0 + np.arange(6, dtype=np.float64))
    changed_volume = base_volume.copy()
    changed_volume[2] += 1.0
    funding = np.zeros(6, dtype=np.float64)
    funding_mask = np.zeros(6, dtype=np.bool_)
    funding_mask[3] = True
    volume_changed = _quantbt_native.FullPreparedMarketCore(
        index.asi8,
        close[:, None],
        (close + 1.0)[:, None],
        (close - 1.0)[:, None],
        close[:, None],
        changed_volume[:, None],
        funding[:, None],
        funding_mask,
    )
    assert _request(volume_changed, output_profile=0).fingerprint != score.fingerprint

    changed_funding = funding.copy()
    changed_funding[3] = 0.0002
    funding_changed = _quantbt_native.FullPreparedMarketCore(
        index.asi8,
        close[:, None],
        (close + 1.0)[:, None],
        (close - 1.0)[:, None],
        close[:, None],
        base_volume[:, None],
        changed_funding[:, None],
        funding_mask,
    )
    assert _request(funding_changed, output_profile=0).fingerprint != score.fingerprint


def test_typed_ir_request_compiles_once_and_matches_full_session_ir_path():
    import _quantbt_native

    prepared, _ = _prepared()
    program = _quantbt_native.NativeStrategyProgramCore(
        1,  # grid_level
        quantity=0.5,
        dca_period=1,
        max_levels=3,
    )
    signal = np.array([0.0, 1.0, 2.0, 1.0, 0.0, 0.0], dtype=np.float64)
    contract_sizes, leverages, fee_rates = _account_arrays()
    request = _quantbt_native.NativeExecutionRequestCore.from_strategy_ir(
        prepared,
        program,
        signal,
        contract_sizes,
        leverages,
        fee_rates,
        10_000.0,
        0.005,
        0.0001,
        True,
        event_contract_code=NEXT_OPEN,
        output_profile=2,
    )
    typed = request.execute()
    direct = _session(prepared).run_ir_audit(program, signal)

    assert request.workload_kind == "strategy_ir_v1"
    assert request.command_count == direct["strategy_ir_command_count"]
    for key in ("equity", "positions", "fees", "turnover", "fill_price", "event_kind"):
        np.testing.assert_allclose(typed[key], direct[key], rtol=0.0, atol=1e-12)
    assert typed["final_equity"] == direct["final_equity"]


def test_typed_request_rejects_unknown_contract_and_bad_flat_tape_before_execution():
    import _quantbt_native

    prepared, _ = _prepared()
    ptr, codes, values, expiry = _tape()
    contract_sizes, leverages, fee_rates = _account_arrays()
    with pytest.raises(ValueError, match="contract code"):
        _quantbt_native.NativeExecutionRequestCore.from_command_tape(
            prepared,
            ptr,
            codes,
            values,
            expiry,
            contract_sizes,
            leverages,
            fee_rates,
            10_000.0,
            0.005,
            0.0001,
            False,
            event_contract_code=999,
        )
    with pytest.raises(ValueError, match="length"):
        _quantbt_native.NativeExecutionRequestCore.from_command_tape(
            prepared,
            np.array([0, 1], dtype=np.int64),
            codes,
            values,
            expiry,
            contract_sizes,
            leverages,
            fee_rates,
            10_000.0,
            0.005,
            0.0001,
            False,
        )


def test_api04_static_route_is_locked_to_the_typed_command_tape_translator():
    root = Path(__file__).parents[2]
    source = (root / "rust" / "native_event" / "src" / "lib.rs").read_text()
    assert "let tape = translate_full_command_tape(" in source
    assert "session.run_typed_score(&tape)" in source
    assert "session.run_typed_compact(&tape)" in source
    assert "session.run_typed_audit(&tape)" in source
