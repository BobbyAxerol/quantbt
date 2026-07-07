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
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    PackageExecutionKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
)
from quantbt.core.schema import AccountConfig


PERP = "BTCUSDT-PERP.BINANCE"
QUARTERLY = "BTCUSDT-QUARTERLY.BINANCE"
BASE = "BASE"
HEDGE = "HEDGE"


def _idx():
    return pd.date_range("2024-01-01", periods=4, freq="8h", tz="UTC")


def _basis_closes(idx):
    return {
        PERP: pd.Series([100.0, 100.0, 105.0, 110.0], index=idx),
        QUARTERLY: pd.Series([102.0, 102.0, 104.0, 106.0], index=idx),
    }


def _basis_signal(idx):
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


def _stat_closes(idx):
    return {
        BASE: pd.Series([10.0, 10.0, 20.0, 20.0], index=idx),
        HEDGE: pd.Series([100.0, 100.0, 120.0, 120.0], index=idx),
    }


def _stat_signal(idx):
    return pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)


def _stat_hedge_ratios(idx):
    return {
        BASE: pd.Series([1.0, 1.0, 1.0, 1.0], index=idx),
        HEDGE: pd.Series([-0.5, -0.5, -2.0, -2.0], index=idx),
    }


def _stat_spec():
    return StatArbPairSpec(
        arb_id="STAT_PAIR_001",
        legs=(
            ArbitrageLeg(symbol=BASE, ratio=1.0, asset_class="crypto"),
            ArbitrageLeg(symbol=HEDGE, ratio=-0.5, asset_class="crypto"),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BETA_NEUTRAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=600.0),
    )


def _event_backend():
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=False,
        )
    )


def _vectorized_backend():
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=False,
        )
    )


def test_phase_e_vectorized_basis_matches_native_event_market_fill_parity():
    idx = _idx()
    event = _event_backend().run_basis_arbitrage(
        datetime_index=idx,
        spec=_basis_spec(),
        signal=_basis_signal(idx),
        closes=_basis_closes(idx),
    )
    vectorized = _vectorized_backend().run_basis_arbitrage(
        datetime_index=idx,
        spec=_basis_spec(),
        signal=_basis_signal(idx),
        closes=_basis_closes(idx),
    )

    np.testing.assert_allclose(vectorized.equity.to_numpy(), event.equity.to_numpy(), atol=1e-10)
    np.testing.assert_allclose(vectorized.positions.to_numpy(), event.positions.to_numpy(), atol=1e-10)
    assert vectorized.metadata["engine"] == "units_v2_basis_arbitrage"
    assert vectorized.metadata["package_target_units"].loc[idx[1], PERP] == -100.0
    assert vectorized.metadata["package_target_units"].loc[idx[3], QUARTERLY] == 0.0
    np.testing.assert_allclose(
        vectorized.metadata["package_pnl_report"]["pnl_residual"].to_numpy(),
        0.0,
        atol=1e-10,
    )


def test_phase_e_vectorized_stat_arb_matches_native_event_and_reports_beta_drift():
    idx = _idx()
    event = _event_backend().run_stat_arb_pair_arbitrage(
        datetime_index=idx,
        spec=_stat_spec(),
        signal=_stat_signal(idx),
        closes=_stat_closes(idx),
        hedge_ratios=_stat_hedge_ratios(idx),
    )
    vectorized = _vectorized_backend().run_stat_arb_pair_arbitrage(
        datetime_index=idx,
        spec=_stat_spec(),
        signal=_stat_signal(idx),
        closes=_stat_closes(idx),
        hedge_ratios=_stat_hedge_ratios(idx),
    )

    np.testing.assert_allclose(vectorized.equity.to_numpy(), event.equity.to_numpy(), atol=1e-10)
    np.testing.assert_allclose(vectorized.positions.to_numpy(), event.positions.to_numpy(), atol=1e-10)
    beta_drift = vectorized.metadata["beta_drift_report"]
    hedge_drift = beta_drift[(beta_drift["timestamp"] == idx[2]) & (beta_drift["symbol"] == HEDGE)].iloc[0]
    assert hedge_drift["rel_beta_drift"] == 3.0
    assert vectorized.metadata["package_target_units"].loc[idx[2], HEDGE] == -5.0


def test_phase_e_arbitrage_endpoint_supports_native_vectorized_backend():
    idx = _idx()
    endpoint = QuantBTEndpoint.arbitrage(
        arb_type="basis",
        spec=_basis_spec(),
        backend="native_vectorized",
        initial_capital=20_000.0,
        leverage=10.0,
        use_funding=False,
    )

    result = endpoint.simulate(
        closes=_basis_closes(idx),
        datetime_index=idx,
        signal=_basis_signal(idx),
    )

    assert result.metadata["backend"] == "native_vectorized"
    assert result.metadata["engine"] == "units_v2_basis_arbitrage"
    assert "spread_report" in result.metadata
