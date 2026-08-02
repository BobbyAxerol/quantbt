from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    NativeEventProfile,
    NativeEventStrategy,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    TimeInForce,
)


def _bars(n: int = 12) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = 100.0 + np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


class EnterExitStrategy:
    def initialize(self, context):
        return ()

    def on_bar_close(self, context):
        if context.bar_index == 0:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=context.symbols[0],
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="entry",
                )
            ]
        if context.bar_index == 4:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=context.symbols[0],
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id="exit",
                )
            ]
        return ()

    def finalize(self, context):
        return ()


def _assert_accounting_equal(left, right) -> None:
    pd.testing.assert_series_equal(left.equity, right.equity)
    pd.testing.assert_series_equal(left.returns, right.returns)
    pd.testing.assert_frame_equal(left.positions, right.positions)
    pd.testing.assert_series_equal(left.fees, right.fees)
    pd.testing.assert_series_equal(left.funding, right.funding)
    pd.testing.assert_frame_equal(left.margin, right.margin)
    assert left.liquidated == right.liquidated
    assert left.liquidation_bar == right.liquidation_bar


def test_phase48c_profile_mapping_and_public_backend_contract():
    expected = {
        "research": ("fast", "single_pass", "minimal", "none"),
        "optimize": ("fast", "single_pass", "score", "none"),
        "audit": ("audit", "replay_certified", "audit", "memory"),
    }

    for profile, values in expected.items():
        endpoint = QuantBTEndpoint.event_driven(
            profile=profile,
            backend="auto",
            initial_capital=10_000,
            use_funding=False,
        )
        config = endpoint.config
        assert config.mode == "native_event_strategy"
        assert config.backend == "native_event"
        assert config.native_backend == "auto"
        assert (
            config.reactive_execution_mode,
            config.reactive_kernel_mode,
            config.report_level,
            config.audit_sink,
        ) == values
        assert config.metadata["event_driven_facade"] == {
            "input_mode": "strategy",
            "profile": profile,
            "backend": "auto",
        }

    assert QuantBTEndpoint.event_driven(backend="python").config.native_backend == "python"
    assert QuantBTEndpoint.event_driven(backend="rust").config.native_backend == "rust"
    assert NativeEventProfile.AUDIT.value == "audit"
    assert isinstance(EnterExitStrategy(), NativeEventStrategy)


def test_phase48c_orders_profile_maps_to_lifecycle_endpoint():
    endpoint = QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile=NativeEventProfile.AUDIT,
        backend="python",
        initial_capital=10_000,
        use_funding=False,
    )

    assert endpoint.config.mode == "orders"
    assert endpoint.config.backend == "native_event"
    assert endpoint.config.native_backend == "python"
    assert endpoint.config.event_engine_version == "v2"
    assert endpoint.config.metadata["event_driven_facade"]["input_mode"] == "orders"


def test_phase48c_profile_controls_are_explicitly_conflict_checked():
    with pytest.raises(ValueError, match="profile='optimize' controls report_level"):
        QuantBTEndpoint.event_driven(profile="optimize", report_level="audit")

    with pytest.raises(ValueError, match="profile='audit' controls reactive_kernel_mode"):
        QuantBTEndpoint.event_driven(profile="audit", reactive_kernel_mode="single_pass")

    with pytest.raises(ValueError, match="input_mode must be"):
        QuantBTEndpoint.event_driven(input_mode="signal")

    with pytest.raises(ValueError, match="backend must be one of"):
        QuantBTEndpoint.event_driven(backend="replay_certified")


def test_phase48c_advanced_native_backend_selector_remains_available():
    endpoint = QuantBTEndpoint.event_driven(
        profile="audit",
        backend="auto",
        native_backend="replay_certified",
    )

    assert endpoint.config.native_backend == "replay_certified"

    with pytest.raises(ValueError, match="either backend=.*native_backend"):
        QuantBTEndpoint.event_driven(backend="python", native_backend="replay_certified")


def test_phase48c_strategy_facade_delegates_without_accounting_change():
    data = _bars()
    facade = QuantBTEndpoint.event_driven(
        profile="audit",
        backend="python",
        initial_capital=10_000,
        leverage=5,
        fee_rate=0.0002,
        use_funding=False,
    )
    direct = QuantBTEndpoint.native_event_strategy(
        reactive_execution_mode="audit",
        reactive_kernel_mode="replay_certified",
        report_level="audit",
        audit_sink="memory",
        native_backend="python",
        initial_capital=10_000,
        leverage=5,
        fee_rate=0.0002,
        use_funding=False,
    )

    facade_result = facade.simulate(data=data, strategy=EnterExitStrategy(), symbols=["BTC"])
    direct_result = direct.simulate(data=data, strategy=EnterExitStrategy(), symbols=["BTC"])

    _assert_accounting_equal(facade_result, direct_result)
    assert facade.config.metadata["event_driven_facade"]["profile"] == "audit"


def test_phase48c_orders_facade_delegates_without_accounting_change():
    data = _bars()
    command = OrderCommand(
        timestamp=data.index[1],
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1.0,
        tif=TimeInForce.IOC,
        order_id="entry",
    )
    facade = QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile="audit",
        backend="python",
        initial_capital=10_000,
        leverage=5,
        fee_rate=0.0002,
        use_funding=False,
    )
    direct = QuantBTEndpoint.native_event_lifecycle(
        native_backend="python",
        report_level="audit",
        reactive_kernel_mode="replay_certified",
        audit_sink="memory",
        initial_capital=10_000,
        leverage=5,
        fee_rate=0.0002,
        use_funding=False,
    )

    facade_result = facade.simulate(data=data, order_commands=[command], symbols=["BTC"])
    direct_result = direct.simulate(data=data, order_commands=[command], symbols=["BTC"])

    _assert_accounting_equal(facade_result, direct_result)
    assert facade.config.metadata["event_driven_facade"]["input_mode"] == "orders"


def test_phase48c_public_result_and_endpoint_report_helpers_remain_available():
    endpoint = QuantBTEndpoint.event_driven(
        profile="research",
        backend="python",
        initial_capital=10_000,
        use_funding=False,
    )
    result = endpoint.simulate(data=_bars(), strategy=EnterExitStrategy(), symbols=["BTC"])

    result_report = result.full_report()
    endpoint_report = endpoint.full_report()
    assert result_report["final_equity"] == pytest.approx(endpoint_report["final_equity"])
    assert endpoint.show_metrics()["num_trades"] == result_report["num_trades"]
