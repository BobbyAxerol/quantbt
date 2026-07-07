from __future__ import annotations

import pytest
import pandas as pd

from quantbt import (
    ArbitrageLeg,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
)
from quantbt.core.schema import AccountConfig


BASE = "BASE"
HEDGE = "HEDGE"


def _idx():
    return pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")


def _closes(idx):
    return {
        BASE: pd.Series([10.0, 10.0, 20.0, 20.0], index=idx),
        HEDGE: pd.Series([100.0, 100.0, 120.0, 120.0], index=idx),
    }


def _frames(idx):
    return {
        symbol: pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 0.0},
            index=idx,
        )
        for symbol, close in _closes(idx).items()
    }


def _signal(idx):
    return pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)


def _hedge_ratios(idx):
    return {
        BASE: pd.Series([1.0, 1.0, 1.0, 1.0], index=idx),
        HEDGE: pd.Series([-0.5, -0.5, -2.0, -2.0], index=idx),
    }


def _stat_spec(*, rebalance_threshold=None, freeze_on_entry=True):
    return StatArbPairSpec(
        arb_id="STAT_PAIR_001",
        legs=(
            ArbitrageLeg(symbol=BASE, ratio=1.0, asset_class="crypto"),
            ArbitrageLeg(symbol=HEDGE, ratio=-0.5, asset_class="crypto"),
        ),
        hedge_policy=HedgePolicy(
            kind=HedgePolicyKind.BETA_NEUTRAL,
            freeze_on_entry=freeze_on_entry,
            rebalance_threshold=rebalance_threshold,
        ),
        sizing_policy=SizingPolicy(
            kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL,
            notional=600.0,
        ),
    )


def _backend():
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=False,
        )
    )


def test_phase_d_stat_arb_freezes_beta_and_reports_beta_drift():
    idx = _idx()
    result = _backend().run_stat_arb_pair_arbitrage(
        datetime_index=idx,
        spec=_stat_spec(),
        signal=_signal(idx),
        closes=_closes(idx),
        hedge_ratios=_hedge_ratios(idx),
    )

    target_units = result.metadata["package_target_units"]
    assert target_units.loc[idx[1], BASE] == 10.0
    assert target_units.loc[idx[1], HEDGE] == -5.0
    assert target_units.loc[idx[2], BASE] == 10.0
    assert target_units.loc[idx[2], HEDGE] == -5.0
    assert target_units.loc[idx[3], BASE] == 0.0
    assert target_units.loc[idx[3], HEDGE] == 0.0
    assert len(result.fills) == 4

    beta_drift = result.metadata["beta_drift_report"]
    hedge_drift = beta_drift[(beta_drift["timestamp"] == idx[2]) & (beta_drift["symbol"] == HEDGE)].iloc[0]
    assert hedge_drift["frozen_ratio_to_ref"] == -0.5
    assert hedge_drift["current_ratio_to_ref"] == -2.0
    assert hedge_drift["rel_beta_drift"] == 3.0
    assert bool(hedge_drift["breached"]) is False


def test_phase_d_stat_arb_rebalances_only_when_beta_drift_exceeds_threshold():
    idx = _idx()
    result = _backend().run_stat_arb_pair_arbitrage(
        datetime_index=idx,
        spec=_stat_spec(rebalance_threshold=1.0),
        signal=_signal(idx),
        closes=_closes(idx),
        hedge_ratios=_hedge_ratios(idx),
    )

    target_units = result.metadata["package_target_units"]
    assert target_units.loc[idx[1], BASE] == 10.0
    assert target_units.loc[idx[1], HEDGE] == -5.0
    assert target_units.loc[idx[2], BASE] == pytest.approx(600.0 / 260.0)
    assert target_units.loc[idx[2], HEDGE] == pytest.approx(-2.0 * 600.0 / 260.0)
    assert target_units.loc[idx[3], BASE] == 0.0
    assert target_units.loc[idx[3], HEDGE] == 0.0
    assert len(result.fills) == 6

    order_report = result.metadata["order_report"]
    assert (order_report["fill_bar"] == 2).sum() == 2
    beta_drift = result.metadata["beta_drift_report"]
    hedge_drift = beta_drift[(beta_drift["timestamp"] == idx[2]) & (beta_drift["symbol"] == HEDGE)].iloc[0]
    assert hedge_drift["rel_beta_drift"] == pytest.approx(0.0)


def test_phase_d_stat_arb_endpoint_runs_via_arbitrage_facade():
    idx = _idx()
    endpoint = QuantBTEndpoint.arbitrage(
        arb_type="stat_arb_pair",
        spec=_stat_spec(),
        initial_capital=10_000.0,
        leverage=10.0,
        use_funding=False,
    )

    result = endpoint.simulate(data=_frames(idx), signal=_signal(idx), hedge_ratios=_hedge_ratios(idx))

    assert result.metadata["engine"] == "event_v1_stat_arb_pair"
    assert result.metadata["arb_type"] == "stat_arb_pair"
    assert "beta_drift_report" in result.metadata
    assert endpoint.fills_report.shape[0] == 4
