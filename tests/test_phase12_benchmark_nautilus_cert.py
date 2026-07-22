from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import AccountConfig
from quantbt.backends import NativePortfolioBackend, NativePortfolioConfig
from quantbt.benchmarks.run_phase12_benchmark_nautilus_cert import make_markdown, run_certification


def test_phase12_benchmark_nautilus_certification_smoke():
    report = run_certification(rows=180, symbols=3, repeats=1, include_nautilus=False)

    assert report["status"] == "pass"
    assert report["benchmark_followup"]["status"] == "pass"
    assert report["benchmark_followup"]["stages"]["full_facade_seconds"] > 0.0
    assert report["benchmark_followup"]["stages"]["prepared_reuse_facade_seconds"] > 0.0
    assert report["benchmark_followup"]["stages"]["pure_numba_kernel_seconds"] > 0.0
    assert report["all_or_none_basket"]["status"] == "pass"
    assert report["all_or_none_basket"]["accepted_orders"] == 0
    assert report["all_or_none_basket"]["rejected_orders"] == 2
    assert report["nautilus_portfolio"]["status"] == "skipped"

    markdown = make_markdown(report)
    assert "Phase 12B Benchmark And Nautilus Portfolio Certification" in markdown
    assert "Cython/C++ Decision" in markdown


def test_phase12_native_portfolio_prepared_reuse_matches_normal_run():
    idx, positions, closes = _portfolio_fixture()
    backend = NativePortfolioBackend(
        NativePortfolioConfig(
            account=AccountConfig(initial_capital=100_000.0, leverage=4.0, maintenance_ratio=0.005),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    symbols = list(positions)

    normal = backend.run_signals(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        symbols=symbols,
        mode="market_neutral",
        hedge_type="notional",
        alloc_per_trade={"BTC": 1_000.0, "ETH": 1_500.0},
        use_pyramiding=True,
        funding_rate=0.0,
    )

    market = backend.prepare_market_arrays(idx, closes=closes, highs=closes, lows=closes, funding_rate=0.0, symbols=symbols)
    signals = backend.prepare_signal_matrix(positions, idx, symbols)
    reused = backend.run_signals(
        positions=None,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        symbols=symbols,
        mode="market_neutral",
        hedge_type="notional",
        alloc_per_trade={"BTC": 1_000.0, "ETH": 1_500.0},
        use_pyramiding=True,
        funding_rate=0.0,
        market_arrays=market,
        raw_signal_matrix=signals,
    )

    np.testing.assert_allclose(reused.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(reused.positions.to_numpy(), normal.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        reused.metadata["symbol_pnl_report"]["total_pnl"].to_numpy(),
        normal.metadata["symbol_pnl_report"]["total_pnl"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    for key in (
        "target_units_report",
        "accepted_units_report",
        "target_notional_report",
        "accepted_notional_report",
        "exposure_report",
    ):
        np.testing.assert_allclose(
            reused.metadata[key].to_numpy(dtype=float),
            normal.metadata[key].to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-10,
        )
    np.testing.assert_allclose(reused.funding.to_numpy(), normal.funding.to_numpy(), rtol=0.0, atol=1e-12)
    assert reused.metadata["rebalance_report"].reset_index(drop=True).equals(
        normal.metadata["rebalance_report"].reset_index(drop=True)
    )


def test_phase12_native_portfolio_prepared_reuse_rejects_stale_signature():
    idx, positions, closes = _portfolio_fixture()
    backend = NativePortfolioBackend(
        NativePortfolioConfig(account=AccountConfig(initial_capital=100_000.0, leverage=4.0), use_funding=False)
    )
    symbols = list(positions)
    market = backend.prepare_market_arrays(idx, closes=closes, highs=closes, lows=closes, symbols=symbols)
    signals = backend.prepare_signal_matrix(positions, idx, symbols)

    with pytest.raises(ValueError, match="prepared market arrays"):
        backend.run_signals(
            positions=None,
            closes=closes,
            datetime_index=idx[:-1],
            symbols=symbols,
            market_arrays=market,
            raw_signal_matrix=signals[:-1],
        )


def _portfolio_fixture():
    idx = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0, 0.0], index=idx),
        "ETH": pd.Series([0.0, -1.0, -1.0, 0.0, 1.0, 1.0, 0.0, 0.0], index=idx),
    }
    closes = {
        "BTC": pd.Series([100.0, 101.0, 102.0, 101.5, 100.5, 99.0, 100.0, 101.0], index=idx),
        "ETH": pd.Series([50.0, 49.5, 49.0, 50.0, 51.0, 52.0, 51.0, 50.5], index=idx),
    }
    return idx, positions, closes
