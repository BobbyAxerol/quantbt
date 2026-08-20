"""Phase 54A.5.2 typed native execution-request conformance.

The frozen API-0.4 arrays remain accepted by ``FullReactiveSessionCore``.
They must now be translated once to ABI-0.5 ``CommandTapeV5`` before the one
authoritative ``FullSession`` lifecycle runs.  The additive request class locks
that same path for immutable static and strategy-IR workloads.
"""

from __future__ import annotations

import gc
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


def test_typed_outputs_are_profiled_soa_and_match_the_legacy_cold_adapter():
    import _quantbt_native

    shared_score_keys = (
        "final_equity",
        "total_fee",
        "total_turnover",
        "total_funding",
        "fill_count",
        "event_count",
        "rejected_count",
        "canceled_count",
        "max_initial_margin",
        "max_maintenance_margin",
        "liquidated",
        "liquidation_bar",
        "liquidation_reason",
    )
    path_keys = (
        "equity",
        "positions",
        "fees",
        "turnover",
        "funding",
        "initial_margin",
        "maintenance_margin",
    )
    detail_keys = (
        "fill_bar",
        "fill_order_id",
        "fill_symbol",
        "fill_side",
        "fill_qty",
        "fill_price",
        "fill_fee",
        "fill_reason",
        "fill_ambiguity",
        "event_bar",
        "event_kind",
        "event_status",
        "event_order_id",
        "event_target_id",
        "event_symbol",
        "event_reject_code",
    )

    score_request = _request(_prepared()[0], output_profile=0)
    score = score_request.execute_typed()
    score_legacy = score_request.execute()
    assert isinstance(score, _quantbt_native.NativeScoreOutputV1)
    assert not isinstance(score, dict)
    assert score.output_version == 1
    assert score.output_profile == "score"
    assert score.bars == 6
    assert not hasattr(score, "equity")
    assert score.final_positions.dtype == np.float64
    assert score.final_positions.flags.c_contiguous
    assert score.output_bytes == score.final_positions.nbytes
    score_dict = score.as_dict()
    assert score_dict["native_execution_passes"] == 1
    assert score_dict["native_execution_buffer_transfer"] == "rust_vec_to_numpy_zero_copy"
    for key in shared_score_keys:
        assert getattr(score, key) == score_legacy[key]
        assert score_dict[key] == score_legacy[key]
    np.testing.assert_allclose(score.final_positions, score_legacy["final_positions"])

    compact_request = _request(_prepared()[0], output_profile=1)
    compact = compact_request.execute_typed()
    compact_legacy = compact_request.execute()
    assert isinstance(compact, _quantbt_native.NativeCompactOutputV1)
    assert compact.output_profile == "compact"
    assert not hasattr(compact, "fill_bar")
    for key in path_keys:
        value = getattr(compact, key)
        assert isinstance(value, np.ndarray)
        assert value.flags.c_contiguous
        np.testing.assert_allclose(value, compact_legacy[key], rtol=0.0, atol=1e-12)
    compact_dict = compact.as_dict()
    for key in shared_score_keys:
        assert getattr(compact, key) == compact_legacy[key]
        assert compact_dict[key] == compact_legacy[key]
    assert compact.output_bytes == sum(
        getattr(compact, key).nbytes for key in ("final_positions", *path_keys)
    )

    audit_request = _request(_prepared()[0], output_profile=2)
    audit = audit_request.execute_typed()
    audit_legacy = audit_request.execute()
    assert isinstance(audit, _quantbt_native.NativeAuditOutputV1)
    assert audit.output_profile == "audit"
    for key in (*path_keys, *detail_keys):
        value = getattr(audit, key)
        assert isinstance(value, np.ndarray)
        assert value.flags.c_contiguous
        np.testing.assert_allclose(value, audit_legacy[key], rtol=0.0, atol=1e-12)
    for key in ("fill_bar", "fill_order_id", "event_bar", "event_kind"):
        assert getattr(audit, key).dtype == np.int64
    audit_dict = audit.as_dict()
    for key in shared_score_keys:
        assert getattr(audit, key) == audit_legacy[key]
        assert audit_dict[key] == audit_legacy[key]
    assert audit.output_bytes == sum(
        getattr(audit, key).nbytes
        for key in ("final_positions", *path_keys, *detail_keys)
    )


def test_typed_output_numpy_owners_survive_request_gc_and_runner_reuse():
    request = _request(_prepared()[0], output_profile=2)
    first = request.execute_typed()
    first_equity = first.equity
    first_fills = first.fill_price
    expected_equity = first_equity.copy()
    expected_fills = first_fills.copy()

    # A repeated request run creates a fresh Rust session. Its output must not
    # mutate arrays already transferred into the first NumPy-owned result.
    second = request.execute_typed()
    np.testing.assert_allclose(first_equity, expected_equity, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(first_fills, expected_fills, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(second.equity, expected_equity, rtol=0.0, atol=1e-12)

    del request
    gc.collect()
    np.testing.assert_allclose(first_equity, expected_equity, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(first_fills, expected_fills, rtol=0.0, atol=0.0)


def test_typed_audit_empty_columns_are_typed_and_do_not_require_rows():
    prepared, _ = _prepared()
    ptr = np.zeros(7, dtype=np.int64)
    codes = np.empty((0, 16), dtype=np.int64)
    values = np.empty((0, 3), dtype=np.float64)
    expiry = np.empty(0, dtype=np.int64)
    contract_sizes, leverages, fee_rates = _account_arrays()

    import _quantbt_native

    request = _quantbt_native.NativeExecutionRequestCore.from_command_tape(
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
        output_profile=2,
    )
    output = request.execute_typed()
    assert isinstance(output, _quantbt_native.NativeAuditOutputV1)
    assert output.fill_bar.dtype == np.int64
    assert output.event_kind.dtype == np.int64
    assert output.fill_bar.size == 0
    assert output.event_kind.size == 0
    assert output.fill_count == 0
    assert output.event_count == 0
