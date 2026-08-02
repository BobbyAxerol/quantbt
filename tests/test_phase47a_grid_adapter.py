"""Phase 47A integration tests for the external Grid alpha adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from quantbt import NativeEventScoreRequirements
from quantbt.core.results import NativeEventScalarScoreResult


GRID_PATH = Path(
    "/root/bobby/pool_alpha/alphas_storage/TA/"
    "dynamic_grid_quantbt_native_event.py"
)


@pytest.fixture(scope="module")
def grid_module():
    if not GRID_PATH.exists():
        pytest.skip(f"external Grid module is not available: {GRID_PATH}")

    module_name = "phase47a_dynamic_grid_quantbt_native_event"
    spec = importlib.util.spec_from_file_location(module_name, GRID_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load Grid module from {GRID_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def grid_data() -> pd.DataFrame:
    index = pd.date_range(
        "2025-01-01",
        periods=240,
        freq="h",
        tz="UTC",
    )
    x = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 3.5 * np.sin(x / 7.0) + 0.025 * x
    open_ = close + 0.15 * np.sin(x / 3.0)
    high = np.maximum(open_, close) + 1.2
    low = np.minimum(open_, close) - 1.2
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(len(index), 1000.0),
        },
        index=index,
    )


@pytest.fixture(scope="module")
def grid_params() -> dict:
    return {
        "grid_mode": "long_only",
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
        "campaign_id": "PHASE47A",
    }


def _execution(module, *, backend: str, report_level: str):
    return module.GridExecutionConfig(
        symbol="ETHUSDT",
        initial_capital=20_000.0,
        cash_per_entry=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.0,
        contract_size=1.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        use_funding=False,
        funding_rate=0.0,
        native_backend=backend,
        reactive_execution_mode="fast",
        reactive_kernel_mode=(
            "replay_certified"
            if backend == "replay_certified"
            else "single_pass"
        ),
        report_level=report_level,
        audit_sink="none",
    )


def test_grid_native_backend_selector_is_validated_and_forwarded(grid_module):
    for selected in ("python", "rust", "auto", "replay_certified"):
        execution = _execution(
            grid_module,
            backend=selected,
            report_level="score",
        )
        assert execution.native_backend == selected
        endpoint = grid_module.build_grid_endpoint(execution)
        assert endpoint.config.native_backend == selected

    with pytest.raises(ValueError, match="native_backend"):
        _execution(grid_module, backend="unsupported", report_level="score")


def test_grid_prepare_and_scalar_score_do_not_materialize_public_result(
    grid_module,
    grid_data,
    grid_params,
):
    execution = _execution(
        grid_module,
        backend="python",
        report_level="score",
    )
    endpoint, prepared = grid_module.prepare_grid_score_runner(
        df=grid_data,
        execution=execution,
    )

    assert prepared.endpoint is endpoint
    assert prepared.scores == 0
    assert endpoint.result is None

    score = grid_module.score_grid_params(
        prepared_runner=prepared,
        df=grid_data,
        params=grid_params,
        execution=execution,
        trading_days=365,
    )

    assert isinstance(score, NativeEventScalarScoreResult)
    assert prepared.scores == 1
    assert prepared.runs == 0
    assert endpoint.result is None
    assert score.metadata["score_pandas_materialized"] is False
    assert score.metadata["score_full_ledgers_materialized"] is False

    second = grid_module.score_grid_params(
        prepared_runner=prepared,
        df=grid_data,
        params=grid_params,
        execution=execution,
        trading_days=365,
    )
    assert prepared.scores == 2
    assert endpoint.result is None
    assert second.final_equity == pytest.approx(score.final_equity)
    assert second.fill_count == score.fill_count
    assert second.metrics["num_trades"] == score.metrics["num_trades"]


def test_grid_public_run_still_returns_reportable_result(
    grid_module,
    grid_data,
    grid_params,
):
    execution = _execution(
        grid_module,
        backend="python",
        report_level="minimal",
    )
    run = grid_module.run_grid_backtest(
        df=grid_data,
        params=grid_params,
        execution=execution,
    )

    assert run.result is run.endpoint.result
    assert len(run.result.equity) == len(grid_data)
    assert len(run.frame) == len(grid_data)
    report = run.result.full_report(
        trading_days=365,
        scope="full",
    )
    assert report["initial_capital"] == pytest.approx(20_000.0)
    assert "final_equity" in report


def test_grid_python_single_pass_matches_replay_baseline(
    grid_module,
    grid_data,
    grid_params,
):
    oracle = grid_module.run_grid_backtest(
        df=grid_data,
        params=grid_params,
        execution=_execution(
            grid_module,
            backend="replay_certified",
            report_level="audit",
        ),
    )
    candidate = grid_module.run_grid_backtest(
        df=grid_data,
        params=grid_params,
        execution=_execution(
            grid_module,
            backend="python",
            report_level="audit",
        ),
    )

    np.testing.assert_array_equal(
        oracle.result.positions.to_numpy(dtype=np.float64),
        candidate.result.positions.to_numpy(dtype=np.float64),
    )
    np.testing.assert_allclose(
        oracle.result.equity.to_numpy(dtype=np.float64),
        candidate.result.equity.to_numpy(dtype=np.float64),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        oracle.result.fees.to_numpy(dtype=np.float64),
        candidate.result.fees.to_numpy(dtype=np.float64),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        oracle.result.funding.to_numpy(dtype=np.float64),
        candidate.result.funding.to_numpy(dtype=np.float64),
        rtol=0.0,
        atol=1e-12,
    )
    assert len(oracle.result.fills) == len(candidate.result.fills)
    assert len(oracle.command_tape) == len(candidate.command_tape)


def test_grid_score_contract_is_public_and_scalar(grid_module):
    contract = NativeEventScoreRequirements.scalar_score_contract()
    assert contract.need_trade_stats is True
    assert contract.need_equity_path is False
    assert contract.need_fill_ledger is False
    assert contract.need_context_fills is True
    assert contract.need_context_active_orders is True
