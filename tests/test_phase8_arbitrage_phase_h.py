from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    PackageExecutionKind,
    SizingPolicy,
    SizingPolicyKind,
    SpotPerpCashCarrySpec,
    build_arbitrage_order_plan,
)
from quantbt.core.event import ORDER_STATUS_REJECTED, REJECT_INSUFFICIENT_MARGIN
from quantbt.core.schema import AccountConfig, ExecutionConfig


PERP = "BTCUSDT-PERP.BINANCE"
QUARTERLY = "BTCUSDT-QUARTERLY.BINANCE"


def _idx(periods=5, *, tz="UTC"):
    return pd.date_range("2024-01-01", periods=periods, freq="8h", tz=tz)


def _basis_spec(*, notional=10_000.0, fee_rate=0.0, qty_step=0.001, contract_size=1.0):
    return BasisArbitrageSpec(
        arb_id="BTC_BASIS_GOLDEN",
        legs=(
            ArbitrageLeg(
                symbol=PERP,
                ratio=-1.0,
                role="perp",
                contract_type=ContractType.LINEAR,
                contract_size=contract_size,
                qty_step=qty_step,
                min_qty=qty_step,
                min_notional=10.0,
                fee_rate=fee_rate,
                funding_enabled=True,
            ),
            ArbitrageLeg(
                symbol=QUARTERLY,
                ratio=1.0,
                role="quarterly",
                contract_type=ContractType.LINEAR,
                contract_size=contract_size,
                qty_step=qty_step,
                min_qty=qty_step,
                min_notional=10.0,
                fee_rate=fee_rate,
                funding_enabled=False,
            ),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=notional,
            reference_symbol=PERP,
        ),
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )


def _basis_closes(idx):
    return {
        PERP: pd.Series([100.0, 100.0, 105.0, 103.0, 103.0][: len(idx)], index=idx),
        QUARTERLY: pd.Series([102.0, 102.0, 104.0, 101.0, 101.0][: len(idx)], index=idx),
    }


def _basis_signal(idx):
    values = [0.0, 1.0, 1.0, 0.0, -1.0][: len(idx)]
    return pd.Series(values, index=idx)


def _event(initial_capital=50_000.0, leverage=10.0, slippage_bps=0.0, use_funding=True):
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=initial_capital, leverage=leverage),
            execution=ExecutionConfig(slippage_bps=slippage_bps),
            fee_rate=0.0,
            use_funding=use_funding,
        )
    )


def _vectorized(initial_capital=50_000.0, leverage=10.0, slippage_bps=0.0, use_funding=True):
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=initial_capital, leverage=leverage),
            execution=ExecutionConfig(slippage_bps=slippage_bps),
            fee_rate=0.0,
            use_funding=use_funding,
        )
    )


def test_phase_h_basis_fee_slippage_and_package_pnl_residual_are_exact():
    idx = _idx(4)
    spec = _basis_spec(fee_rate=0.001)
    result = _event(slippage_bps=100.0, use_funding=False).run_basis_arbitrage(
        datetime_index=idx,
        spec=spec,
        signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        closes=_basis_closes(idx),
    )

    fills = result.fills
    assert fills[0].price == 99.0
    assert fills[1].price == 103.02
    assert fills[2].price == 104.03
    assert fills[3].price == 99.99
    assert result.fees.iloc[1] == pytest.approx(20.201999999999998)
    assert result.fees.iloc[3] == pytest.approx(20.402)
    assert result.metadata["package_pnl_report"]["pnl_residual"].abs().max() < 1e-10
    assert result.metadata["leg_pnl_report"]["fee"].sum() == pytest.approx(result.fees.sum())


def test_phase_h_positive_funding_is_paid_by_long_and_received_by_short():
    idx = _idx(4)
    closes = _basis_closes(idx)
    funding = {PERP: pd.Series([0.0, 0.0, 0.01, 0.0], index=idx)}

    short_perp = _event().run_basis_arbitrage(
        datetime_index=idx,
        spec=_basis_spec(),
        signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        closes=closes,
        funding_rate=funding,
    )
    long_perp = _event().run_basis_arbitrage(
        datetime_index=idx,
        spec=_basis_spec(),
        signal=pd.Series([0.0, -1.0, -1.0, 0.0], index=idx),
        closes=closes,
        funding_rate=funding,
    )

    short_funding = short_perp.metadata["leg_pnl_report"][
        (short_perp.metadata["leg_pnl_report"]["timestamp"] == idx[2])
        & (short_perp.metadata["leg_pnl_report"]["symbol"] == PERP)
    ]["funding_pnl"].iloc[0]
    long_funding = long_perp.metadata["leg_pnl_report"][
        (long_perp.metadata["leg_pnl_report"]["timestamp"] == idx[2])
        & (long_perp.metadata["leg_pnl_report"]["symbol"] == PERP)
    ]["funding_pnl"].iloc[0]

    assert short_funding == pytest.approx(105.0)
    assert long_funding == pytest.approx(-105.0)


