from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ArbitrageLeg,
    BasisArbitrageSpec,
    BracketOrderSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    OrderIntent,
    PortfolioBacktestEngine,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    build_arbitrage_domain_audit,
    build_portfolio_domain_audit,
    compare_native_arbitrage_results,
)
from quantbt.adapters.nautilus import NautilusBackendConfig
from quantbt.adapters.nautilus._dependency import require_nautilus
from quantbt.core.event import ORDER_STATUS_FILLED
from quantbt.core.schema import ExecutionConfig, OrderSide, OrderType, TimeInForce


def test_phase5_3_simulated_multisymbol_portfolio_matrix_is_auditable():
    idx = pd.date_range("2024-01-01", periods=6, freq="1D", tz="UTC")
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, -1.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -1.0, -1.0, 0.0, 1.0, 0.0], index=idx),
        "SOL": pd.Series([0.0, 0.0, 1.0, 1.0, 0.0, 0.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 100.0, 106.0, 104.0, 101.0, 99.0], index=idx),
        "ETH": pd.Series([50.0, 50.0, 47.0, 48.0, 52.0, 54.0], index=idx),
        "SOL": pd.Series([20.0, 20.0, 22.0, 23.0, 22.0, 21.0], index=idx),
    }

    result = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        mode="market_neutral",
        account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
        fee_rate=0.0004,
        alloc_per_trade={"BTC": 10_000.0, "ETH": 8_000.0, "SOL": 6_000.0},
        use_funding=False,
    ).result

    audit = build_portfolio_domain_audit(result, tolerance=1e-8, raise_on_fail=True)
    exposure = result.metadata["exposure_report"]

    assert audit["status"] == "pass"
    assert audit["rebalance_count"] == 0
    np.testing.assert_allclose(exposure["long_notional"].iloc[1], exposure["short_notional"].iloc[1])
    assert exposure["gross_leverage"].max() < 1.0
    assert result.equity.iloc[-1] > 0.0


def test_phase5_3_simulated_explicit_orders_fill_at_domain_prices_and_flatten():
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    close = pd.Series([100.0, 100.0, 102.0, 103.0, 101.0], index=idx)
    high = pd.Series([100.0, 101.0, 103.0, 104.0, 102.0], index=idx)
    low = pd.Series([100.0, 95.0, 101.0, 102.0, 100.0], index=idx)
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=10.0,
            price=96.0,
            tif=TimeInForce.GTC,
            tag="limit-entry",
        ),
        OrderIntent(
            timestamp=idx[3],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=10.0,
            tif=TimeInForce.IOC,
            reduce_only=True,
            tag="market-exit",
        ),
    ]

    result = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0,
            use_funding=False,
        )
    ).run_orders(
        datetime_index=idx,
        orders=orders,
        closes={"BTC": close},
        highs={"BTC": high},
        lows={"BTC": low},
    )

    assert [fill.price for fill in result.fills] == [96.0, 103.0]
    assert result.positions["Position_BTC"].iloc[-1] == 0.0
    assert result.metadata["order_report"]["status"].tolist() == [ORDER_STATUS_FILLED, ORDER_STATUS_FILLED]
    np.testing.assert_allclose(result.equity.iloc[-1], 10_070.0)


def test_phase5_3_simulated_nautilus_bracket_oco_fills_one_exit_and_cancels_sibling():
    try:
        require_nautilus()
    except ImportError:
        pytest.skip("nautilus_trader not installed")

    idx = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(idx),
            "high": [101.0, 101.0, 101.0, 111.0, 112.0, 100.0, 100.0, 100.0],
            "low": [99.0, 99.0, 99.0, 98.0, 98.0, 98.0, 98.0, 98.0],
            "close": [100.0, 100.0, 100.0, 110.0, 111.0, 100.0, 100.0, 100.0],
            "volume": 1_000.0,
        },
        index=idx,
    )
    symbol = "ETHUSDT-PERP.BINANCE"

    result = QuantBTEndpoint.nautilus_bracket_orders(
        spec=BracketOrderSpec(
            symbol=symbol,
            entry_timestamp=idx[1],
            exit_timestamp=idx[2],
            side=OrderSide.BUY,
            qty=0.1,
            take_profit_price=110.0,
            stop_loss_price=95.0,
        ),
        initial_capital=10_000.0,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            instrument_id=symbol,
            timeframe="1h",
            starting_balance=10_000.0,
            bypass_risk=True,
        ),
    ).simulate(data=df)

    assert result.metadata["engine"] == "nautilus_bracket_oco"
    assert result.metadata["input_mode"] == "bracket_oco"
    assert result.metadata["fills_count"] == 2
    assert result.metadata["oco_cancellations"]
    assert result.metadata["package_order_map"]["leg_role"].tolist() == ["entry", "take_profit", "stop_loss"]


def test_phase5_3_simulated_basis_arbitrage_event_vectorized_parity_is_auditable():
    idx = pd.date_range("2024-01-01", periods=5, freq="8h", tz="UTC")
    signal = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0], index=idx)
    closes = {
        "BTC-PERP": pd.Series([100.0, 100.0, 102.0, 104.0, 103.0], index=idx),
        "BTC-QUARTERLY": pd.Series([102.0, 102.0, 103.0, 104.5, 103.2], index=idx),
    }
    spec = BasisArbitrageSpec(
        arb_id="SIM_BASIS",
        legs=(
            ArbitrageLeg("BTC-PERP", -1.0, role="perp", contract_type=ContractType.LINEAR, funding_enabled=True),
            ArbitrageLeg("BTC-QUARTERLY", 1.0, role="quarterly", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=10_000.0,
            reference_symbol="BTC-PERP",
        ),
    )
    event = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=True,
        )
    ).run_basis_arbitrage(idx, spec, signal, closes, funding_rate={"BTC-PERP": 0.0})
    vectorized = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=True,
        )
    ).run_basis_arbitrage(idx, spec, signal, closes, funding_rate={"BTC-PERP": 0.0})

    event_audit = build_arbitrage_domain_audit(event, raise_on_fail=True)
    vector_audit = build_arbitrage_domain_audit(vectorized, raise_on_fail=True)
    parity = compare_native_arbitrage_results(event, vectorized, raise_on_fail=True)

    assert event_audit["status"] == "pass"
    assert vector_audit["status"] == "pass"
    assert parity["status"] == "pass"
    assert event_audit["final_gross_target_units"] == 0.0
    assert event_audit["final_gross_position_units"] == 0.0
