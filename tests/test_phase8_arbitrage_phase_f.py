from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    ArbitrageLeg,
    BacktestResultV2,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
    build_arbitrage_order_plan,
)
from quantbt.adapters import nautilus as nautilus_mod
from quantbt.adapters.nautilus import NautilusBackendConfig, NautilusBacktestEngine, build_nautilus_package_order_table
from quantbt.adapters.nautilus._dependency import require_nautilus
from quantbt.core.schema import AccountConfig


BTC = "BTCUSDT-PERP.BINANCE"
ETH = "ETHUSDT-PERP.BINANCE"


def _idx():
    return pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC")


def _closes(idx):
    return {
        BTC: pd.Series([50_000.0 + i * 10.0 for i in range(len(idx))], index=idx),
        ETH: pd.Series([3_000.0 + i * 2.0 for i in range(len(idx))], index=idx),
    }


def _frames(idx):
    return {
        symbol: pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 1_000.0},
            index=idx,
        )
        for symbol, close in _closes(idx).items()
    }


def _signal(idx):
    return pd.Series([0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0], index=idx)


def _stat_spec():
    return StatArbPairSpec(
        arb_id="BTC_ETH_STAT",
        legs=(
            ArbitrageLeg(symbol=BTC, ratio=1.0, asset_class="crypto"),
            ArbitrageLeg(symbol=ETH, ratio=-0.5, asset_class="crypto"),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BETA_NEUTRAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=20_000.0),
    )


def test_phase_f_builds_nautilus_package_order_map_from_quantbt_orders():
    idx = _idx()
    spec = _stat_spec()
    plan = build_arbitrage_order_plan(
        datetime_index=idx,
        spec=spec,
        signal=_signal(idx),
        closes=_closes(idx),
    )

    table = build_nautilus_package_order_table(plan.orders)

    assert len(table) == len(plan.orders)
    assert set(table["instrument_id"]) == {BTC, ETH}
    assert set(table["arb_id"]) == {"BTC_ETH_STAT"}
    assert set(table["arb_type"]) == {"stat_arb_pair"}
    assert table.iloc[0]["timestamp"] == idx[2]
    assert table.iloc[0]["target_units"] == plan.orders[0].metadata["target_units"]


def test_phase_f_arbitrage_endpoint_routes_package_orders_to_nautilus_adapter(monkeypatch):
    captured = {}

    class FakeNautilusEngine:
        def __init__(self, config):
            captured["config"] = config

        def run_order_packages(self, data, orders, symbols, params=None):
            captured["data"] = data
            captured["orders"] = tuple(orders)
            captured["symbols"] = list(symbols)
            captured["params"] = dict(params or {})
            idx = next(iter(data.values())).index
            close_df = pd.DataFrame({f"Close_{symbol}": data[symbol]["close"] for symbol in symbols}, index=idx)
            return BacktestResultV2(
                equity=pd.Series(10_000.0, index=idx, name="equity"),
                returns=pd.Series(0.0, index=idx, name="returns"),
                positions=pd.DataFrame({f"Position_{symbol}": 0.0 for symbol in symbols}, index=idx),
                closes=close_df,
                symbols=list(symbols),
                initial_capital=10_000.0,
                metadata={
                    "backend": "nautilus",
                    "engine": "nautilus_package_orders",
                    "package_order_map": build_nautilus_package_order_table(orders),
                    **(params or {}),
                },
            )

    monkeypatch.setattr(nautilus_mod, "NautilusBacktestEngine", FakeNautilusEngine)
    idx = _idx()
    endpoint = QuantBTEndpoint.arbitrage(
        arb_type="stat_arb_pair",
        spec=_stat_spec(),
        backend="nautilus",
        initial_capital=10_000.0,
        leverage=5.0,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            timeframe="1h",
            starting_balance=99_999.0,
            trade_notional=123.0,
            sizing_mode="notional",
        ),
    )

    result = endpoint.simulate(data=_frames(idx), signal=_signal(idx))

    assert captured["config"].starting_balance == 10_000.0
    assert captured["config"].trade_notional == 0.0
    assert captured["symbols"] == [BTC, ETH]
    assert len(captured["orders"]) > 0
    assert captured["params"]["arb_id"] == "BTC_ETH_STAT"
    assert "package_target_units" in captured["params"]
    assert result.metadata["engine"] == "nautilus_arbitrage_package"
    assert result.metadata["package_order_map"].shape[0] == len(captured["orders"])


def test_phase_f_nautilus_package_orders_optional_smoke_matches_native_event_targets():
    try:
        require_nautilus()
    except ImportError:
        pytest.skip("nautilus_trader not installed")

    idx = _idx()
    spec = _stat_spec()
    native = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0),
            fee_rate=0.0,
            use_funding=False,
        )
    ).run_stat_arb_pair_arbitrage(
        datetime_index=idx,
        spec=spec,
        signal=_signal(idx),
        closes=_closes(idx),
    )
    result = NautilusBacktestEngine(
        NautilusBackendConfig(
            timeframe="1h",
            starting_balance=20_000.0,
            trade_notional=0.0,
            sizing_mode="notional",
            bypass_risk=True,
        )
    ).run_order_packages(
        data=_frames(idx),
        orders=native.metadata["arbitrage_plan"].orders,
        symbols=[BTC, ETH],
        params={
            "arb_id": spec.arb_id,
            "arb_type": spec.arb_type.value,
            "package_target_units": native.metadata["package_target_units"],
        },
    )

    assert result.metadata["engine"] == "nautilus_package_orders"
    assert result.metadata["package_orders_count"] == len(native.metadata["arbitrage_plan"].orders)
    assert result.metadata["package_order_map"].shape[0] == len(native.metadata["arbitrage_plan"].orders)
    assert np.isfinite(result.equity.iloc[-1])
