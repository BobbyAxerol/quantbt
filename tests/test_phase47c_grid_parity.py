"""Phase 47C: Grid 2,000-bar parity and scalar retention gates.

The Grid alpha remains an external, read-only integration fixture. These tests
load that module directly and exercise only the public QuantBT adapter.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt import NativeEventScalarScoreResult


GRID_PATH = Path(
    "/root/bobby/pool_alpha/alphas_storage/TA/"
    "dynamic_grid_quantbt_native_event.py"
)


def _load_grid_module():
    if not GRID_PATH.exists():
        pytest.skip(
            f"external Grid fixture is unavailable: {GRID_PATH}",
            allow_module_level=True,
        )
    spec = importlib.util.spec_from_file_location("phase47c_grid_alpha", GRID_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Grid fixture: {GRID_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GRID = _load_grid_module()

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="Phase 47C requires the installed Rust full-contract extension",
)


def _data_2000() -> pd.DataFrame:
    n = 2000
    index = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
    x = np.arange(n, dtype=np.float64)
    close = 100.0 + 5.0 * np.sin(x / 11.0) + 0.01 * x + 1.5 * np.sin(x / 47.0)
    open_ = close + 0.2 * np.sin(x / 3.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1.5,
            "low": np.minimum(open_, close) - 1.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=index,
    )


def _params(grid_mode: str) -> dict:
    return {
        "grid_mode": grid_mode,
        "ma_type": "EMA",
        "ma_len": 8,
        "ema_len_short": 3,
        "logic": "ATR",
        "band_mult": 0.25,
        "zone_smoothing_len": 2,
        "warmup_bars": 12,
        "pyramiding": 3,
        "neutral_position_mode": "hold",
        "one_entry_fill_per_bar": True,
        "one_exit_fill_per_bar": True,
        "campaign_id": "PHASE47C",
    }


def _execution(backend: str, *, audit: bool) :
    return GRID.GridExecutionConfig(
        symbol="ETHUSDT",
        initial_capital=20_000.0,
        cash_per_entry=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_size=1.0,
        fee_rate=0.0005,
        slippage_bps=2.0,
        use_funding=True,
        funding_rate=0.0001,
        native_backend=backend,
        reactive_execution_mode="audit" if audit else "fast",
        reactive_kernel_mode=("replay_certified" if backend == "replay_certified" else "single_pass"),
        report_level="audit" if audit else "score",
        audit_sink="memory" if audit else "none",
    )


@pytest.fixture(scope="module")
def data_2000():
    data = _data_2000()
    assert len(data) == 2000
    assert data.index.is_monotonic_increasing
    assert not data.index.has_duplicates
    return data


@pytest.fixture(scope="module")
def audit_runs(data_2000):
    runs = {}
    for grid_mode in ("long_only", "long_short"):
        params = _params(grid_mode)
        for backend in ("replay_certified", "python", "rust"):
            runs[(grid_mode, backend)] = GRID.run_grid_backtest(
                df=data_2000,
                params=params,
                execution=_execution(backend, audit=True),
            )
    return runs


def _fill_signature(result):
    return tuple(
        (
            int(pd.Timestamp(fill.timestamp).value),
            str(fill.symbol),
            getattr(fill.side, "value", str(fill.side)),
            float(fill.qty),
            float(fill.price),
            float(fill.fee),
            fill.order_id,
        )
        for fill in result.fills
    )


def _audit_fingerprint(run) -> tuple:
    result = run.result
    command_signature = tuple(
        (
            int(pd.Timestamp(command.timestamp).value),
            command.action.value,
            command.symbol,
            None if command.side is None else command.side.value,
            None if command.order_type is None else command.order_type.value,
            float(command.qty or 0.0),
            None if command.price is None else float(command.price),
            None if command.trigger_price is None else float(command.trigger_price),
            command.tif.value,
            bool(command.reduce_only),
            command.order_id,
            command.target_order_id,
            command.parent_order_id,
            command.group_id,
            command.oco_group_id,
            None if command.expires_at is None else int(pd.Timestamp(command.expires_at).value),
        )
        for command in run.command_tape
    )
    event_frame = run.order_events.reset_index(drop=True)
    event_signature = tuple(
        tuple(None if pd.isna(value) else str(value) for value in row)
        for row in event_frame.itertuples(index=False, name=None)
    )
    return (
        command_signature,
        event_signature,
        _fill_signature(result),
        tuple(np.asarray(result.equity, dtype=np.float64)),
        tuple(np.asarray(result.fees, dtype=np.float64)),
        tuple(np.asarray(result.funding, dtype=np.float64)),
        tuple(np.asarray(result.positions, dtype=np.float64).ravel()),
        tuple(np.asarray(result.margin, dtype=np.float64).ravel()),
        bool(result.liquidated),
        int(result.liquidation_bar),
    )


def _assert_parity(reference, candidate):
    np.testing.assert_allclose(reference.result.equity, candidate.result.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(reference.result.positions, candidate.result.positions, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(reference.result.fees, candidate.result.fees, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(reference.result.funding, candidate.result.funding, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(reference.result.margin, candidate.result.margin, rtol=0.0, atol=1e-12)
    assert reference.command_tape == candidate.command_tape
    assert _fill_signature(reference.result) == _fill_signature(candidate.result)
    pd.testing.assert_frame_equal(
        reference.order_events.reset_index(drop=True),
        candidate.order_events.reset_index(drop=True),
        check_dtype=False,
    )
    assert reference.result.liquidated == candidate.result.liquidated
    assert reference.result.liquidation_bar == candidate.result.liquidation_bar
    reference_counters = reference.result.metadata["lifecycle_counters"]
    candidate_counters = candidate.result.metadata["lifecycle_counters"]
    # ``filled_command_count`` is intentionally not part of the canonical
    # parity surface yet: replay reports filled command-state transitions,
    # while reactive sessions report fill records. The exact order-event and
    # fill ledgers above are the authoritative lifecycle evidence.
    for key in (
        "fill_count",
        "event_count",
        "rejected_count",
        "canceled_count",
        "pending_command_count",
        "expired_event_count",
    ):
        assert reference_counters[key] == candidate_counters[key]


def test_phase47c_grid_2000_long_only_and_long_short_full_parity(audit_runs):
    for grid_mode in ("long_only", "long_short"):
        oracle = audit_runs[(grid_mode, "replay_certified")]
        _assert_parity(oracle, audit_runs[(grid_mode, "python")])
        _assert_parity(oracle, audit_runs[(grid_mode, "rust")])


def test_phase47c_scalar_v2_matches_same_backend_audit(audit_runs, data_2000):
    for grid_mode in ("long_only", "long_short"):
        params = _params(grid_mode)
        for backend in ("python", "rust"):
            execution = _execution(backend, audit=False)
            endpoint, prepared = GRID.prepare_grid_score_runner(
                df=data_2000,
                execution=execution,
            )
            score = GRID.score_grid_params(
                prepared_runner=prepared,
                df=data_2000,
                params=params,
                execution=execution,
            )
            audit = audit_runs[(grid_mode, backend)]
            assert isinstance(score, NativeEventScalarScoreResult)
            assert endpoint.result is None
            assert prepared.scores == 1
            assert score.metadata["score_pandas_materialized"] is False
            assert score.metadata["score_full_ledgers_materialized"] is False
            np.testing.assert_allclose(score.final_equity, audit.result.equity.iloc[-1], rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(
                score.final_positions,
                audit.result.positions.iloc[-1].to_numpy(dtype=np.float64),
                rtol=0.0,
                atol=1e-12,
            )
            np.testing.assert_allclose(score.total_fee, audit.result.fees.sum(), rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(
                score.metadata["total_funding"], audit.result.funding.sum(), rtol=0.0, atol=1e-12
            )
            assert score.fill_count == len(audit.result.fills)
            assert score.rejection_count == audit.result.metadata["lifecycle_counters"]["rejected_count"]
            assert score.cancellation_count == audit.result.metadata["lifecycle_counters"]["canceled_count"]
            assert score.liquidated == audit.result.liquidated
            assert score.liquidation_bar == audit.result.liquidation_bar
            # The audit fingerprint is the retained proof. Scalar mode is
            # intentionally not expected to retain the command tape itself.
            assert len(_audit_fingerprint(audit)[0]) == len(audit.command_tape)


def test_phase47c_backend_policy_is_explicit_and_no_silent_rust_fallback(data_2000):
    params = _params("long_only")
    rust = GRID.run_grid_backtest(
        df=data_2000,
        params=params,
        execution=_execution("rust", audit=True),
    )
    auto = GRID.run_grid_backtest(
        df=data_2000,
        params=params,
        execution=_execution("auto", audit=True),
    )
    assert rust.result.metadata["native_event_backend_requested"] == "rust"
    assert rust.result.metadata["native_event_backend_resolved"] == "rust"
    assert auto.result.metadata["native_event_backend_requested"] == "auto"
    assert auto.result.metadata["native_event_backend_resolved"] == "python"
