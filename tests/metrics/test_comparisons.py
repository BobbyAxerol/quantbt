import hashlib
from importlib import metadata
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt.metrics import performance as legacy

from .reference_oracle import DAY_NS, account_growth, drawdown_episodes, period_statistics, utc_ns


ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT / "docs/metrics/evidence/met01/baseline.json").read_text())


@pytest.fixture(scope="module")
def qs():
    package = pytest.importorskip("quantstats")
    assert metadata.version("quantstats") == BASELINE["quantstats"]["version"] == "0.0.81"
    root = Path(package.__file__).parent
    for source, expected in BASELINE["quantstats"]["sources"].items():
        assert hashlib.sha256((root / source).read_bytes()).hexdigest() == expected
    return package.stats


def test_t06_matched_prepared_return_conventions(qs):
    returns = pd.Series([.01, .02, -.01, 0.], index=pd.date_range("2025-01-01", periods=4, tz="UTC"))
    oracle = period_statistics(returns, annual_periods=365.)
    assert qs.profit_factor(returns, prepare_returns=False) == pytest.approx(oracle["profit_factor"])
    assert qs.avg_win(returns, prepare_returns=False) == pytest.approx(oracle["avg_win"])
    assert qs.avg_loss(returns, prepare_returns=False) == pytest.approx(oracle["avg_loss"])
    assert qs.sharpe(returns, rf=0, periods=365, annualize=True) == pytest.approx(oracle["sharpe"])
    assert qs.sortino(returns, rf=0, periods=365, annualize=True) == pytest.approx(oracle["sortino"])
    assert qs.cagr(returns, periods=365, rf=0) == pytest.approx(oracle["cagr_period_count"])
    assert qs.expected_return(returns, prepare_returns=False) == pytest.approx(oracle["mean_geometric"])
    assert qs.win_rate(returns, prepare_returns=False) == pytest.approx(oracle["nonzero_win_rate"])
    assert qs.win_rate(returns, prepare_returns=False) != oracle["win_rate"]
    assert legacy._array_profit_factor(returns.to_numpy()) == oracle["profit_factor"]
    assert legacy._array_sortino(returns.to_numpy(), 365) == pytest.approx(oracle["sortino"] / 2)


@pytest.mark.parametrize("dates,legacy_count,inclusive_days,elapsed_days", [
    (["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"], 2, 2, 3),
    (["2025-01-01", "2025-01-04", "2025-01-07", "2025-01-08"], 2, 4, 7),
])
def test_t06_observed_count_calendar_inclusive_and_elapsed_are_different(qs, dates, legacy_count, inclusive_days, elapsed_days):
    idx = pd.to_datetime(dates, utc=True)
    values = np.array([100., 90., 95., 100.])
    oracle = drawdown_episodes(list(map(int, idx.asi8)), list(values), 100., int(idx[0].value))
    # Supply explicit DD, avoiding QuantStats price/currency heuristics.
    details = qs.drawdown_details(pd.Series([0., -.1, -.05, 0.], index=idx))
    assert details.iloc[0]["days"] == inclusive_days
    assert legacy._array_drawdown_duration_days(idx, values)[0] == legacy_count
    assert oracle["episodes"][0]["elapsed_ns"] == elapsed_days * DAY_NS
    assert oracle["episodes"][0]["inclusive_underwater_calendar_days"] == inclusive_days


def test_t06_intraday_duration_and_first_loss_edge(qs):
    idx = pd.date_range("2025-01-01 10:00", periods=3, freq="h", tz="UTC")
    oracle = drawdown_episodes(list(map(int, idx.asi8)), [100, 90, 100], 100, int(idx[0].value))
    assert oracle["episodes"][0]["elapsed_ns"] == 7_200_000_000_000
    assert legacy._array_drawdown_duration_days(idx, np.array([100., 90., 100.]))[0] == 0
    assert qs.drawdown_details(pd.Series([0., -.1, 0.], index=idx)).iloc[0]["days"] == 1
    first_loss = pd.Series([-.1, -.1], index=idx[:2])
    assert qs.drawdown_details(first_loss).empty
    assert drawdown_episodes(list(map(int, idx[:2].asi8)), [90, 90], 100, int(idx[0].value))["episodes"]


def test_t06_currency_heuristic_not_a_financial_oracle(qs):
    idx = pd.date_range("2025-01-01", periods=2, tz="UTC")
    raw = pd.Series([20_000., 20_000.], index=idx)
    assert qs.max_drawdown(raw) == pytest.approx(-.8)
    assert drawdown_episodes(list(map(int, idx.asi8)), list(raw), 20_000., int(idx[0].value))["max_depth"] == 0
    assert qs.max_drawdown(pd.Series([0., 0.], index=idx)) == 0


def test_t06_zero_denominators_and_cagr_calendar_disagreements(qs):
    flat = pd.Series([0., 0.], index=pd.date_range("2025-01-01", periods=2, tz="UTC"))
    assert math.isnan(qs.sortino(flat))
    assert qs.profit_factor(flat, prepare_returns=False) == 0.
    assert math.isinf(legacy._array_profit_factor(flat.to_numpy()))
    assert period_statistics(flat)["profit_factor"] is None
    dates = [utc_ns("2025-01-01T00:00:00Z"), utc_ns("2026-01-01T06:00:00Z")]
    account = account_growth(dates, [100, 110], 100, dates[0])
    assert account["cagr_elapsed"] == pytest.approx(.1)
    periods = pd.Series([0., .1], index=pd.to_datetime(dates, utc=True))
    assert qs.cagr(periods, periods=365) != pytest.approx(account["cagr_elapsed"])


def test_t06_legacy_first_fee_flat_count_and_expectancy_are_locked():
    idx = pd.date_range("2025-01-01", periods=2, tz="UTC")
    report = legacy.compute_performance_metrics(timestamps=idx, equity=[90, 90], returns=[-.1, 0],
                                                positions=[[0, 0], [0, 0]], symbols=["BTC", "ETH"], initial_capital=100)
    assert report["total_return_pct"] == -10.
    assert report["cagr_pct"] == report["max_drawdown_pct"] == 0.
    assert report["num_trades"] == 2
    idx = pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC")
    report = legacy.compute_performance_metrics(timestamps=idx, equity=[20_000, 20_200, 20_099, 20_099],
                                                returns=[0, .01, -.005, 0], positions=[0, 1, 1, 0], symbols=["BTC"], initial_capital=20_000)
    assert report["num_trades"] == 3
    assert report["expectancy_pct"] == -.125
    assert period_statistics([0, .01, -.005, 0])["mean_arithmetic"] == .00125
