from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    PackageExecutionKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
    build_arbitrage_order_plan,
)
from quantbt.core.schema import OrderSide


def _idx():
    return pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")


def _basis_closes(idx):
    return {
        "BTCUSDT-PERP.BINANCE": pd.Series([100_000.0, 100_000.0, 101_000.0, 101_000.0], index=idx),
        "BTCUSDT-QUARTERLY.BINANCE": pd.Series([102_000.0, 102_000.0, 102_500.0, 102_500.0], index=idx),
    }


def _basis_spec(*, execution_policy=None, min_notional=100.0, notional=50_000.0):
    return BasisArbitrageSpec(
        arb_id="BTC_USDM_PERP_QUARTERLY",
        legs=(
            ArbitrageLeg(
                symbol="BTCUSDT-PERP.BINANCE",
                ratio=-1.0,
                role="perp",
                contract_type=ContractType.LINEAR,
                qty_step=0.001,
                min_qty=0.001,
                min_notional=min_notional,
                funding_enabled=True,
            ),
            ArbitrageLeg(
                symbol="BTCUSDT-QUARTERLY.BINANCE",
                ratio=1.0,
                role="quarterly",
                contract_type=ContractType.LINEAR,
                qty_step=0.001,
                min_qty=0.001,
                min_notional=min_notional,
                funding_enabled=False,
            ),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(
            kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=notional,
            reference_symbol="BTCUSDT-PERP.BINANCE",
        ),
        execution_policy=execution_policy or ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )


def test_basis_phase_a_uses_equal_base_quantity_not_equal_notional():
    idx = _idx()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    plan = build_arbitrage_order_plan(
        datetime_index=idx,
        spec=_basis_spec(),
        signal=signal,
        closes=_basis_closes(idx),
    )

    assert len(plan.orders) == 4
    entry_perp, entry_quarterly = plan.orders[0], plan.orders[1]
    assert entry_perp.symbol == "BTCUSDT-PERP.BINANCE"
    assert entry_perp.side is OrderSide.SELL
    assert entry_perp.qty == 0.5
    assert entry_quarterly.symbol == "BTCUSDT-QUARTERLY.BINANCE"
    assert entry_quarterly.side is OrderSide.BUY
    assert entry_quarterly.qty == 0.5

    assert plan.target_units.loc[idx[1], "BTCUSDT-PERP.BINANCE"] == -0.5
    assert plan.target_units.loc[idx[1], "BTCUSDT-QUARTERLY.BINANCE"] == 0.5
    assert abs(plan.target_units.loc[idx[1], "BTCUSDT-PERP.BINANCE"]) == abs(
        plan.target_units.loc[idx[1], "BTCUSDT-QUARTERLY.BINANCE"]
    )
    assert abs(plan.target_units.loc[idx[1], "BTCUSDT-PERP.BINANCE"]) * 100_000.0 != abs(
        plan.target_units.loc[idx[1], "BTCUSDT-QUARTERLY.BINANCE"]
    ) * 102_000.0

    assert plan.target_units.loc[idx[2], "BTCUSDT-PERP.BINANCE"] == -0.5
    assert plan.target_units.loc[idx[2], "BTCUSDT-QUARTERLY.BINANCE"] == 0.5
    assert plan.target_units.loc[idx[3], "BTCUSDT-PERP.BINANCE"] == 0.0
    assert plan.target_units.loc[idx[3], "BTCUSDT-QUARTERLY.BINANCE"] == 0.0


def test_stat_arb_phase_a_freezes_dynamic_hedge_ratio_until_signal_change():
    idx = _idx()
    closes = {
        "BASE": pd.Series([10.0, 10.0, 20.0, 20.0], index=idx),
        "HEDGE": pd.Series([100.0, 100.0, 120.0, 120.0], index=idx),
    }
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    hedge_ratios = {
        "BASE": pd.Series([1.0, 1.0, 1.0, 1.0], index=idx),
        "HEDGE": pd.Series([-0.5, -0.5, -2.0, -2.0], index=idx),
    }
    spec = StatArbPairSpec(
        arb_id="STAT_PAIR_001",
        legs=(
            ArbitrageLeg(symbol="BASE", ratio=1.0),
            ArbitrageLeg(symbol="HEDGE", ratio=-0.5),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BETA_NEUTRAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=600.0),
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )

    plan = build_arbitrage_order_plan(
        datetime_index=idx,
        spec=spec,
        signal=signal,
        closes=closes,
        hedge_ratios=hedge_ratios,
    )

    assert plan.target_units.loc[idx[1], "BASE"] == 10.0
    assert plan.target_units.loc[idx[1], "HEDGE"] == -5.0
    assert plan.target_units.loc[idx[2], "BASE"] == 10.0
    assert plan.target_units.loc[idx[2], "HEDGE"] == -5.0
    assert len(plan.orders) == 4


def test_atomic_arbitrage_package_rejects_all_legs_on_min_notional_failure():
    idx = _idx()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    plan = build_arbitrage_order_plan(
        datetime_index=idx,
        spec=_basis_spec(min_notional=60_000.0),
        signal=signal,
        closes=_basis_closes(idx),
    )

    assert plan.orders == ()
    assert len(plan.rejections) == 1
    assert set(plan.rejections[0].failed_legs) == {"BTCUSDT-PERP.BINANCE", "BTCUSDT-QUARTERLY.BINANCE"}
    assert plan.target_units.abs().sum().sum() == 0.0
    assert plan.rejection_report.loc[0, "reason"] == "precision_or_min_notional"


def test_best_effort_arbitrage_package_keeps_valid_legs_and_reports_failed_legs():
    idx = _idx()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    spec = _basis_spec(
        min_notional=100.0,
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.BEST_EFFORT),
    )
    # Make only the quarterly leg fail min-notional by overriding that leg.
    spec = BasisArbitrageSpec(
        arb_id=spec.arb_id,
        legs=(
            spec.legs[0],
            ArbitrageLeg(
                symbol="BTCUSDT-QUARTERLY.BINANCE",
                ratio=1.0,
                role="quarterly",
                contract_type=ContractType.LINEAR,
                qty_step=0.001,
                min_qty=0.001,
                min_notional=60_000.0,
            ),
        ),
        hedge_policy=spec.hedge_policy,
        sizing_policy=spec.sizing_policy,
        execution_policy=spec.execution_policy,
    )

    plan = build_arbitrage_order_plan(
        datetime_index=idx,
        spec=spec,
        signal=signal,
        closes=_basis_closes(idx),
    )

    assert len(plan.rejections) == 1
    assert plan.rejections[0].failed_legs == ("BTCUSDT-QUARTERLY.BINANCE",)
    assert plan.target_units.loc[idx[1], "BTCUSDT-PERP.BINANCE"] == -0.5
    assert plan.target_units.loc[idx[1], "BTCUSDT-QUARTERLY.BINANCE"] == 0.0
    assert [order.symbol for order in plan.orders] == ["BTCUSDT-PERP.BINANCE", "BTCUSDT-PERP.BINANCE"]


def test_arbitrage_endpoint_stores_spec_and_runs_phase_c_basis_engine():
    idx = _idx()
    endpoint = QuantBTEndpoint.arbitrage(
        arb_type="basis",
        spec=_basis_spec(),
        initial_capital=100_000.0,
        leverage=5.0,
    )

    assert endpoint.config.mode == "arbitrage"
    assert endpoint.config.arbitrage_spec.arb_id == "BTC_USDM_PERP_QUARTERLY"
    assert endpoint.config.metadata["arb_type"] == "basis"
    result = endpoint.simulate(
        closes=_basis_closes(idx),
        datetime_index=idx,
        signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
    )
    assert result.metadata["engine"] == "event_v1_basis_arbitrage"
