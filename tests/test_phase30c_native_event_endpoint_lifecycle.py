from __future__ import annotations

import pandas as pd

from quantbt import (
    AccountConfig,
    BacktestResultV2,
    BracketOrderSpec,
    DcaGridSpec,
    OrderAction,
    OrderCommand,
    OrderIntent,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    TimeInForce,
)
from quantbt.core.event import ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 103.0, 108.0, 96.0, 100.0],
            "high": [100.0, 101.0, 106.0, 111.0, 100.0, 101.0],
            "low": [100.0, 99.0, 98.0, 94.0, 89.0, 99.0],
            "close": [100.0, 100.0, 103.0, 108.0, 96.0, 100.0],
            "volume": 1_000.0,
        },
        index=idx,
    )


def test_endpoint_native_event_lifecycle_accepts_order_commands():
    df = _bars()
    commands = [
        OrderCommand(
            timestamp=df.index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=90.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=df.index[2],
            action=OrderAction.AMEND,
            target_order_id="entry",
            price=99.0,
        ),
    ]

    endpoint = QuantBTEndpoint.native_event_lifecycle(
        initial_capital=10_000.0,
        leverage=10.0,
        use_funding=False,
    )
    result = endpoint.simulate(data=df, order_commands=commands, symbols=["BTC"])

    assert result.metadata["engine"] == "event_v2_lifecycle"
    assert len(result.fills) == 1
    assert result.fills[0].order_id == "entry"
    assert result.fills[0].price == 99.0
    assert "amend" in set(result.metadata["order_events"]["event_name"])
    assert "command_report" in result.metadata


def test_endpoint_orders_v2_converts_legacy_intents_to_lifecycle_place_commands():
    df = _bars()
    orders = [
        OrderIntent(
            timestamp=df.index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.IOC,
            order_id="entry",
        )
    ]

    endpoint = QuantBTEndpoint.orders(
        backend="native_event",
        event_engine_version="v2",
        initial_capital=10_000.0,
        leverage=10.0,
        use_funding=False,
    )
    result = endpoint.simulate(data=df, orders=orders, symbols=["BTC"])

    assert result.metadata["engine"] == "event_v2_lifecycle"
    assert len(result.fills) == 1
    assert result.fills[0].order_id == "entry"


def test_endpoint_native_event_bracket_uses_parent_oco_lifecycle():
    df = _bars()
    spec = BracketOrderSpec(
        package_id="bracket-1",
        entry_timestamp=df.index[1],
        symbol="BTC",
        side=OrderSide.BUY,
        qty=1.0,
        entry_order_type=OrderType.MARKET,
        entry_tif=TimeInForce.IOC,
        take_profit_price=110.0,
        stop_loss_price=93.0,
    )

    endpoint = QuantBTEndpoint.native_event_bracket_orders(
        spec=spec,
        initial_capital=10_000.0,
        leverage=10.0,
        use_funding=False,
    )
    result = endpoint.simulate(data=df)
    report = result.metadata["command_report"].sort_values("original_index")

    assert result.metadata["engine"] == "event_v2_bracket_oco"
    assert [fill.order_id for fill in result.fills] == ["bracket-1:entry", "bracket-1:take-profit"]
    assert int(report.iloc[1]["status"]) == ORDER_STATUS_FILLED
    assert int(report.iloc[2]["status"]) == ORDER_STATUS_CANCELED
    assert "activate" in set(result.metadata["order_events"]["event_name"])


def test_endpoint_native_event_dca_grid_reports_grid_fills_and_oco_cancel():
    df = _bars()
    spec = DcaGridSpec(
        package_id="dca-1",
        entry_timestamp=df.index[1],
        symbol="BTC",
        side=OrderSide.BUY,
        base_qty=1.0,
        safety_order_count=2,
        safety_qty=1.0,
        step_pct=0.05,
        take_profit_price=110.0,
        stop_loss_price=88.0,
    )

    endpoint = QuantBTEndpoint.native_event_dca_grid(
        spec=spec,
        initial_capital=10_000.0,
        leverage=10.0,
        use_funding=False,
    )
    result = endpoint.simulate(data=df)

    fill_ids = [fill.order_id for fill in result.fills]
    assert "dca-1:base" in fill_ids
    assert "dca-1:safety-1" in fill_ids
    assert "dca-1:safety-2" in fill_ids
    assert result.metadata["engine"] == "event_v2_dca_grid"
    assert result.metadata["lifecycle_command_count"] >= 5
    assert not result.metadata["command_report"].empty


def test_endpoint_orders_nautilus_accepts_order_commands_via_package_payload(monkeypatch):
    import quantbt.adapters.nautilus as nautilus_module

    df = _bars()
    captured = {}

    class FakeNautilusBacktestEngine:
        def __init__(self, config):
            captured["config"] = config

        def run_order_packages(self, data, orders, symbols, params=None):
            captured["orders"] = tuple(orders)
            captured["symbols"] = list(symbols)
            captured["params"] = dict(params or {})
            idx = next(iter(data.values())).index
            equity = pd.Series(10_000.0, index=idx, name="equity")
            positions = pd.DataFrame({"Position_BTC": 0.0}, index=idx)
            closes = pd.DataFrame({"Close_BTC": data["BTC"]["close"]}, index=idx)
            return BacktestResultV2(
                equity=equity,
                returns=equity.pct_change().fillna(0.0),
                positions=positions,
                closes=closes,
                symbols=["BTC"],
                initial_capital=10_000.0,
                metadata={"backend": "nautilus", "engine": "fake"},
            )

    monkeypatch.setattr(nautilus_module, "NautilusBacktestEngine", FakeNautilusBacktestEngine)

    endpoint = QuantBTEndpoint.orders(
        backend="nautilus",
        initial_capital=10_000.0,
        use_funding=False,
    )
    commands = [
        OrderCommand(
            timestamp=df.index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            order_id="entry",
        ),
        OrderCommand(timestamp=df.index[2], action=OrderAction.CANCEL, target_order_id="entry"),
    ]

    endpoint.simulate(data=df, order_commands=commands, symbols=["BTC"])

    assert captured["params"]["input_mode"] == "lifecycle_commands"
    assert captured["params"]["command_count_input"] == 2
    assert len(captured["orders"]) == 1
    assert captured["orders"][0].order_id == "entry"
    assert captured["orders"][0].metadata["command_action"] == "place"
