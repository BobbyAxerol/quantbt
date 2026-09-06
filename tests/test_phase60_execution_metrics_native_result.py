"""Phase 60 contracts: execution retention, metrics, and NativeResult V2."""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt.core.native_result_v2 import NativeResultV2Adapter


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


NEXT_OPEN = 3


def _prepared(n_bars: int = 12):
    import _quantbt_native

    index = pd.date_range("2026-08-01", periods=n_bars, freq="1h", tz="UTC")
    close = np.ascontiguousarray(100.0 + np.arange(n_bars, dtype=np.float64))
    return _quantbt_native.FullPreparedMarketCore(
        np.ascontiguousarray(index.asi8, dtype=np.int64),
        np.ascontiguousarray(close[:, None]),
        np.ascontiguousarray((close + 1.0)[:, None]),
        np.ascontiguousarray((close - 1.0)[:, None]),
        np.ascontiguousarray(close[:, None]),
        np.ascontiguousarray(np.full((n_bars, 1), 100.0, dtype=np.float64)),
        np.zeros((n_bars, 1), dtype=np.float64),
        np.zeros(n_bars, dtype=np.bool_),
    )


def _tape(n_bars: int = 12):
    # A sequence of full reversals creates enough fill/event rows to prove
    # bounded audit retention without changing terminal accounting.
    command_count = n_bars - 1
    ptr = np.zeros(n_bars + 1, dtype=np.int64)
    ptr[1:] = np.arange(command_count + 1, dtype=np.int64)
    codes = np.full((command_count, 16), -1, dtype=np.int64)
    values = np.zeros((command_count, 3), dtype=np.float64)
    expiry = np.full(command_count, -1, dtype=np.int64)
    for bar in range(1, n_bars):
        command = bar - 1
        codes[command] = [
            0,  # place
            0,  # BTC symbol column
            1 if bar % 2 else -1,
            0,  # market
            0,  # GTC
            0,  # not reduce-only
            1_000 + command,
            -1,
            -1,
            -1,
            -1,
            0,
            command,
            0,
            0,
            0,
        ]
        values[command, 0] = 1.0
    return ptr, np.ascontiguousarray(codes), np.ascontiguousarray(values), expiry


def _request(prepared, *, output_profile: int):
    import _quantbt_native

    ptr, codes, values, expiry = _tape()
    return _quantbt_native.NativeExecutionRequestCore.from_command_tape(
        prepared,
        ptr,
        codes,
        values,
        expiry,
        np.array([1.0], dtype=np.float64),
        np.array([5.0], dtype=np.float64),
        np.array([0.0005], dtype=np.float64),
        10_000.0,
        0.005,
        0.0002,
        False,
        event_contract_code=NEXT_OPEN,
        output_profile=output_profile,
    )


def test_phase60_score_compact_audit_share_native_result_v2_terminal_and_metric_contract():
    prepared = _prepared()
    score = _request(prepared, output_profile=0).execute_typed()
    compact = _request(prepared, output_profile=1).execute_typed()
    audit = _request(prepared, output_profile=2).execute_typed()

    assert score.native_result_version == compact.native_result_version == audit.native_result_version == 2
    assert score.execution_model_id == compact.execution_model_id == audit.execution_model_id == "bar_touch_v1"
    assert score.terminal_fingerprint == compact.terminal_fingerprint == audit.terminal_fingerprint
    assert score.contract_bundle_hash == compact.contract_bundle_hash == audit.contract_bundle_hash
    assert score.detail_truncated is False
    assert compact.detail_truncated is False
    assert audit.detail_truncated is False
    assert score.output_profile == "score"
    assert not hasattr(score, "equity")
    assert not hasattr(compact, "fill_bar")
    assert hasattr(audit, "fill_bar")

    metrics = score.metrics
    assert metrics["native_metric_contract_version"] == 2
    assert metrics["native_metric_return_frequency"] == "daily"
    assert np.isfinite(metrics["native_metric_total_return"])
    assert np.isfinite(metrics["native_metric_sharpe"])
    assert metrics["native_metric_total_fee"] == pytest.approx(score.total_fee)
    assert metrics["native_metric_fill_count"] == score.fill_count

    score_adapter = NativeResultV2Adapter(score.as_dict())
    assert score_adapter.materialized_frames == ()
    assert score_adapter.metrics["sharpe"] == pytest.approx(metrics["native_metric_sharpe"])
    assert score_adapter.materialized_frames == ()
    with pytest.raises(ValueError, match="score profile"):
        score_adapter.to_pandas()

    raw_score_adapter = NativeResultV2Adapter(score)
    assert raw_score_adapter.header.metric_contract_version == 2
    assert raw_score_adapter.header.runtime_class == "whole_run_native"
    assert raw_score_adapter.metrics["total_fee"] == pytest.approx(score.total_fee)

    audit_adapter = NativeResultV2Adapter(audit.as_dict(), max_cached_frames=2)
    paths = audit_adapter.to_pandas()
    fills = audit_adapter.fills_dataframe()
    events = audit_adapter.audit_events()
    assert len(paths) == 12
    assert len(fills) + len(events) == audit.retained_rows
    assert audit_adapter.orders_dataframe() is events
    assert audit_adapter.materialized_frames == ("fills", "events")


def test_phase60_audit_retention_is_bounded_fingerprinted_and_does_not_change_terminal_state():
    prepared = _prepared()
    full_request = _request(prepared, output_profile=2)
    capped_request = full_request.with_audit_detail_limit(2)
    assert capped_request.audit_detail_row_limit == 2
    assert capped_request.fingerprint != full_request.fingerprint

    full = full_request.execute_typed()
    capped = capped_request.execute_typed()
    assert capped.detail_truncated is True
    assert capped.retained_rows == 2
    assert capped.dropped_rows > 0
    assert capped.terminal_fingerprint == full.terminal_fingerprint
    assert capped.final_equity == pytest.approx(full.final_equity, abs=1e-12)
    assert capped.total_fee == pytest.approx(full.total_fee, abs=1e-12)
    assert capped.fill_count == full.fill_count
    assert capped.event_count == full.event_count

    payload = capped.as_dict()
    retained = len(payload["fill_bar"]) + len(payload["event_bar"])
    assert retained == capped.retained_rows
    assert retained + capped.dropped_rows >= capped.fill_count + capped.event_count


def test_phase60_explicit_audit_retention_rejects_non_audit_profiles():
    prepared = _prepared()
    score_request = _request(prepared, output_profile=0)
    with pytest.raises(ValueError, match="only valid for audit"):
        score_request.with_audit_detail_limit(10)
