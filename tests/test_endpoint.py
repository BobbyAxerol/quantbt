from __future__ import annotations

import pandas as pd

from quantbt import (
    AccountConfig,
    BasketLegSpec,
    BasketSpec,
    BacktestResultV2,
    format_metrics_report,
    OrderIntent,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    TimeInForce,
)


def _bars():
    idx = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0, 120.0, 115.0],
            "high": [100.0, 101.0, 112.0, 121.0, 116.0],
            "low": [100.0, 99.0, 94.0, 113.0, 112.0],
            "close": [100.0, 100.0, 110.0, 120.0, 115.0],
            "volume": [1_000.0, 1_100.0, 1_200.0, 1_300.0, 1_400.0],
        },
        index=idx,
    )


def test_endpoint_pct_equity_uses_legacy_backtester():
    df = _bars()
    df["pos"] = [0.0, 1.0, 1.0, 0.0, 0.0]

    endpoint = QuantBTEndpoint.pct_equity(
        initial_capital=10_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0004,
        use_funding=False,
    )
    result = endpoint.backtest(data=df, signal_col="pos")

    assert result.metadata["hedge_type"] == "%_equity"
    assert result.initial_capital == 10_000.0
    assert result.fills == ()
    assert result.metadata["order_report"].empty
    assert endpoint.full_report()["num_trades"] >= 2


def test_endpoint_signal_notional_vectorized_and_event_match():
    df = _bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index)
    common = dict(
        initial_capital=10_000.0,
        leverage=10.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )

    vectorized = QuantBTEndpoint.signal_notional(backend="native_vectorized", **common)
    event = QuantBTEndpoint.signal_notional(backend="native_event", **common)

    r_vec = vectorized.backtest(data=df, signal=signal, symbols=["BTC"])
    r_evt = event.backtest(data=df, signal=signal, symbols=["BTC"])

    assert r_vec.fills == ()
    assert r_vec.metadata["order_report"].empty
    assert r_vec.equity.equals(r_evt.equity)
    assert len(r_evt.fills) == 2
    assert len(event.fills) == 2
    assert not event.order_report.empty
    assert r_evt.metadata["orders_report"].equals(r_evt.metadata["order_report"])


def test_endpoint_orders_simulation():
    df = _bars()
    order = OrderIntent(
        timestamp=df.index[1],
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=10.0,
        price=99.0,
        tif=TimeInForce.GTC,
    )

    endpoint = QuantBTEndpoint.orders(initial_capital=10_000.0, leverage=10.0, use_funding=False)
    result = endpoint.simulate(data=df, orders=[order], symbols=["BTC"])

    assert result.metadata["backend"] == "native_event"
    assert len(result.fills) == 1
    assert result.fills[0].price == 99.0


def test_endpoint_basket_simulation():
    df = _bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index)
    basket = BasketSpec(
        basket_id="PAIR-001",
        legs=(
            BasketLegSpec(symbol="BASE", ratio=1.0),
            BasketLegSpec(symbol="HEDGE", ratio=-0.5),
        ),
        gross_notional=1_000.0,
    )
    data = {"BASE": df, "HEDGE": df.assign(close=df["close"] * 2.0)}

    endpoint = QuantBTEndpoint.basket(basket=basket, initial_capital=10_000.0, leverage=10.0, use_funding=False)
    result = endpoint.simulate(data=data, signal=signal)

    assert result.metadata["backend"] == "native_event"
    assert "basket_target_units" in result.metadata


def test_endpoint_portfolio_accepts_positions_dataframe_and_data_dict():
    df = _bars()
    positions = pd.DataFrame(
        {
            "BTC": [0.0, 1.0, 1.0, 0.0, 0.0],
            "ETH": [0.0, -1.0, -1.0, 0.0, 0.0],
        },
        index=df.index,
    )
    data = {"BTC": df, "ETH": df.assign(close=df["close"] * 0.1)}

    endpoint = QuantBTEndpoint.portfolio(
        portfolio_mode="market_neutral",
        initial_capital=10_000.0,
        leverage=10.0,
        alloc_per_trade=1_000.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=data, positions=positions)

    assert result.metadata["backend"] == "legacy_portfolio"
    assert "Position_BTC" in result.positions.columns


