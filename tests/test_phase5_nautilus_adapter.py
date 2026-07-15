from __future__ import annotations

import pandas as pd
import pytest

from quantbt import AccountConfig, BacktestEngineV2
from quantbt.adapters.nautilus import (
    NautilusBackendConfig,
    NautilusBacktestEngine,
    build_nautilus_package_order_table,
    ensure_utc_ohlcv,
    make_binance_perpetual,
    normalize_binance_perp_symbol,
    result_from_nautilus_reports,
    supported_binance_perpetuals,
    timeframe_to_nautilus,
)
from quantbt.adapters.nautilus._dependency import require_nautilus
from quantbt.core.orders import OrderIntent
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def test_nautilus_timeframe_mapping_is_explicit():
    assert timeframe_to_nautilus("1m") == "1-MINUTE"
    assert timeframe_to_nautilus("5min") == "5-MINUTE"
    assert timeframe_to_nautilus("1h") == "1-HOUR"
    assert timeframe_to_nautilus("2h") == "2-HOUR"
    assert timeframe_to_nautilus("1d") == "1-DAY"
    assert timeframe_to_nautilus("1w") == "1-WEEK"

    with pytest.raises(ValueError):
        timeframe_to_nautilus("3h")


def test_nautilus_supported_binance_perpetual_symbols():
    supported = supported_binance_perpetuals()

    assert "BTCUSDT-PERP.BINANCE" in supported
    assert "ETHUSDT-PERP.BINANCE" in supported
    assert "BNBUSDT-PERP.BINANCE" in supported
    assert "SOLUSDT-PERP.BINANCE" in supported
    assert "DOGEUSDT-PERP.BINANCE" in supported
    assert "ARBUSDT-PERP.BINANCE" in supported
    assert "LINKUSDT-PERP.BINANCE" in supported
    assert normalize_binance_perp_symbol("ARP") == "ARBUSDT"


def test_nautilus_can_build_supported_binance_perpetuals():
    try:
        nt = require_nautilus()
    except ImportError:
        pytest.skip("nautilus_trader not installed")

    for instrument_id in (
        "BNBUSDT-PERP.BINANCE",
        "SOLUSDT-PERP.BINANCE",
        "DOGEUSDT-PERP.BINANCE",
        "LINKUSDT-PERP.BINANCE",
    ):
        instrument = make_binance_perpetual(instrument_id, nt)
        assert str(instrument.id) == instrument_id
        assert instrument.quote_currency.code == "USDT"


def test_nautilus_backend_uses_symbol_override_for_supported_perpetual():
    try:
        require_nautilus()
    except ImportError:
        pytest.skip("nautilus_trader not installed")

    idx = pd.date_range("2024-01-01", periods=24, freq="1h", tz="UTC")
    close = pd.Series([100.0 + (i % 5) for i in range(len(idx))], index=idx)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )
    signal = pd.Series([0.0] * 4 + [1.0] * 10 + [0.0] * 10, index=idx)

    engine = BacktestEngineV2(
        data=df,
        signals=signal,
        symbols=["SOLUSDT-PERP.BINANCE"],
        backend="nautilus",
        account=AccountConfig(initial_capital=20_000.0, leverage=5.0),
        alloc_per_trade=1_000.0,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            timeframe="1h",
            starting_balance=20_000.0,
            trade_notional=1_000.0,
        ),
    )

    assert engine.result.metadata["instrument_id"] == "SOLUSDT-PERP.BINANCE"
    assert engine.result.metadata["orders_count"] >= 1


@pytest.mark.parametrize(
    ("hedge_type", "alloc_per_trade"),
    [
        ("signal_notional", 1_000.0),
        ("notional", 1_000.0),
        ("unit", 1_000.0),
        ("%_equity", 0.5),
    ],
)
def test_nautilus_backend_supports_single_symbol_sizing_modes(hedge_type, alloc_per_trade):
    try:
        require_nautilus()
    except ImportError:
        pytest.skip("nautilus_trader not installed")

    idx = pd.date_range("2024-01-01", periods=18, freq="1h", tz="UTC")
    close = pd.Series([100.0 + i for i in range(len(idx))], index=idx)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )
    signal = pd.Series([0.0] * 3 + [1.0] * 10 + [0.0] * 5, index=idx)

    engine = BacktestEngineV2(
        data=df,
        signals=signal,
        symbols=["BNBUSDT-PERP.BINANCE"],
        backend="nautilus",
        hedge_type=hedge_type,
        account=AccountConfig(initial_capital=20_000.0, leverage=5.0),
        alloc_per_trade=alloc_per_trade,
        use_funding=False,
    )

    assert engine.result.metadata["instrument_id"] == "BNBUSDT-PERP.BINANCE"
    assert engine.result.metadata["sizing_mode"] == hedge_type
    assert engine.result.metadata["orders_count"] >= 1
    assert engine.result.equity.iloc[-1] > 0.0


