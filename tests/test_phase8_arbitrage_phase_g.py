from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    ArbitrageLeg,
    CalendarSpreadSpec,
    CarryModel,
    ContractType,
    CrossExchangeArbSpec,
    FundingArbitrageSpec,
    HedgePolicy,
    HedgePolicyKind,
    IndexBasketArbSpec,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    OptionsVolArbSpec,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    SpotPerpCashCarrySpec,
    TriangularArbSpec,
)
from quantbt.core.schema import AccountConfig


def _idx():
    return pd.date_range("2024-01-01", periods=4, freq="8h", tz="UTC")


def _signal(idx):
    return pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)


def _event():
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=True,
        )
    )


def _vectorized():
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=True,
        )
    )


def test_phase_g_advanced_spec_domain_validation():
    with pytest.raises(ValueError, match="at least three legs"):
        IndexBasketArbSpec(
            arb_id="IDX_BAD",
            legs=(ArbitrageLeg("A", 1.0), ArbitrageLeg("B", -1.0)),
            hedge_policy=HedgePolicy(HedgePolicyKind.NOTIONAL_NEUTRAL),
            sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=1_000.0),
        )

    with pytest.raises(ValueError, match="venue"):
        CrossExchangeArbSpec(
            arb_id="XEX_BAD",
            legs=(ArbitrageLeg("A", 1.0, venue="BINANCE"), ArbitrageLeg("B", -1.0)),
            hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
            sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_BASE_QTY, base_qty=1.0),
        )

    with pytest.raises(ValueError, match="exactly three legs"):
        TriangularArbSpec(
            arb_id="TRI_BAD",
            legs=(ArbitrageLeg("BTCUSDT", 1.0, base_currency="BTC"), ArbitrageLeg("ETHBTC", 1.0, base_currency="ETH")),
            hedge_policy=HedgePolicy(HedgePolicyKind.NOTIONAL_NEUTRAL),
            sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=1_000.0),
        )

    with pytest.raises(ValueError, match="option leg"):
        OptionsVolArbSpec(
            arb_id="OPT_BAD",
            legs=(ArbitrageLeg("BTC", 1.0), ArbitrageLeg("HEDGE", -1.0)),
            hedge_policy=HedgePolicy(HedgePolicyKind.VEGA_NEUTRAL),
            sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=1_000.0),
        )

    SpotPerpCashCarrySpec(
        arb_id="CARRY_OK",
        legs=(
            ArbitrageLeg("BTC-SPOT", 1.0, role="spot", contract_type=ContractType.SPOT, asset_class="crypto"),
            ArbitrageLeg("BTC-PERP", -1.0, role="perp", contract_type=ContractType.LINEAR, funding_enabled=True),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, notional=10_000.0, reference_symbol="BTC-SPOT"),
        carry_model=CarryModel(kind="funding_and_borrow", borrow_rate=0.01, cash_yield=0.02),
    )


def test_phase_g_calendar_spread_event_and_vectorized_package_parity():
    idx = _idx()
    closes = {
        "BTC-MAR": pd.Series([100.0, 100.0, 101.0, 101.0], index=idx),
        "BTC-JUN": pd.Series([103.0, 103.0, 104.0, 104.0], index=idx),
    }
    spec = CalendarSpreadSpec(
        arb_id="CAL_BTC",
        legs=(
            ArbitrageLeg("BTC-MAR", -1.0, role="near", expiry="2024-03-29"),
            ArbitrageLeg("BTC-JUN", 1.0, role="far", expiry="2024-06-28"),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, notional=10_000.0, reference_symbol="BTC-MAR"),
    )

    event = _event().run_package_arbitrage(idx, spec, _signal(idx), closes)
    vectorized = _vectorized().run_package_arbitrage(idx, spec, _signal(idx), closes)

    np.testing.assert_allclose(event.equity.to_numpy(), vectorized.equity.to_numpy(), atol=1e-10)
    np.testing.assert_allclose(event.positions.to_numpy(), vectorized.positions.to_numpy(), atol=1e-10)
    assert event.metadata["engine"] == "event_v1_calendar_spread"
    assert vectorized.metadata["engine"] == "units_v2_calendar_spread"
    assert event.metadata["package_target_units"].loc[idx[1], "BTC-MAR"] == -100.0
    assert "spread_report" in event.metadata


