from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
)
from quantbt.backends.native_event import NativeEventBackend, NativeEventConfig


def _case():
    index = pd.date_range("2026-01-01", periods=12, freq="1h", tz="UTC")
    close = np.array(
        [100.0, 101.0, 103.0, 102.0, 98.0, 96.0, 99.0, 104.0, 108.0, 105.0, 103.0, 106.0]
    )
    frame = pd.DataFrame(
        {
            "open": close - 0.25,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.linspace(1_000.0, 2_100.0, len(index)),
        },
        index=index,
    )
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="BTC", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=0.0199, order_id="entry",
        ),
        OrderCommand(
            timestamp=index[4], symbol="BTC", side=OrderSide.SELL,
            order_type=OrderType.LIMIT, qty=0.0099, price=99.0, order_id="reduce",
        ),
        OrderCommand(
            timestamp=index[8], symbol="BTC", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=0.0099, order_id="close",
        ),
    )
    return frame, commands


def _oracle(frame, commands):
    account = AccountConfig(initial_capital=10_000.0, leverage=5.0)
    execution = ExecutionConfig(slippage_bps=2.0)
    backend = NativeEventBackend(
        NativeEventConfig(
            account=account,
            execution=execution,
            fee_rate=0.0005,
            use_funding=True,
            report_level="audit",
            native_backend="python",
            execution_contract="event_lifecycle_v3_next_open",
        )
    )
    return backend.run_order_commands(
        datetime_index=frame.index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        funding_rate=0.0001,
        contract_size=1.0,
        leverage=5.0,
        fee_rate=0.0005,
        symbols=["BTC"],
        qty_step=0.001,
        min_qty=0.001,
        execution_contract="event_lifecycle_v3_next_open",
    )


def test_public_lifecycle_routes_through_one_plan_and_preparation_with_p0_parity():
    frame, commands = _case()
    expected = _oracle(frame, commands)
    endpoint = QuantBTEndpoint.native_event_lifecycle(
        initial_capital=10_000.0,
        leverage=5.0,
        fee_rate=0.0005,
        slippage_bps=2.0,
        use_funding=True,
        funding_rate=0.0001,
        native_backend="python",
        report_level="audit",
        execution_contract="event_lifecycle_v3_next_open",
        qty_step=0.001,
        min_qty=0.001,
    )
    actual = endpoint.simulate(data=frame, order_commands=commands, symbols=["BTC"])

    np.testing.assert_array_equal(actual.equity.to_numpy(), expected.equity.to_numpy())
    np.testing.assert_array_equal(actual.positions.to_numpy(), expected.positions.to_numpy())
    np.testing.assert_array_equal(actual.fees.to_numpy(), expected.fees.to_numpy())
    np.testing.assert_array_equal(actual.funding.to_numpy(), expected.funding.to_numpy())
    np.testing.assert_array_equal(actual.margin.to_numpy(), expected.margin.to_numpy())
    assert [(fill.order_id, fill.qty, fill.price, fill.fee) for fill in actual.fills] == [
        (fill.order_id, fill.qty, fill.price, fill.fee) for fill in expected.fills
    ]
    assert actual.metadata["canonical_trace_fingerprint"] == expected.metadata["canonical_trace_fingerprint"]
    assert actual.metadata["accounting_invariants_v1"]["passed"] is True
    assert actual.metadata["p1_execution_route"] == "plan_prepare_legacy_public_adapter_v1"
    assert actual.metadata["native_event_backend_requested"] == "python"
    assert actual.metadata["native_event_backend_resolved"] == "python"
    assert actual.metadata["quantity_preflight"]["changed_count"] == 3

    plan = actual.metadata["execution_plan_v1"]
    diagnostics = actual.metadata["preparation_diagnostics_v1"]
    assert plan["plan_fingerprint"] == actual.metadata["execution_plan_fingerprint"]
    assert plan["projection_fingerprint"] == actual.metadata["output_projection_fingerprint"]
    assert diagnostics["market_normalizations"] == 1
    assert diagnostics["instrument_normalizations"] == 1
    assert diagnostics["command_compilations"] == 1
    assert diagnostics["backend_resolutions"] == 1
    assert diagnostics["output_projections"] == 1
    assert endpoint.engine.execution_plan.plan_fingerprint == plan["plan_fingerprint"]
    assert endpoint.engine.prepared_run.keys.combined == actual.metadata["prepared_run_keys_v1"]["combined"]


def test_public_score_keeps_result_surface_without_fill_or_event_rows_in_projection():
    frame, commands = _case()
    endpoint = QuantBTEndpoint.native_event_lifecycle(
        initial_capital=10_000.0,
        leverage=5.0,
        use_funding=False,
        native_backend="python",
        report_level="score",
    )
    result = endpoint.simulate(data=frame, order_commands=commands, symbols=["BTC"])

    output = result.metadata["execution_plan_v1"]["output"]
    assert len(result.equity) == len(frame)
    assert output["fill_detail"] == "count"
    assert output["event_detail"] == "count"
    assert output["active_order_detail"] == "none"
    assert output["materialize_pandas"] is True
