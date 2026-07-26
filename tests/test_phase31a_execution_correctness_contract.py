from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    BacktestEngineV2,
    ExecutionConfig,
    FillPricePolicy,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    TimeInForce,
)
from quantbt.core.preprocessor import prepare_funding
from quantbt.core.schema import AccountConfig


def _ohlcv() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.0, 101.0, 102.0, 103.0],
            "volume": [10.0, 11.0, 12.0, 13.0],
        },
        index=idx,
    )


def test_phase31a_native_vectorized_declares_close_target_contract_metadata():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    close = pd.Series([100.0, 101.0, 102.0], index=idx)
    target = pd.Series([0.0, 1.0, 1.0], index=idx)
    backend = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            use_funding=False,
        )
    )

    result = backend.run_target_units(
        datetime_index=idx,
        target_units={"BTC": target},
        closes={"BTC": close},
        highs={"BTC": close},
        lows={"BTC": close},
    )

    assert result.metadata["engine"] == "close_target_v2"
    assert result.metadata["engine_id"] == "close_target_v2"
    assert result.metadata["kernel_version"] == "units_v2"
    assert result.metadata["execution_contract"]["signal_phase"] == "bar_close"
    assert result.metadata["execution_contract"]["fill_phase"] == "same_close"
    assert result.metadata["intrabar_exit_model"] == "none"
    assert result.metadata["first_bar_target_policy"].startswith("target_units[0]_not_executed")
    assert result.metadata["data_signature"].length == 3


def test_phase31a_funding_dict_missing_symbol_is_explicit_error():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    with pytest.raises(KeyError, match="missing symbol 'ETH'"):
        prepare_funding({"BTC": 0.0}, ["BTC", "ETH"], idx)


def test_phase31a_native_vectorized_rejects_unsupported_execution_config():
    with pytest.raises(NotImplementedError, match="close_target_v2"):
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=10_000.0),
            execution=ExecutionConfig(fill_price_policy=FillPricePolicy.NEXT_OPEN),
        )


def test_phase31a_missing_high_low_is_marked_uncertified_instead_of_silent():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    close = pd.Series([100.0, 101.0, 102.0], index=idx)
    target = pd.Series([0.0, 1.0, 1.0], index=idx)
    backend = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            use_funding=False,
        )
    )

    with pytest.warns(RuntimeWarning, match="missing high/low"):
        result = backend.run_target_units(
            datetime_index=idx,
            target_units={"BTC": target},
            closes={"BTC": close},
        )

    assert result.metadata["high_low_source"] == "close_fallback_uncertified_intrabar_risk"


def test_phase31a_endpoint_warns_when_close_target_receives_intrabar_columns():
    df = _ohlcv()
    df["pos_weight"] = [0.0, 1.0, 1.0, 0.0]
    df["exit_price"] = [0.0, 0.0, 99.0, 0.0]
    endpoint = QuantBTEndpoint.signal_notional(
        backend="native_vectorized",
        initial_capital=10_000.0,
        leverage=5.0,
        use_funding=False,
        alloc_per_trade=1_000.0,
    )

    with pytest.warns(RuntimeWarning, match="close_target_v2"):
        result = endpoint.backtest(data=df, signal_col="pos_weight", symbols=["BTC"])

    assert result.metadata["intrabar_misuse_markers"] == ["exit_price"]
    assert result.metadata["certification_status"] == "uncertified_intrabar_columns_on_close_target"


def test_phase31a_reactive_event_context_receives_open_and_volume_from_facade():
    df = _ohlcv()

    class Strategy:
        def __init__(self):
            self.seen = []

        def on_bar_close(self, context):
            self.seen.append((context.bar_index, float(context.open[0]), float(context.volume[0])))
            if context.bar_index == 0:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        qty=1.0,
                        tif=TimeInForce.IOC,
                        order_id="entry",
                    )
                ]
            return []

    strategy = Strategy()
    BacktestEngineV2(
        data=df,
        signals=pd.Series(0.0, index=df.index),
        backend="native_event",
        account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
        strategy=strategy,
        symbols=["BTC"],
        use_funding=False,
    )

    assert strategy.seen[0] == (0, 100.0, 10.0)
    assert strategy.seen[1] == (1, 101.0, 11.0)
