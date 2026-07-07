from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import (
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    PackageExecutionKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
)
from quantbt.core.schema import AccountConfig, OrderSide


PERP = "BTCUSDT-PERP.BINANCE"
QUARTERLY = "BTCUSDT-QUARTERLY.BINANCE"


def _idx():
    return pd.date_range("2024-01-01", periods=4, freq="8h", tz="UTC")


def _closes(idx):
    return {
        PERP: pd.Series([100.0, 100.0, 105.0, 110.0], index=idx),
        QUARTERLY: pd.Series([102.0, 102.0, 104.0, 106.0], index=idx),
    }


def _frames(idx):
    return {
        symbol: pd.DataFrame(
            {
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 0.0,
            },
            index=idx,
        )
        for symbol, close in _closes(idx).items()
    }


def _signal(idx):
    return pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)


def _basis_spec():
    return BasisArbitrageSpec(
        arb_id="BTC_USDM_PERP_QUARTERLY",
        legs=(
            ArbitrageLeg(
                symbol=PERP,
                ratio=-1.0,
                role="perp",
                contract_type=ContractType.LINEAR,
                qty_step=0.001,
                min_qty=0.001,
                min_notional=10.0,
                fee_rate=0.001,
                funding_enabled=True,
            ),
            ArbitrageLeg(
                symbol=QUARTERLY,
                ratio=1.0,
                role="quarterly",
                contract_type=ContractType.LINEAR,
                qty_step=0.001,
                min_qty=0.001,
                min_notional=10.0,
                fee_rate=0.001,
                funding_enabled=False,
            ),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(
            kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=10_000.0,
            reference_symbol=PERP,
        ),
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )


def test_phase_c_basis_arbitrage_runs_package_trade_with_leg_pnl_reports():
    idx = _idx()
    spec = _basis_spec()
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=True,
        )
    )

    result = backend.run_basis_arbitrage(
        datetime_index=idx,
        spec=spec,
        signal=_signal(idx),
        closes=_closes(idx),
        funding_rate={PERP: pd.Series([0.0, 0.0, 0.01, 0.0], index=idx)},
    )

    plan = result.metadata["arbitrage_plan"]
    assert plan.target_units.loc[idx[1], PERP] == -100.0
    assert plan.target_units.loc[idx[1], QUARTERLY] == 100.0
    assert abs(plan.target_units.loc[idx[1], PERP]) == abs(plan.target_units.loc[idx[1], QUARTERLY])
    assert abs(plan.target_units.loc[idx[1], PERP]) * 100.0 != abs(plan.target_units.loc[idx[1], QUARTERLY]) * 102.0

    fills = result.fills
    assert len(fills) == 4
    assert [fill.timestamp for fill in fills[:2]] == [idx[1], idx[1]]
    assert [fill.timestamp for fill in fills[2:]] == [idx[3], idx[3]]
    assert fills[0].side is OrderSide.SELL
    assert fills[1].side is OrderSide.BUY
    assert result.positions[f"Position_{PERP}"].loc[idx[3]] == 0.0
    assert result.positions[f"Position_{QUARTERLY}"].loc[idx[3]] == 0.0

    leg_pnl = result.metadata["leg_pnl_report"]
    package_pnl = result.metadata["package_pnl_report"]
    grouped_leg_pnl = leg_pnl.groupby("timestamp")["total_pnl"].sum().reindex(idx, fill_value=0.0)
    np.testing.assert_allclose(grouped_leg_pnl.to_numpy(), package_pnl["package_pnl"].to_numpy(), atol=1e-10)
    np.testing.assert_allclose(package_pnl["package_pnl"].to_numpy(), result.equity.diff().fillna(0.0).to_numpy(), atol=1e-10)

    perp_funding = leg_pnl[(leg_pnl["timestamp"] == idx[2]) & (leg_pnl["symbol"] == PERP)]["funding_pnl"].iloc[0]
    quarterly_funding = leg_pnl[(leg_pnl["timestamp"] == idx[2]) & (leg_pnl["symbol"] == QUARTERLY)]["funding_pnl"].iloc[0]
    assert perp_funding == 105.0
    assert quarterly_funding == 0.0
    assert result.metadata["spread_report"].loc[idx[1], "spread"] == 2.0


def test_phase_c_arbitrage_endpoint_runs_basis_native_event():
    idx = _idx()
    endpoint = QuantBTEndpoint.arbitrage(
        arb_type="basis",
        spec=_basis_spec(),
        initial_capital=20_000.0,
        leverage=10.0,
        use_funding=False,
    )

    result = endpoint.simulate(data=_frames(idx), signal=_signal(idx))

    assert result.metadata["engine"] == "event_v1_basis_arbitrage"
    assert "spread_report" in result.metadata
    assert "leg_pnl_report" in result.metadata
    assert result.metadata["fills_count"] == 4
    assert endpoint.fills_report.shape[0] == 4
