from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import AccountConfig
from quantbt.backends import NativePortfolioBackend, NativePortfolioConfig


def test_phase13_native_portfolio_report_optimization_matches_legacy_report_formulas():
    idx = pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC")
    symbols = ["BTC", "ETH", "SOL"]
    closes = {
        "BTC": pd.Series([100, 101, 103, 102, 104, 105, 103, 102, 101, 100, 102, 103], index=idx, dtype=float),
        "ETH": pd.Series([50, 49, 48, 50, 51, 52, 53, 52, 51, 50, 49, 50], index=idx, dtype=float),
        "SOL": pd.Series([20, 21, 20, 19, 20, 21, 22, 23, 22, 21, 20, 19], index=idx, dtype=float),
    }
    positions = {
        "BTC": pd.Series([0, 1, 1, 0, -1, -1, 0, 1, 1, 0, 0, 0], index=idx, dtype=float),
        "ETH": pd.Series([0, -1, -1, 0, 1, 1, 0, -1, -1, 0, 0, 0], index=idx, dtype=float),
        "SOL": pd.Series([0, 1, 0, 0, 1, 0, 0, -1, 0, 0, 1, 0], index=idx, dtype=float),
    }
    funding_rate = {
        "BTC": pd.Series([0.0, 0.0, 0.0001, 0.0, 0.0, 0.0001, 0.0, 0.0, 0.0001, 0.0, 0.0, 0.0001], index=idx),
        "ETH": pd.Series([0.0, 0.0, -0.00005, 0.0, 0.0, -0.00005, 0.0, 0.0, -0.00005, 0.0, 0.0, -0.00005], index=idx),
        "SOL": pd.Series(0.0, index=idx),
    }
    backend = NativePortfolioBackend(
        NativePortfolioConfig(
            account=AccountConfig(initial_capital=100_000.0, leverage=4.0, maintenance_ratio=0.005),
            fee_rate=0.0002,
            use_funding=True,
        )
    )
    result = backend.run_signals(
        positions=positions,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=idx,
        symbols=symbols,
        mode="market_neutral",
        hedge_type="notional",
        alloc_per_trade={"BTC": 1_000.0, "ETH": 1_500.0, "SOL": 500.0},
        funding_rate=funding_rate,
        contract_size={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0},
        use_pyramiding=True,
    )

    old = _legacy_report_formula_snapshot(result, symbols)

    np.testing.assert_allclose(result.returns.to_numpy(), old["returns"].to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(result.funding.to_numpy(), old["funding"].to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_array_equal(
        result.diagnostics["rejected_rebalances"].to_numpy(dtype=bool),
        old["rejected_rebalances"].to_numpy(dtype=bool),
    )
    np.testing.assert_allclose(
        result.metadata["exposure_report"].to_numpy(dtype=float),
        old["exposure_report"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-10,
    )
    pd.testing.assert_frame_equal(
        result.metadata["rebalance_report"].reset_index(drop=True),
        old["rebalance_report"].reset_index(drop=True),
        check_dtype=False,
    )


def _legacy_report_formula_snapshot(result, symbols):
    idx = result.equity.index
    target_units = result.metadata["target_units_report"]
    accepted_units = result.metadata["accepted_units_report"]
    closes = result.metadata["accepted_notional_report"] / accepted_units.replace(0.0, np.nan)
    closes = closes.fillna(result.metadata["target_notional_report"] / target_units.replace(0.0, np.nan)).fillna(0.0)
    contract_sizes = pd.Series(result.metadata["contract_size"], dtype=float).reindex(symbols)
    target_notional = result.metadata["target_notional_report"]
    accepted_notional = result.metadata["accepted_notional_report"]
    leverages = pd.Series(result.metadata["initial_buying_power"] / result.initial_capital, index=symbols, dtype=float)
    betas = pd.Series(result.metadata["beta"], dtype=float).reindex(symbols)

    returns = result.equity.pct_change().fillna(0.0)
    funding = result.metadata["symbol_pnl_report"].groupby("timestamp", sort=False)["funding_cost"].sum().reindex(idx, fill_value=0.0)
    rejected_rebalances = (target_units - accepted_units).abs().sum(axis=1) > 1e-10

    abs_accepted = accepted_notional.abs()
    gross = abs_accepted.sum(axis=1)
    net = accepted_notional.sum(axis=1)
    initial_margin = abs_accepted.div(leverages, axis=1).sum(axis=1)
    maintenance_margin = gross * float(result.margin["maintenance_margin"].div(gross.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna().iloc[0])
    beta_exposure = accepted_notional.mul(betas, axis=1).sum(axis=1)
    target_gross = target_notional.abs().sum(axis=1)
    target_beta_exposure = target_notional.mul(betas, axis=1).sum(axis=1)
    exposure_report = pd.DataFrame(
        {
            "long_notional": accepted_notional.where(accepted_notional > 0.0, 0.0).sum(axis=1),
            "short_notional": (-accepted_notional.where(accepted_notional < 0.0, 0.0)).sum(axis=1),
            "gross_notional": gross,
            "net_notional": net,
            "beta_exposure_notional": beta_exposure,
            "target_gross_notional": target_gross,
            "target_beta_exposure_notional": target_beta_exposure,
            "initial_margin": initial_margin,
            "maintenance_margin": maintenance_margin,
            "equity": result.equity,
            "available_equity_after_im": result.equity - initial_margin,
            "buying_power": result.equity * float(leverages.mean()),
        },
        index=idx,
    )
    exposure_report["gross_leverage"] = exposure_report["gross_notional"] / exposure_report["equity"].replace(0.0, np.nan)
    exposure_report["net_exposure_pct"] = exposure_report["net_notional"] / exposure_report["equity"].replace(0.0, np.nan)
    exposure_report = exposure_report.fillna(0.0)

    diff = target_units - accepted_units
    mask = diff.abs() > 1e-10
    if not mask.to_numpy().any():
        rebalance_report = pd.DataFrame(
            columns=["timestamp", "symbol", "target_units", "accepted_units", "unit_diff", "notional_diff", "reason"]
        )
    else:
        notional_diff = diff.mul(closes, axis=0).mul(contract_sizes, axis=1)
        stacked = diff.where(mask).stack(future_stack=True).dropna()
        index = stacked.index
        rebalance_report = pd.DataFrame(
            {
                "timestamp": index.get_level_values(0),
                "symbol": index.get_level_values(1),
                "target_units": target_units.stack(future_stack=True).reindex(index).to_numpy(dtype=float),
                "accepted_units": accepted_units.stack(future_stack=True).reindex(index).to_numpy(dtype=float),
                "unit_diff": stacked.to_numpy(dtype=float),
                "notional_diff": notional_diff.stack(future_stack=True).reindex(index).to_numpy(dtype=float),
                "reason": "margin_or_portfolio_gate",
            }
        )

    return {
        "returns": returns,
        "funding": funding,
        "rejected_rebalances": rejected_rebalances,
        "exposure_report": exposure_report,
        "rebalance_report": rebalance_report,
    }
