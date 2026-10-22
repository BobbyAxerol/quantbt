from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from quantbt.metrics.performance import compute_performance_metrics
from tests.native_event.contract.scalar_report_assertions import SCORE_REPORT_KEYS, assert_scalar_report_parity


def sample():
    index = pd.date_range("2025-01-01", periods=3, freq="D", tz="UTC")
    equity = pd.Series([100., 110., 99.], index=index)
    returns = equity.pct_change().fillna(0.)
    report = compute_performance_metrics(timestamps=index, equity=equity, returns=returns,
        positions=[[0.], [1.], [1.]], symbols=["X"], initial_capital=100.)
    audit = SimpleNamespace(equity=equity, returns=returns, full_report=lambda: report)
    return {key: report[key] for key in SCORE_REPORT_KEYS}, audit, report


def test_legacy_score_parity_and_additive_report_fields_are_both_checked():
    metrics, audit, _ = sample()
    assert_scalar_report_parity(metrics, audit, atol=1e-12)


@pytest.mark.parametrize("change", ("score", "missing_score", "unknown_report", "period_mean",
                                     "position_alias", "population", "sample_count"))
def test_separation_does_not_hide_metric_or_metadata_drift(change):
    metrics, audit, original = sample()
    report = deepcopy(original)
    audit.full_report = lambda: report
    if change == "score":
        metrics["sharpe"] += 1.
    elif change == "missing_score":
        metrics.pop("sortino")
    elif change == "unknown_report":
        report["unreviewed_field"] = 1.
    elif change == "period_mean":
        report["period_expected_return_pct"] += 1.
    elif change == "position_alias":
        report["position_state_count"] += 1
    elif change == "population":
        report["metric_population"]["sharpe"]["population"] = "closed_trade"
    else:
        report["metric_population"]["sharpe"]["sample_count"] += 1
    with pytest.raises(AssertionError):
        assert_scalar_report_parity(metrics, audit, atol=1e-12)
