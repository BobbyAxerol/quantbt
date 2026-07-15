"""Minimal basis arbitrage endpoint example."""

from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import (
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
)


idx = pd.date_range("2024-01-01", periods=6, freq="1D", tz="UTC")
perp = pd.Series([100.0, 101.0, 102.0, 101.5, 101.0, 100.5], index=idx)
quarterly = pd.Series([102.0, 103.0, 103.5, 102.0, 101.5, 101.0], index=idx)

data = {
    "BTC-PERP": pd.DataFrame({"open": perp, "high": perp + 0.5, "low": perp - 0.5, "close": perp, "volume": 1_000.0}),
    "BTC-QUARTERLY": pd.DataFrame(
        {"open": quarterly, "high": quarterly + 0.5, "low": quarterly - 0.5, "close": quarterly, "volume": 1_000.0}
    ),
}
signal = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0, 0.0], index=idx)

spec = BasisArbitrageSpec(
    arb_id="BTC_BASIS_EXAMPLE",
    legs=(
        ArbitrageLeg("BTC-PERP", ratio=-1.0, role="perp", contract_type=ContractType.LINEAR, qty_step=0.001),
        ArbitrageLeg("BTC-QUARTERLY", ratio=1.0, role="quarterly", contract_type=ContractType.LINEAR, qty_step=0.001),
    ),
    hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
    sizing_policy=SizingPolicy(
        SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
        notional=10_000.0,
        reference_symbol="BTC-PERP",
    ),
)

bt = QuantBTEndpoint.arbitrage(
    arb_type="basis",
    spec=spec,
    backend="native_vectorized",
    initial_capital=100_000.0,
    leverage=5.0,
    fee_rate=0.0,
    use_funding=False,
)

result = bt.simulate(data=data, signal=signal)

print(result.equity.tail())
print(result.metadata["package_target_units"].tail())
print(result.metadata["spread_report"].tail())