def test_nautilus_backend_replays_explicit_market_and_limit_orders():
    try:
        require_nautilus()
    except ImportError:
        pytest.skip("nautilus_trader not installed")

    idx = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(idx),
            "high": [101.0] * len(idx),
            "low": [99.0, 99.0, 94.0, 94.0, 99.0, 99.0, 99.0, 99.0],
            "close": [100.0] * len(idx),
            "volume": 1_000.0,
        },
        index=idx,
    )
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="ETHUSDT-PERP.BINANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=0.1,
            price=95.0,
            tif=TimeInForce.GTC,
            tag="limit-entry",
        ),
        OrderIntent(
            timestamp=idx[5],
            symbol="ETHUSDT-PERP.BINANCE",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=0.1,
            tif=TimeInForce.IOC,
            reduce_only=True,
            tag="market-exit",
        ),
    ]

    engine = BacktestEngineV2(
        data=df,
        orders=orders,
        symbols=["ETHUSDT-PERP.BINANCE"],
        backend="nautilus",
        account=AccountConfig(initial_capital=10_000.0),
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            instrument_id="ETHUSDT-PERP.BINANCE",
            timeframe="1h",
            starting_balance=10_000.0,
            bypass_risk=True,
        ),
    )

    report = engine.result.metadata["orders_report"]
    assert engine.result.metadata["input_mode"] == "explicit_orders"
    assert engine.result.metadata["order_count_input"] == 2
    assert engine.result.metadata["orders_count"] == 2
    assert engine.result.metadata["fills_count"] == 2
    assert list(report["type"]) == ["LIMIT", "MARKET"]
    assert float(report.iloc[0]["avg_px"]) == 95.0
    assert report.iloc[0]["time_in_force"] == "GTC"
    assert report.iloc[0]["status"] == "FILLED"
    assert report.iloc[1]["is_reduce_only"] in (True, "True", "true")


def test_nautilus_config_rejects_dca_ladder_until_event_ladder_is_supported():
    with pytest.raises(NotImplementedError):
        NautilusBackendConfig(sizing_mode="dca_ladder")


def test_nautilus_package_order_table_preserves_explicit_order_fields():
    order = OrderIntent(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC"),
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.STOP_LIMIT,
        qty=0.5,
        price=99.5,
        trigger_price=100.0,
        tif=TimeInForce.GTC,
        reduce_only=True,
        order_id="client-1",
        tag="bracket-entry",
        metadata={"arb_id": "ARB-1"},
    )

    table = build_nautilus_package_order_table(
        [order],
        instrument_ids={"ETHUSDT": "ETHUSDT-PERP.BINANCE"},
    )

    assert table.loc[0, "symbol"] == "ETHUSDT"
    assert table.loc[0, "instrument_id"] == "ETHUSDT-PERP.BINANCE"
    assert table.loc[0, "order_type"] == "stop_limit"
    assert table.loc[0, "price"] == 99.5
    assert table.loc[0, "trigger_price"] == 100.0
    assert table.loc[0, "tif"] == "gtc"
    assert bool(table.loc[0, "reduce_only"]) is True
    assert table.loc[0, "order_id"] == "client-1"
    assert table.loc[0, "tag"] == "bracket-entry"
    assert table.loc[0, "arb_id"] == "ARB-1"


def test_ensure_utc_ohlcv_normalizes_common_market_data_shape():
    raw = pd.DataFrame(
        {
            "Date": ["2024-01-02 00:00:00", "2024-01-01 00:00:00"],
            "Open": [11.0, 10.0],
            "High": [12.0, 11.0],
            "Low": [10.0, 9.0],
            "Close": [11.5, 10.5],
            "Volume": [101.0, 100.0],
        }
    )

    out = ensure_utc_ohlcv(raw)

    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert str(out.index.tz) == "UTC"
    assert out.index[0] == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    assert out["close"].iloc[0] == 10.5


