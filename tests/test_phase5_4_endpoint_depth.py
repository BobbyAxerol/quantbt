from __future__ import annotations

import pandas as pd

from quantbt import (
    BasketExecutionPolicy,
    BasketLegSpec,
    BasketSpec,
    BracketOrderSpec,
    DcaGridSpec,
    NautilusExecutionDepthConfig,
    OrderSide,
    QuantBTEndpoint,
    build_nautilus_depth_parity_summary,
)
from quantbt.core.results import BacktestResultV2


def _df():
    idx = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0] * len(idx),
            "high": [100.0, 101.0, 101.0, 111.0, 100.0, 100.0],
            "low": [100.0, 99.0, 99.5, 94.0, 99.0, 99.0],
            "close": [100.0, 100.0, 100.0, 110.0, 100.0, 100.0],
            "volume": [100.0] * len(idx),
        },
        index=idx,
    )


def _install_fake_nautilus(monkeypatch):
    import quantbt.adapters.nautilus as nautilus_module

    captured = {"runs": 0}

    class FakeNautilusBacktestEngine:
        def __init__(self, config):
            captured["config"] = config

        def run_order_packages(self, data, orders, symbols, params=None):
            captured["runs"] += 1
            captured["data"] = data
            captured["orders"] = tuple(orders)
            captured["symbols"] = list(symbols)
            captured["params"] = dict(params or {})
            idx = next(iter(data.values())).index
            return BacktestResultV2(
                equity=pd.Series(10_000.0, index=idx),
                returns=pd.Series(0.0, index=idx),
                positions=pd.DataFrame({f"Position_{symbol}": 0.0 for symbol in symbols}, index=idx),
                closes=pd.DataFrame({f"Close_{symbol}": data[symbol]["close"] for symbol in symbols}, index=idx),
                symbols=list(symbols),
                initial_capital=10_000.0,
                metadata={
                    "backend": "nautilus",
                    "engine": "nautilus_package_orders",
                    "orders_count": len(orders),
                    "fills_count": len(orders),
                    **captured["params"],
                },
            )

    monkeypatch.setattr(nautilus_module, "NautilusBacktestEngine", FakeNautilusBacktestEngine)
    return captured


def test_phase5_4_endpoint_depth_can_reject_structured_package_before_nautilus(monkeypatch):
    captured = _install_fake_nautilus(monkeypatch)
    df = _df()
    idx = df.index

    endpoint = QuantBTEndpoint.nautilus_dca_grid(
        spec=DcaGridSpec(
            symbol="ETHUSDT-PERP.BINANCE",
            entry_timestamp=idx[1],
            side=OrderSide.BUY,
            base_notional=1_000.0,
            safety_notional=500.0,
            safety_order_count=1,
            step_pct=0.20,
        ),
        initial_capital=10_000.0,
        use_funding=False,
        nautilus_depth_config=NautilusExecutionDepthConfig(
            all_or_none_packages=True,
            all_or_none_package_types=("dca_grid",),
        ),
    )

    result = endpoint.simulate(data=df)

    assert captured["runs"] == 0
    assert result.metadata["engine"] == "nautilus_dca_grid"
    assert result.metadata["nautilus_depth_enabled"] is True
    assert result.metadata["order_count_before_depth"] == 2
    assert result.metadata["order_count_after_depth"] == 0
    assert result.metadata["nautilus_depth_package_report"].iloc[0]["status"] == "rejected"


def test_phase5_4_endpoint_depth_filters_bracket_oco_before_nautilus(monkeypatch):
    captured = _install_fake_nautilus(monkeypatch)
    df = _df()
    idx = df.index

    endpoint = QuantBTEndpoint.nautilus_bracket_orders(
        spec=BracketOrderSpec(
            symbol="ETHUSDT-PERP.BINANCE",
            entry_timestamp=idx[1],
            exit_timestamp=idx[3],
            side=OrderSide.BUY,
            qty=1.0,
            take_profit_price=110.0,
            stop_loss_price=95.0,
        ),
        initial_capital=10_000.0,
        use_funding=False,
        nautilus_depth_config=NautilusExecutionDepthConfig(),
    )

    result = endpoint.simulate(data=df)

    assert captured["runs"] == 1
    assert len(captured["orders"]) == 2
    assert [order.metadata["leg_role"] for order in captured["orders"]] == ["entry", "take_profit"]
    assert captured["params"]["order_count_before_depth"] == 3
    assert captured["params"]["order_count_after_depth"] == 2
    assert captured["params"]["nautilus_depth_order_report"]["status"].tolist() == ["filled", "filled", "canceled"]
    assert result.metadata["nautilus_depth_enabled"] is True
    summary = build_nautilus_depth_parity_summary(result)
    assert summary["status"] == "pass"
    assert summary["accepted_after_depth"] == 2
    assert summary["depth_canceled"] == 1


def test_phase5_4_endpoint_depth_annotates_basket_package_reports(monkeypatch):
    captured = _install_fake_nautilus(monkeypatch)
    df = _df()
    data = {
        "BTCUSDT-PERP.BINANCE": df,
        "ETHUSDT-PERP.BINANCE": df.assign(close=df["close"] * 0.5),
    }
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0, 0.0], index=df.index)
    basket = BasketSpec(
        basket_id="DEPTH-BASKET",
        legs=(
            BasketLegSpec("BTCUSDT-PERP.BINANCE", 1.0),
            BasketLegSpec("ETHUSDT-PERP.BINANCE", -1.0),
        ),
        gross_notional=10_000.0,
        execution_policy=BasketExecutionPolicy.ALL_OR_NONE,
    )

    endpoint = QuantBTEndpoint.basket(
        basket=basket,
        backend="nautilus",
        initial_capital=10_000.0,
        use_funding=False,
        nautilus_depth_config=NautilusExecutionDepthConfig(all_or_none_packages=True),
    )
    result = endpoint.simulate(data=data, signal=signal)

    assert captured["runs"] == 1
    assert result.metadata["nautilus_depth_enabled"] is True
    assert result.metadata["order_count_before_depth"] == 4
    assert result.metadata["order_count_after_depth"] == 4
    assert result.metadata["nautilus_depth_package_report"]["status"].tolist() == ["accepted", "accepted"]
    assert all(order.metadata["package_type"] == "basket_package" for order in captured["orders"])
