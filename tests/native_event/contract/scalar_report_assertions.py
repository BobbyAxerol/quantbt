"""Keep the streaming score-v1 contract distinct from additive cold reports."""

import math

import numpy as np

SCORE_REPORT_KEYS = frozenset((
    "initial_capital", "final_equity", "total_return_pct", "cagr_pct", "sharpe",
    "sortino", "calmar", "omega", "max_drawdown_pct", "avg_drawdown_pct",
    "max_dd_duration_days", "avg_dd_duration_days", "profit_factor",
    "long_hitrate_pct", "short_hitrate_pct", "avg_win_pct", "avg_loss_pct",
    "expectancy_pct", "num_trades", "liquidated",
))
COLD_REPORT_KEYS = frozenset(("period_expected_return_pct", "position_state_count", "metric_population"))


def assert_scalar_report_parity(metrics, audit, *, atol):
    report = audit.full_report()
    assert set(report) == SCORE_REPORT_KEYS | COLD_REPORT_KEYS
    assert SCORE_REPORT_KEYS <= metrics.keys()
    for key in SCORE_REPORT_KEYS:
        expected, actual = report[key], metrics[key]
        if isinstance(expected, (float, int, np.floating, np.integer)) and not isinstance(expected, bool):
            if math.isinf(float(expected)):
                assert math.isinf(float(actual)) and (float(actual) > 0.0) == (float(expected) > 0.0)
            else:
                np.testing.assert_allclose(actual, expected, rtol=0.0, atol=atol)
        else:
            assert actual == expected
    # These are post-execution report fields, not retained streaming-score paths.
    assert report["position_state_count"] == metrics["num_trades"]
    daily = audit.equity.resample("1D").last().dropna().to_numpy(dtype=np.float64)
    if len(daily) >= 2:
        base = daily[:-1]
        values = np.divide(daily[1:] - base, base, out=np.zeros(len(base)), where=base != 0.0)
        population = "observed_daily_equity_returns"
    else:
        values = audit.returns.to_numpy(dtype=np.float64)
        population = "finite_bar_returns"
    values = values[np.isfinite(values)]
    np.testing.assert_allclose(report["period_expected_return_pct"], np.mean(values) * 100.0,
                               rtol=0.0, atol=atol)
    for key in ("sharpe", "sortino", "omega", "profit_factor", "period_expected_return_pct"):
        assert report["metric_population"][key]["population"] == population
        assert report["metric_population"][key]["sample_count"] == len(values)