def test_result_from_nautilus_reports_converts_account_equity_contract():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    account = pd.DataFrame({"total": [10_000.0, 10_100.0, 10_050.0]}, index=idx)

    result = result_from_nautilus_reports(
        account_report=account,
        symbols=["BTCUSDT-PERP.BINANCE"],
        initial_capital=10_000.0,
    )

    assert result.metadata["backend"] == "nautilus"
    assert result.equity.tolist() == [10_000.0, 10_100.0, 10_050.0]
    assert result.returns.iloc[0] == 0.0
    assert "Position_BTCUSDT-PERP.BINANCE" in result.positions.columns


def test_result_from_nautilus_reports_accepts_money_strings():
    idx = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    account = pd.DataFrame({"total": ["10000 USDT", "10025.5 USDT"]}, index=idx)

    result = result_from_nautilus_reports(
        account_report=account,
        symbols=["BTCUSDT-PERP.BINANCE"],
        initial_capital=10_000.0,
    )

    assert result.equity.tolist() == [10_000.0, 10_025.5]


def test_result_from_nautilus_reports_rebuilds_positions_from_fills():
    idx = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    account = pd.DataFrame({"total": [10_000.0, 10_010.0, 10_020.0, 10_030.0]}, index=idx)
    fills = pd.DataFrame(
        {
            "instrument_id": ["BTCUSDT-PERP.BINANCE", "BTCUSDT-PERP.BINANCE"],
            "side": ["BUY", "SELL"],
            "filled_qty": [2.0, 0.5],
            "ts_last": [idx[1], idx[2]],
        }
    )

    result = result_from_nautilus_reports(
        account_report=account,
        fills_report=fills,
        orders_report=fills,
        symbols=["BTCUSDT-PERP.BINANCE"],
        initial_capital=10_000.0,
    )

    pos = result.positions["Position_BTCUSDT-PERP.BINANCE"]
    assert pos.iloc[0] == 0.0
    assert pos.iloc[1] == 2.0
    assert pos.iloc[2] == 1.5
    assert pos.iloc[3] == 1.5
    assert result.metadata["fills_count"] == 2


def test_result_from_nautilus_reports_reconstructs_full_bar_equity_from_fills():
    idx = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    account = pd.DataFrame({"total": [10_000.0, 10_020.0]}, index=[idx[1], idx[2]])
    fills = pd.DataFrame(
        {
            "instrument_id": ["BTCUSDT-PERP.BINANCE", "BTCUSDT-PERP.BINANCE"],
            "side": ["BUY", "SELL"],
            "filled_qty": [2.0, 0.5],
            "avg_px": [110.0, 120.0],
            "commissions": ["0 USDT", "0 USDT"],
            "ts_last": [idx[1], idx[2]],
        }
    )
    closes = {"BTCUSDT-PERP.BINANCE": pd.Series([100.0, 110.0, 120.0, 115.0], index=idx)}

    result = result_from_nautilus_reports(
        account_report=account,
        fills_report=fills,
        orders_report=fills,
        symbols=["BTCUSDT-PERP.BINANCE"],
        initial_capital=10_000.0,
        closes=closes,
    )

    assert result.equity.index.equals(idx)
    assert result.closes["Close_BTCUSDT-PERP.BINANCE"].tolist() == [100.0, 110.0, 120.0, 115.0]
    assert result.equity.tolist() == [10_000.0, 10_000.0, 10_020.0, 10_012.5]
    assert result.metadata["account_equity"].tolist() == [10_000.0, 10_020.0]
    assert result.metadata["equity_source"] == "fills_reconstructed"
    assert result.metadata["account_reconstructed_diff"] == -7.5


def test_nautilus_config_validates_identifiers_and_capital():
    with pytest.raises(ValueError):
        NautilusBackendConfig(starting_balance=0.0)
    with pytest.raises(ValueError):
        NautilusBackendConfig(strategy_id="QuantBT")
    with pytest.raises(ValueError):
        NautilusBackendConfig(trader_id="BACKTESTER")


def test_nautilus_config_accepts_force_flat_alias():
    cfg = NautilusBackendConfig(force_flat_on_stop=True)

    assert cfg.close_positions_on_stop is True


def test_nautilus_dependency_is_lazy_and_reports_missing_package_cleanly():
    try:
        import nautilus_trader  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="optional 'nautilus_trader'"):
            NautilusBacktestEngine.check_available()
