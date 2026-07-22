from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    ArbitrageLeg,
    CrossExchangeArbSpec,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
    build_arbitrage_domain_audit,
    compare_native_arbitrage_results,
)
from quantbt.core.schema import AccountConfig


def _idx():
    return pd.date_range("2024-01-01", periods=6, freq="8h", tz="UTC")


def _event():
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0002,
            use_funding=True,
        )
    )


def _vectorized():
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0002,
            use_funding=True,
        )
    )


def _stat_spec():
    return StatArbPairSpec(
        arb_id="PHASE13C_STAT_ARB",
        legs=(
            ArbitrageLeg("ETH-PERP", 1.0, asset_class="crypto", funding_enabled=True),
            ArbitrageLeg("SOL-PERP", -1.0, asset_class="crypto"),
        ),
        hedge_policy=HedgePolicy(
            HedgePolicyKind.BETA_NEUTRAL,
            freeze_on_entry=False,
            rebalance_threshold=0.15,
        ),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=10_000.0),
    )


def test_phase13c_stat_arb_package_pnl_report_reconciles_event_and_vectorized():
    idx = _idx()
    closes = {
        "ETH-PERP": pd.Series([100.0, 100.0, 102.0, 104.0, 103.0, 101.0], index=idx),
        "SOL-PERP": pd.Series([50.0, 50.0, 49.0, 48.0, 50.0, 51.0], index=idx),
    }
    signal = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0, 0.0], index=idx)
    hedge_ratios = {
        "ETH-PERP": pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 1.0], index=idx),
        "SOL-PERP": pd.Series([-1.0, -1.0, -1.35, -1.35, -0.8, -0.8], index=idx),
    }
    funding = {
        "ETH-PERP": pd.Series([0.0, 0.0, 0.001, 0.0, -0.0005, 0.0], index=idx),
        "SOL-PERP": pd.Series([0.01, 0.01, 0.01, 0.01, 0.01, 0.01], index=idx),
    }
    spec = _stat_spec()

    event = _event().run_stat_arb_pair_arbitrage(
        idx,
        spec,
        signal,
        closes,
        hedge_ratios=hedge_ratios,
        funding_rate=funding,
    )
    vectorized = _vectorized().run_stat_arb_pair_arbitrage(
        idx,
        spec,
        signal,
        closes,
        hedge_ratios=hedge_ratios,
        funding_rate=funding,
    )

    for result in (event, vectorized):
        audit = build_arbitrage_domain_audit(result, raise_on_fail=True)
        package = result.metadata["package_pnl_report"]
        leg_report = result.metadata["leg_pnl_report"]

        assert audit["status"] == "pass"
        assert set(
            [
                "price_pnl",
                "fill_pnl",
                "fees",
                "funding_pnl",
                "leg_pnl",
                "hedge_pnl",
                "spread_pnl",
                "package_pnl",
                "equity_delta",
                "pnl_residual",
            ]
        ).issubset(package.columns)
        np.testing.assert_allclose(
            package["package_pnl"].to_numpy(dtype=float),
            (
                package["price_pnl"]
                + package["fill_pnl"]
                - package["fees"]
                + package["funding_pnl"]
            ).to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-10,
        )
        np.testing.assert_allclose(package["pnl_residual"].to_numpy(dtype=float), 0.0, rtol=0.0, atol=1e-10)
        np.testing.assert_allclose(
            package["spread_pnl"].to_numpy(dtype=float),
            (package["leg_pnl"] + package["hedge_pnl"]).to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-12,
        )
        assert leg_report.groupby("symbol")["funding_pnl"].sum().loc["SOL-PERP"] == pytest.approx(0.0)
        assert abs(float(leg_report.groupby("symbol")["funding_pnl"].sum().loc["ETH-PERP"])) > 0.0

    parity = compare_native_arbitrage_results(event, vectorized, raise_on_fail=True)
    assert parity["status"] == "pass"
    pd.testing.assert_frame_equal(
        event.metadata["package_pnl_report"],
        vectorized.metadata["package_pnl_report"],
        check_dtype=False,
        check_exact=False,
        rtol=0.0,
        atol=1e-10,
    )


def test_phase13c_schema_only_arbitrage_specs_reject_with_actionable_message():
    idx = _idx()
    closes = {
        "BTC-BINANCE": pd.Series(100.0, index=idx),
        "BTC-OKX": pd.Series(101.0, index=idx),
    }
    spec = CrossExchangeArbSpec(
        arb_id="SCHEMA_ONLY_CROSS_EXCHANGE",
        legs=(
            ArbitrageLeg("BTC-BINANCE", 1.0, venue="BINANCE"),
            ArbitrageLeg("BTC-OKX", -1.0, venue="OKX"),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=10_000.0,
            reference_symbol="BTC-BINANCE",
        ),
    )

    with pytest.raises(NotImplementedError, match="schema-validated.*specialized arbitrage engine"):
        _event().run_package_arbitrage(idx, spec, pd.Series(1.0, index=idx), closes)
    with pytest.raises(NotImplementedError, match="arbitrage_support_matrix"):
        _vectorized().run_package_arbitrage(idx, spec, pd.Series(1.0, index=idx), closes)
