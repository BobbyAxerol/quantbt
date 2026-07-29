from __future__ import annotations

import pandas as pd

from quantbt import AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig, QuantBTEndpoint
from quantbt.core.orders import OrderAction, OrderCommand
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def _market(n: int = 8):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series([100.0, 100.0, 101.0, 103.0, 98.0, 99.0, 104.0, 100.0][:n], index=idx)
    high = pd.Series([101.0, 102.0, 104.0, 106.0, 100.0, 101.0, 106.0, 103.0][:n], index=idx)
    low = pd.Series([99.0, 98.0, 99.0, 100.0, 94.0, 96.0, 101.0, 98.0][:n], index=idx)
    frame = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1_000.0}, index=idx)
    return idx, frame, {"BTC": close}, {"BTC": high}, {"BTC": low}


def _commands(idx):
    return [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=99.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=idx[2],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=105.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            order_id="take-profit",
        ),
        OrderCommand(
            timestamp=idx[2],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=97.0,
            tif=TimeInForce.GTD,
            reduce_only=True,
            order_id="expires",
            expires_at=idx[4],
        ),
        OrderCommand(timestamp=idx[5], action=OrderAction.CANCEL, target_order_id="take-profit"),
    ]


def _backend(report_level: str, audit_sink: str = "memory", audit_sink_path=None):
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0,
            use_funding=False,
            report_level=report_level,
            audit_sink=audit_sink,
            audit_sink_path=audit_sink_path,
        )
    )


def _assert_accounting_equal(left, right):
    pd.testing.assert_series_equal(left.equity, right.equity)
    pd.testing.assert_series_equal(left.returns, right.returns)
    pd.testing.assert_frame_equal(left.positions, right.positions)
    pd.testing.assert_series_equal(left.fees, right.fees)
    pd.testing.assert_series_equal(left.funding, right.funding)
    pd.testing.assert_frame_equal(left.margin, right.margin)
    pd.testing.assert_frame_equal(left.diagnostics, right.diagnostics)
    assert left.liquidated == right.liquidated
    assert left.liquidation_bar == right.liquidation_bar
    assert left.metadata["lifecycle_counters"] == right.metadata["lifecycle_counters"]


def test_native_event_report_levels_preserve_accounting_and_reduce_artifacts():
    idx, _, close, high, low = _market()
    commands = _commands(idx)

    audit = _backend("audit").run_order_commands(idx, commands, close, high, low)
    standard = _backend("standard").run_order_commands(idx, commands, close, high, low)
    minimal = _backend("minimal").run_order_commands(idx, commands, close, high, low)

    _assert_accounting_equal(audit, standard)
    _assert_accounting_equal(audit, minimal)

    assert audit.metadata["report_level"] == "audit"
    assert standard.metadata["report_level"] == "standard"
    assert minimal.metadata["report_level"] == "minimal"

    assert not audit.metadata["command_report"].empty
    assert not audit.metadata["order_events"].empty
    assert len(audit.fills) == audit.metadata["lifecycle_counters"]["fill_count"]

    assert not standard.metadata["command_report"].empty
    assert standard.metadata["order_events"].empty
    assert len(standard.fills) == audit.metadata["lifecycle_counters"]["fill_count"]

    assert minimal.metadata["command_report"].empty
    assert minimal.metadata["order_events"].empty
    assert minimal.fills == ()
    assert minimal.orders == ()
    assert minimal.metadata["compact_fill_ledger"].fill_count == audit.metadata["lifecycle_counters"]["fill_count"]
    assert minimal.metadata["compact_order_event_ledger"] is None
    assert minimal.metadata["compact_command_ledger"].status.tolist() == audit.metadata["compact_command_ledger"].status.tolist()


def test_native_event_audit_jsonl_sink_writes_trace_without_accounting_drift(tmp_path):
    idx, _, close, high, low = _market()
    commands = _commands(idx)

    memory = _backend("audit").run_order_commands(idx, commands, close, high, low)
    disk = _backend("audit", audit_sink="jsonl", audit_sink_path=tmp_path).run_order_commands(
        idx,
        commands,
        close,
        high,
        low,
    )

    _assert_accounting_equal(memory, disk)
    artifacts = disk.metadata["audit_artifacts"]
    assert artifacts["format"] == "jsonl"
    assert artifacts["fill_count"] == memory.metadata["lifecycle_counters"]["fill_count"]
    assert (tmp_path / "command_report.jsonl").exists()
    assert (tmp_path / "order_events.jsonl").exists()
    assert (tmp_path / "fill_ledger.jsonl").exists()


def test_endpoint_propagates_native_event_report_level_and_reactive_tape_policy():
    idx, frame, _, _, _ = _market()

    class Strategy:
        def on_bar_close(self, context):
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

    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        report_level="minimal",
    )
    result = endpoint.simulate(data=frame, strategy=Strategy(), symbols=["BTC"])

    assert result.metadata["report_level"] == "minimal"
    assert result.metadata["emitted_command_count"] == 1
    assert result.metadata["emitted_command_tape"] == ()
    assert result.metadata["emitted_command_tape_retained"] is False
    assert result.metadata["lifecycle_counters"]["fill_count"] == 1
    assert result.fills == ()