def test_endpoint_dca_ladder_requires_high_low_and_runs():
    df = _bars()
    signal = pd.Series([0, 2, 2, 0, 0], index=df.index)

    endpoint = QuantBTEndpoint.dca_ladder(
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        dca_max_safety_orders=1,
        dca_step_pct=0.01,
        use_funding=False,
    )
    result = endpoint.backtest(data=df, signal=signal)

    assert result.metadata["hedge_type"] == "dca_ladder"
    assert result.metadata["dca_actual_level"] is not None


def test_endpoint_show_metrics_uses_legacy_text_format(capsys):
    df = _bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index)

    endpoint = QuantBTEndpoint.signal_notional(
        backend="native_vectorized",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    endpoint.backtest(data=df, signal=signal, symbols=["BTC"])
    report = endpoint.show_metrics()
    output = capsys.readouterr().out

    assert report["initial_capital"] == 20_000.0
    assert "  Initial Capital   $        20,000" in output
    assert "  Final Equity      $" in output
    assert "  Max DD Duration" in output
    assert "  Avg Loss" in output
    assert "initial_capital:" not in output


def test_endpoint_result_objects_expose_metrics_helpers(capsys):
    df = _bars()
    df["pos"] = [0.0, 1.0, 1.0, 0.0, 0.0]

    legacy = QuantBTEndpoint.pct_equity(
        initial_capital=10_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0,
        use_funding=False,
    ).backtest(data=df, signal_col="pos")
    v2 = QuantBTEndpoint.signal_notional(
        backend="native_event",
        initial_capital=10_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    ).simulate(data=df, signal_col="pos", symbols=["BTC"])

    assert legacy.show_metrics()["initial_capital"] == 10_000.0
    assert v2.show_metrics()["initial_capital"] == 10_000.0
    output = capsys.readouterr().out

    assert output.count("Initial Capital") == 2
    assert "Final Equity" in output


def test_endpoint_direct_constructor_accepts_account_kwargs():
    endpoint = QuantBTEndpoint(
        mode="single_signal",
        backend="native_vectorized",
        sizing="signal_notional",
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=1_000.0,
        use_funding=False,
    )

    assert endpoint.config.account.initial_capital == 20_000.0
    assert endpoint.config.account.leverage == 3.0
    assert format_metrics_report(
        {
            "initial_capital": 20_000.0,
            "final_equity": 21_000.0,
            "total_return_pct": 5.0,
            "cagr_pct": 5.0,
            "sharpe": 1.0,
            "sortino": 1.0,
            "calmar": 1.0,
            "omega": 1.0,
            "max_drawdown_pct": 1.0,
            "avg_drawdown_pct": 0.5,
            "max_dd_duration_days": 3,
            "profit_factor": 1.2,
            "long_hitrate_pct": 50.0,
            "short_hitrate_pct": 0.0,
            "avg_win_pct": 1.0,
            "avg_loss_pct": -1.0,
            "expectancy_pct": 0.1,
            "num_trades": 2,
            "liquidated": False,
        }
    ).startswith("\n  Initial Capital")


def test_endpoint_arbitrage_support_matrix_exposes_supported_and_schema_only_specs():
    matrix = QuantBTEndpoint.arbitrage_support_matrix()

    assert matrix["StatArbPairSpec"]["status"] == "supported"
    assert "native_vectorized" in matrix["BasisArbitrageSpec"]["backends"]
    assert matrix["TriangularArbSpec"]["status"] == "schema_only"
    assert matrix["OptionsVolArbSpec"]["backends"] == "none"


def test_nautilus_endpoint_accepts_legacy_hedge_type_alias():
    endpoint = QuantBTEndpoint.nautilus_validation(
        hedge_type="%_equity",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        use_funding=False,
    )

    assert endpoint.config.backend == "nautilus"
    assert endpoint.config.sizing == "%_equity"


def test_nautilus_endpoint_forwards_use_pyramiding_to_adapter(monkeypatch):
    from quantbt.adapters.nautilus import NautilusBackendConfig
    import quantbt.adapters.nautilus as nautilus_module

    captured = {}

    class FakeNautilusBacktestEngine:
        def __init__(self, config):
            captured["config"] = config

        def run_signal_series(self, data, signal):
            idx = data.index
            equity = pd.Series(10_000.0, index=idx)
            positions = pd.DataFrame({"Position_ETHUSDT-PERP.BINANCE": 0.0}, index=idx)
            closes = pd.DataFrame({"Close_ETHUSDT-PERP.BINANCE": data["close"]}, index=idx)
            return BacktestResultV2(
                equity=equity,
                returns=equity.pct_change().fillna(0.0),
                positions=positions,
                closes=closes,
                symbols=["ETHUSDT-PERP.BINANCE"],
                initial_capital=10_000.0,
                metadata={"use_pyramiding": captured["config"].use_pyramiding},
            )

    monkeypatch.setattr(nautilus_module, "NautilusBacktestEngine", FakeNautilusBacktestEngine)

    df = _bars()
    signal = pd.Series([0.0, 1.4, 1.4, 0.0, 0.0], index=df.index)
    endpoint = QuantBTEndpoint.nautilus_validation(
        hedge_type="%_equity",
        initial_capital=10_000.0,
        alloc_per_trade=0.5,
        use_pyramiding=False,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            instrument_id="ETHUSDT-PERP.BINANCE",
            timeframe="1h",
            use_pyramiding=True,
        ),
    )

    result = endpoint.simulate(data=df, signal=signal, symbols=["ETHUSDT-PERP.BINANCE"])

    assert captured["config"].use_pyramiding is False
    assert captured["config"].sizing_mode == "%_equity"
    assert captured["config"].trade_notional == 0.5
    assert result.metadata["use_pyramiding"] is False