def test_phase_g_funding_package_applies_funding_enabled_leg_only():
    idx = _idx()
    closes = {
        "PERP_A": pd.Series([100.0, 100.0, 105.0, 105.0], index=idx),
        "PERP_B": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
    }
    spec = FundingArbitrageSpec(
        arb_id="FUND_PAIR",
        legs=(
            ArbitrageLeg("PERP_A", 1.0, funding_enabled=True),
            ArbitrageLeg("PERP_B", -1.0, funding_enabled=False),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, notional=10_000.0, reference_symbol="PERP_A"),
        carry_model=CarryModel(kind="funding", funding_interval_hours=8),
    )
    funding = {"PERP_A": pd.Series([0.0, 0.0, 0.01, 0.0], index=idx), "PERP_B": 0.99}

    event = _event().run_package_arbitrage(idx, spec, _signal(idx), closes, funding_rate=funding)
    vectorized = _vectorized().run_package_arbitrage(idx, spec, _signal(idx), closes, funding_rate=funding)

    np.testing.assert_allclose(event.equity.to_numpy(), vectorized.equity.to_numpy(), atol=1e-10)
    carry = event.metadata["carry_report"]
    perp_a_cost = carry[(carry["timestamp"] == idx[2]) & (carry["symbol"] == "PERP_A")]["funding_cost"].iloc[0]
    perp_b_cost = carry[(carry["timestamp"] == idx[2]) & (carry["symbol"] == "PERP_B")]["funding_cost"].iloc[0]
    assert perp_a_cost == 105.0
    assert perp_b_cost == 0.0


def test_phase_g_index_basket_endpoint_native_vectorized():
    idx = _idx()
    closes = {
        "ETF": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
        "A": pd.Series([50.0, 50.0, 52.0, 52.0], index=idx),
        "B": pd.Series([25.0, 25.0, 24.0, 24.0], index=idx),
    }
    spec = IndexBasketArbSpec(
        arb_id="INDEX_ARB",
        legs=(ArbitrageLeg("ETF", -1.0), ArbitrageLeg("A", 1.0), ArbitrageLeg("B", 2.0)),
        hedge_policy=HedgePolicy(HedgePolicyKind.NOTIONAL_NEUTRAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=20_000.0),
    )
    endpoint = QuantBTEndpoint.arbitrage(
        arb_type="index_basket",
        spec=spec,
        backend="native_vectorized",
        initial_capital=50_000.0,
        leverage=10.0,
        use_funding=False,
    )

    result = endpoint.simulate(closes=closes, datetime_index=idx, signal=_signal(idx))

    assert result.metadata["engine"] == "units_v2_index_basket"
    assert result.metadata["package_target_units"].loc[idx[1]].abs().sum() > 0.0
    assert result.metadata["package_pnl_report"]["pnl_residual"].abs().max() < 1e-10


def test_phase_g_specialized_types_stay_explicitly_unsupported_in_generic_engines():
    spec = CrossExchangeArbSpec(
        arb_id="XEX",
        legs=(ArbitrageLeg("BTC-A", 1.0, venue="BINANCE"), ArbitrageLeg("BTC-B", -1.0, venue="OKX")),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_BASE_QTY, base_qty=1.0),
    )

    with pytest.raises(NotImplementedError, match="specialized"):
        _event().run_package_arbitrage(_idx(), spec, _signal(_idx()), {"BTC-A": pd.Series(100.0, index=_idx()), "BTC-B": pd.Series(101.0, index=_idx())})