def test_phase_h_intrabar_liquidation_uses_adverse_high_low_across_package_legs():
    idx = _idx(4)
    closes = {
        PERP: pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
        QUARTERLY: pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
    }
    highs = {
        PERP: pd.Series([100.0, 100.0, 220.0, 100.0], index=idx),
        QUARTERLY: pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
    }
    lows = {
        PERP: pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
        QUARTERLY: pd.Series([100.0, 100.0, 1.0, 100.0], index=idx),
    }

    result = _event(initial_capital=1_000.0, leverage=10.0).run_basis_arbitrage(
        datetime_index=idx,
        spec=_basis_spec(notional=8_000.0),
        signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        closes=closes,
        highs=highs,
        lows=lows,
    )

    assert result.liquidated is True
    assert result.liquidation_bar == 2
    assert result.equity.iloc[2] == 0.0


def test_phase_h_margin_rejects_oversized_package_components_and_exposes_report():
    idx = _idx(4)
    result = _event(initial_capital=1_000.0, leverage=1.0, use_funding=False).run_basis_arbitrage(
        datetime_index=idx,
        spec=_basis_spec(notional=1_000_000.0),
        signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=idx),
        closes=_basis_closes(idx),
    )

    order_report = result.metadata["order_report"]
    assert len(result.fills) == 0
    assert set(order_report["status"]) == {ORDER_STATUS_REJECTED}
    assert set(order_report["reject_code"]) == {REJECT_INSUFFICIENT_MARGIN}
    assert result.positions.abs().sum().sum() == 0.0


def test_phase_h_precision_contract_size_and_timezone_alignment_are_explicit():
    idx_naive = pd.date_range("2024-01-01", periods=4, freq="8h")
    closes = {
        PERP: pd.Series([100.0, 100.0, 100.0, 100.0], index=idx_naive),
        QUARTERLY: pd.Series([102.0, 102.0, 102.0, 102.0], index=idx_naive),
    }
    spec = _basis_spec(notional=1_000.0, qty_step=0.3, contract_size=10.0)

    plan = build_arbitrage_order_plan(
        datetime_index=idx_naive,
        spec=spec,
        signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=idx_naive),
        closes=closes,
    )

    assert str(plan.target_units.index.tz) == "UTC"
    assert plan.target_units.loc[pd.Timestamp("2024-01-01 08:00:00", tz="UTC"), PERP] == pytest.approx(-9.9)
    assert plan.orders[0].qty == pytest.approx(9.9)
    assert plan.rejections == ()

    with pytest.raises(ValueError, match="missing closes"):
        build_arbitrage_order_plan(
            datetime_index=idx_naive,
            spec=spec,
            signal=pd.Series([0.0, 1.0, 1.0, 0.0], index=idx_naive),
            closes={PERP: closes[PERP]},
        )


def test_phase_h_spot_perp_cash_carry_event_vectorized_parity_with_mock_realistic_data():
    idx = _idx(5)
    closes = {
        "BTC-SPOT": pd.Series([100.0, 100.0, 101.0, 102.0, 102.0], index=idx),
        "BTC-PERP": pd.Series([101.0, 101.0, 102.0, 103.0, 103.0], index=idx),
    }
    spec = SpotPerpCashCarrySpec(
        arb_id="BTC_CASH_CARRY_GOLDEN",
        legs=(
            ArbitrageLeg(
                "BTC-SPOT",
                1.0,
                role="spot",
                contract_type=ContractType.SPOT,
                asset_class="crypto",
                qty_step=0.001,
                min_qty=0.001,
            ),
            ArbitrageLeg(
                "BTC-PERP",
                -1.0,
                role="perp",
                contract_type=ContractType.LINEAR,
                funding_enabled=True,
                qty_step=0.001,
                min_qty=0.001,
            ),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=10_000.0,
            reference_symbol="BTC-SPOT",
        ),
    )
    signal = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0], index=idx)
    funding = {"BTC-PERP": pd.Series([0.0, 0.0, 0.001, -0.001, 0.0], index=idx)}

    event = _event().run_package_arbitrage(idx, spec, signal, closes, funding_rate=funding)
    vectorized = _vectorized().run_package_arbitrage(idx, spec, signal, closes, funding_rate=funding)

    np.testing.assert_allclose(event.equity.to_numpy(), vectorized.equity.to_numpy(), atol=1e-10)
    np.testing.assert_allclose(event.positions.to_numpy(), vectorized.positions.to_numpy(), atol=1e-10)
    assert event.metadata["carry_report"]["funding_cost"].abs().sum() > 0.0
    assert event.metadata["package_pnl_report"]["pnl_residual"].abs().max() < 1e-10
