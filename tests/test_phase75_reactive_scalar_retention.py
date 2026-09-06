"""Phase 75 reactive scalar-retention and Rust hot-state certification.

The public R1/R2/R3 result remains an audit-capable cold path.  Prepared
optimization uses the same Rust lifecycle/accounting session, but keeps no
account path, command rows, callback trace, or terminal active-order report.
These tests lock metric and terminal-account parity against that public path.
"""

from __future__ import annotations

import importlib.util
import math

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    ExecutionConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.backends.native_event import NativeEventScoreRequirements
from quantbt.strategies import BlockPlanV1, WakePlanV1


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(*, bars: int = 96, liquidation: bool = False) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.07 * phase + 0.8 * np.sin(phase / 5.0)
    if liquidation:
        close[2:] = 1.0
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 0.5,
            "low": np.maximum(close - 0.5, 0.01),
            "close": close,
            "volume": np.full(bars, 100.0),
            "funding_rate": np.where(phase % 8 == 0, 0.0001, 0.0),
        },
        index=index,
    )


_NUMERIC = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="snapshot",
    context_mode="numeric",
)


class _EveryBar:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = _NUMERIC

    def on_bar_close(self, context, out) -> None:
        if context.bar_index == 0:
            out.market(0, OrderSide.BUY, 1.0)
        elif context.bar_index == 48:
            out.market(0, OrderSide.SELL, 1.0, reduce_only=True)


class _Sparse:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = _NUMERIC

    def on_wake(self, context, out) -> WakePlanV1:
        if context.bar_index == 0:
            out.market(0, OrderSide.BUY, 1.0)
            return WakePlanV1(next_bar=48)
        if context.bar_index == 48:
            out.market(0, OrderSide.SELL, 1.0, reduce_only=True)
        return WakePlanV1()


class _Block:
    quantbt_reactive_block_intent_v1 = True
    quantbt_block_shadow_certified_v1 = True
    quantbt_requirements = _NUMERIC

    def next_block(self, context, start_bar, max_stop_bar, out) -> BlockPlanV1:
        if context.bar_index == 0:
            out.market(0, OrderSide.BUY, 1.0, effective_bar=start_bar)
            out.market(0, OrderSide.SELL, 1.0, effective_bar=48, reduce_only=True)
        return BlockPlanV1(stop_bar=max_stop_bar, invalidate_on_fill=False)


class _Liquidating:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = _NUMERIC

    def on_bar_close(self, context, out) -> None:
        if context.bar_index == 0:
            out.market(0, OrderSide.BUY, 500.0)


def _endpoint(*, runtime: str, frame: pd.DataFrame, gil_policy: str = "held_for_session"):
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=frame["funding_rate"],
        qty_step=0.25,
        min_qty=0.5,
        min_notional=25.0,
        report_level="audit",
        native_backend="rust",
        reactive_kernel_mode="single_pass",
        reactive_runtime=runtime,
        reactive_gil_policy=gil_policy,
        execution=ExecutionConfig(slippage_bps=1.0),
    )


def _scalar_and_audit(*, runtime: str, strategy_factory, frame: pd.DataFrame, gil_policy: str = "held_for_session"):
    scalar_endpoint = _endpoint(runtime=runtime, frame=frame, gil_policy=gil_policy)
    prepared = scalar_endpoint.prepare_native_event_strategy(data=frame, symbols=["BTC"])
    scalar = prepared.score(
        strategy_factory(),
        score_requirements=NativeEventScoreRequirements.scalar_score_contract(),
    )
    audit = _endpoint(runtime=runtime, frame=frame, gil_policy=gil_policy).simulate(
        data=frame,
        strategy=strategy_factory(),
        symbols=["BTC"],
    )
    return scalar, audit


def _assert_metrics_equal(scalar, audit) -> None:
    report = audit.full_report()
    for key, expected in report.items():
        actual = scalar.metrics[key]
        if isinstance(expected, (float, int, np.floating, np.integer)) and not isinstance(expected, bool):
            if math.isinf(float(expected)):
                assert math.isinf(float(actual))
                assert (float(actual) > 0.0) == (float(expected) > 0.0)
            else:
                np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-10)
        else:
            assert actual == expected
    np.testing.assert_allclose(scalar.final_equity, audit.equity.iloc[-1], rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(
        scalar.final_positions,
        audit.positions.iloc[-1].to_numpy(dtype=np.float64),
        rtol=0.0,
        atol=1e-10,
    )
    np.testing.assert_allclose(scalar.metrics["total_fee"], audit.fees.sum(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(scalar.metrics["total_funding"], audit.funding.sum(), rtol=0.0, atol=1e-10)


@pytest.mark.parametrize(
    ("runtime", "strategy_factory"),
    [
        ("numeric_every_bar_v1", _EveryBar),
        ("numeric_sparse_wake_v1", _Sparse),
        ("numeric_block_intent_v1", _Block),
    ],
)
def test_phase75_scalar_metrics_match_public_rust_reactive_result(runtime, strategy_factory):
    scalar, audit = _scalar_and_audit(
        runtime=runtime,
        strategy_factory=strategy_factory,
        frame=_frame(),
    )

    _assert_metrics_equal(scalar, audit)
    assert scalar.metadata["score_scalar"] is True
    assert scalar.metadata["state_owner"] == "rust"
    assert not hasattr(scalar, "accounting")
    assert all(value is False for value in scalar.metadata["score_retained_paths"].values())
    retention = scalar.metadata["reactive_numeric_observability"]["retention"]
    assert retention == {
        "account_paths": False,
        "command_rows": False,
        "callback_trace": False,
        "terminal_active_orders": False,
    }


def test_phase75_scalar_liquidation_uses_full_tape_cagr_and_keeps_terminal_parity():
    frame = _frame(bars=24, liquidation=True)
    scalar, audit = _scalar_and_audit(
        runtime="numeric_every_bar_v1",
        strategy_factory=_Liquidating,
        frame=frame,
    )
    assert scalar.liquidated is audit.liquidated is True
    assert scalar.liquidation_bar == audit.liquidation_bar
    _assert_metrics_equal(scalar, audit)


def test_phase75_scalar_short_tape_uses_the_python_annualization_contract():
    # Fewer than one daily observation exercises the timestamp-delta fallback
    # rather than a daily-return annualization shortcut.
    scalar, audit = _scalar_and_audit(
        runtime="numeric_every_bar_v1",
        strategy_factory=_EveryBar,
        frame=_frame(bars=12),
    )
    _assert_metrics_equal(scalar, audit)


def test_phase75_scalar_gil_policies_preserve_metrics_and_keep_hot_state_bounded():
    frame = _frame()
    held, _ = _scalar_and_audit(
        runtime="numeric_every_bar_v1",
        strategy_factory=_EveryBar,
        frame=frame,
        gil_policy="held_for_session",
    )
    released, _ = _scalar_and_audit(
        runtime="numeric_every_bar_v1",
        strategy_factory=_EveryBar,
        frame=frame,
        gil_policy="release_between_callbacks",
    )
    for key in held.metrics:
        if isinstance(held.metrics[key], (float, int, np.floating, np.integer)) and not isinstance(held.metrics[key], bool):
            np.testing.assert_allclose(held.metrics[key], released.metrics[key], rtol=0.0, atol=1e-10)
    held_observability = held.metadata["reactive_numeric_observability"]
    released_observability = released.metadata["reactive_numeric_observability"]
    assert held_observability["gil_acquisitions"] == 1
    assert released_observability["gil_acquisitions"] > held_observability["gil_acquisitions"]
    assert held_observability["command_rows"] == released_observability["command_rows"] == 2