def test_simulate_can_print_bounded_nautilus_order_logs(monkeypatch, capsys):
    from quantbt.adapters.nautilus import NautilusBackendConfig
    import quantbt.adapters.nautilus as nautilus_module

    class FakeNautilusBacktestEngine:
        def __init__(self, config):
            self.config = config

        def run_signal_series(self, data, signal):
            idx = data.index
            equity = pd.Series(10_000.0, index=idx)
            positions = pd.DataFrame({"Position_ETHUSDT-PERP.BINANCE": [0.0, 1.0, 1.0, 0.0, 0.0]}, index=idx)
            closes = pd.DataFrame({"Close_ETHUSDT-PERP.BINANCE": data["close"]}, index=idx)
            fills = pd.DataFrame(
                {
                    "instrument_id": ["ETHUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE"],
                    "side": ["BUY", "SELL"],
                    "filled_qty": [1.0, 1.0],
                    "avg_px": [100.0, 102.0],
                    "commissions": ["0.1 USDT", "0.1 USDT"],
                    "ts_last": [idx[1], idx[3]],
                }
            )
            return BacktestResultV2(
                equity=equity,
                returns=equity.pct_change().fillna(0.0),
                positions=positions,
                closes=closes,
                symbols=["ETHUSDT-PERP.BINANCE"],
                initial_capital=10_000.0,
                metadata={"backend": "nautilus", "fills_report": fills, "orders_report": fills},
            )

    monkeypatch.setattr(nautilus_module, "NautilusBacktestEngine", FakeNautilusBacktestEngine)

    endpoint = QuantBTEndpoint.nautilus_validation(
        initial_capital=10_000.0,
        alloc_per_trade=1_000.0,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(instrument_id="ETHUSDT-PERP.BINANCE", timeframe="1h"),
    )

    endpoint.simulate(
        data=_bars(),
        signal=pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=_bars().index),
        symbols=["ETHUSDT-PERP.BINANCE"],
        show_order_logs=True,
        order_log_limit=1,
    )

    out = capsys.readouterr().out
    assert "FILL BUY" in out
    assert "SELL" not in out
