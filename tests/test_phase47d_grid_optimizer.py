"""Phase 47D: safe Grid optimizer hot-path and retention gates."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt import NativeEventScoreRequirements, NativeEventScalarScoreResult


GRID_PATH = Path(
    "/root/bobby/pool_alpha/alphas_storage/TA/"
    "dynamic_grid_quantbt_native_event.py"
)


def _grid_fixture_is_readable() -> bool:
    try:
        return GRID_PATH.is_file()
    except OSError:
        return False


def _load_grid_module():
    if not _grid_fixture_is_readable():
        pytest.skip(
            f"external Grid fixture is unavailable or unreadable: {GRID_PATH}",
            allow_module_level=True,
        )
    spec = importlib.util.spec_from_file_location("phase47d_grid_alpha", GRID_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Grid fixture: {GRID_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GRID = _load_grid_module()


def _data(bars: int = 240) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=bars, freq="h", tz="UTC")
    x = np.arange(bars, dtype=np.float64)
    close = 100.0 + 3.5 * np.sin(x / 7.0) + 0.025 * x
    open_ = close + 0.15 * np.sin(x / 3.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1.2,
            "low": np.minimum(open_, close) - 1.2,
            "close": close,
            "volume": np.full(bars, 1000.0),
        },
        index=index,
    )


def _params() -> dict:
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
        "campaign_id": "PHASE47D",
    }


def _execution(*, collect_diagnostics: bool = True):
    return GRID.GridExecutionConfig(
        symbol="ETHUSDT",
        initial_capital=20_000.0,
        cash_per_entry=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.0,
        contract_size=1.0,
        fee_rate=0.0005,
        slippage_bps=2.0,
        use_funding=False,
        funding_rate=0.0,
        native_backend="python",
        reactive_execution_mode="fast",
        reactive_kernel_mode="single_pass",
        report_level="score",
        audit_sink="none",
        collect_diagnostics=collect_diagnostics,
    )


def test_grid_declares_only_context_payload_it_consumes():
    assert GRID.ReactiveDynamicGridStrategy.native_context_requirements == {
        "fills": True,
        "events": False,
        "active_orders": True,
        "positions": True,
        "margin": False,
    }
    strategy = GRID.build_grid_strategy(
        df=_data(),
        params=_params(),
        execution=_execution(collect_diagnostics=False),
    )
    requirements = NativeEventScoreRequirements.from_strategy(
        strategy,
        base=NativeEventScoreRequirements.scalar_score_contract(),
    )
    assert requirements.need_context_fills is True
    assert requirements.need_context_active_orders is True
    assert requirements.need_context_positions is True
    assert requirements.need_context_events is False
    assert requirements.need_context_margin is False


def test_scalar_strategy_drops_diagnostics_and_alias_columns():
    strategy = GRID.build_grid_strategy(
        df=_data(),
        params=_params(),
        execution=_execution(collect_diagnostics=False),
    )
    assert strategy.collect_diagnostics is False
    for name in (
        "_diag_position_qty",
        "_diag_equity",
        "_diag_open_long_legs",
        "_diag_open_short_legs",
        "_diag_active_entry_orders",
        "_diag_active_exit_orders",
        "_diag_fill_count",
        "_diag_command_count",
    ):
        assert getattr(strategy, name) is None
    assert not any(column.startswith("long_entry_") for column in strategy.alpha_frame)
    assert not any(column.startswith("long_exit_") for column in strategy.alpha_frame)
    assert not any(column.startswith("short_entry_") for column in strategy.alpha_frame)
    assert not any(column.startswith("short_exit_") for column in strategy.alpha_frame)


def test_alias_switch_preserves_execution_columns_and_values():
    data = _data()
    params = _params()
    with_aliases = GRID.prepare_grid_alpha_frame(
        data,
        params,
        include_diagnostic_aliases=True,
    )
    without_aliases = GRID.prepare_grid_alpha_frame(
        data,
        params,
        include_diagnostic_aliases=False,
    )
    assert set(without_aliases.columns).issubset(with_aliases.columns)
    for column in without_aliases.columns:
        pd.testing.assert_series_equal(
            with_aliases[column],
            without_aliases[column],
            check_names=True,
        )


def test_score_helper_uses_scalar_gate_and_keeps_public_endpoint_empty():
    data = _data()
    execution = _execution()
    endpoint, prepared = GRID.prepare_grid_score_runner(
        df=data,
        execution=execution,
    )
    before_scores = prepared.scores
    before_runs = prepared.runs
    score = GRID.score_grid_params(
        prepared_runner=prepared,
        df=data,
        params=_params(),
        execution=execution,
    )
    assert isinstance(score, NativeEventScalarScoreResult)
    assert prepared.scores == before_scores + 1
    assert prepared.runs == before_runs
    assert endpoint.result is None
    assert score.metadata["score_pandas_materialized"] is False
    assert score.metadata["score_full_ledgers_materialized"] is False


def test_scalar_score_matches_public_accounting_and_false_mode_has_no_frame():
    data = _data()
    params = _params()
    public = GRID.run_grid_backtest(
        df=data,
        params=params,
        execution=replace(
            _execution(collect_diagnostics=True),
            report_level="audit",
            audit_sink="memory",
        ),
    )
    endpoint, prepared = GRID.prepare_grid_score_runner(
        df=data,
        execution=_execution(collect_diagnostics=True),
    )
    scalar = GRID.score_grid_params(
        prepared_runner=prepared,
        df=data,
        params=params,
        execution=_execution(collect_diagnostics=True),
    )
    np.testing.assert_allclose(
        scalar.final_equity,
        public.result.equity.iloc[-1],
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        scalar.total_fee,
        public.result.fees.sum(),
        rtol=0.0,
        atol=1e-12,
    )
    assert scalar.fill_count == len(public.result.fills)
    assert endpoint.result is None

    score_execution = replace(_execution(), collect_diagnostics=False)
    score_strategy = GRID.build_grid_strategy(
        df=data,
        params=params,
        execution=score_execution,
    )
    score_endpoint = GRID.build_grid_endpoint(score_execution)
    score_result = score_endpoint.simulate(
        data=data,
        strategy=score_strategy,
        symbols=[score_execution.symbol],
    )
    with pytest.raises(RuntimeError, match="collect_diagnostics=True"):
        score_strategy.build_output_frame(score_result)
