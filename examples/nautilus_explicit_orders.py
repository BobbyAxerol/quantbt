"""Replay explicit QuantBT orders through native-event and Nautilus backends."""

from __future__ import annotations

import pandas as pd

from _bootstrap import PROJECT_ROOT  # noqa: F401

from quantbt import AccountConfig, BacktestEngineV2, build_native_nautilus_parity_report
from quantbt.adapters.nautilus import NautilusBackendConfig
from quantbt.core.orders import OrderIntent
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def main() -> None:
    idx = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0], index=idx)
    data = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="ETHUSDT-PERP.BINANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=0.1,
            tif=TimeInForce.IOC,
            tag="entry",
        ),
        OrderIntent(
            timestamp=idx[5],
            symbol="ETHUSDT-PERP.BINANCE",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=0.1,
            tif=TimeInForce.IOC,
            reduce_only=True,
            tag="exit",
        ),
    ]
    common = dict(
        data=data,
        orders=orders,
        symbols=["ETHUSDT-PERP.BINANCE"],
        account=AccountConfig(initial_capital=10_000.0),
        use_funding=False,
    )

    native = BacktestEngineV2(backend="native_event", fee_rate=0.0, **common).result
    nautilus = BacktestEngineV2(
        backend="nautilus",
        nautilus_config=NautilusBackendConfig(
            instrument_id="ETHUSDT-PERP.BINANCE",
            timeframe="1h",
            starting_balance=10_000.0,
            bypass_risk=True,
        ),
        **common,
    ).result

    parity = build_native_nautilus_parity_report(native, nautilus)
    print(parity[["timestamp", "side", "native_fill_price", "nautilus_fill_price", "equity_diff"]])


if __name__ == "__main__":
    main()
