from __future__ import annotations

import pandas as pd
import pytest

from quantbt import AccountConfig, BacktestEngineV2
from quantbt.adapters.nautilus import (
    NautilusBackendConfig,
    NautilusBacktestEngine,
    ensure_utc_ohlcv,
    make_binance_perpetual,
    normalize_binance_perp_symbol,
    result_from_nautilus_reports,
    supported_binance_perpetuals,
    timeframe_to_nautilus,
)
from quantbt.adapters.nautilus._dependency import require_nautilus


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
