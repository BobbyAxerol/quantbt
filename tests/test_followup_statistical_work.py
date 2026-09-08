"""Independent draw-stream and report-extraction contracts."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization import bootstrap
from quantbt.optimization.objectives import (
    MissingOptimizationMetricError,
    ReportMetricObjective,
    metric_from_result,
    metrics_from_result,
    min_trades_constraint,
)
from quantbt.walkforward import stationary_bootstrap_sharpes


def reference_indices(n, samples, block, seed):
    rng = np.random.default_rng(seed)
    indices = np.empty((samples, n), dtype=np.int64)
    for sample in range(samples):
        current = int(rng.integers(0, n))
        indices[sample, 0] = current
        for bar in range(1, n):
            if rng.random() < 1.0 / max(1.0, float(block)):
                current = int(rng.integers(0, n))
            else:
                current = (current + 1) % n
            indices[sample, bar] = current
    return indices


@pytest.mark.parametrize("n,samples", [(1, 0), (1, 5), (2, 7), (17, 4), (1000, 5)])
@pytest.mark.parametrize("block", [-1, 1, 4, 10000])
@pytest.mark.parametrize("seed", [0, 42, 2**32 + 5])
def test_draw_stream_exact(n, samples, block, seed):
    expected = reference_indices(n, samples, block, seed)
    for accelerated in (False, True):
        actual = bootstrap.stationary_indices(n, samples, block, seed, use_numba=accelerated)
        np.testing.assert_array_equal(actual, expected)


def test_rng_continuation_and_global_isolation():
    pytest.importorskip("numba")
    before = np.random.get_state()
    py_rng, compiled_rng = np.random.default_rng(42), np.random.default_rng(42)
    np.testing.assert_array_equal(
        bootstrap._stationary_indices(py_rng, 117, 4, 5),
        bootstrap._compiled_stationary_indices(compiled_rng, 117, 4, 5),
    )
    assert py_rng.bit_generator.state == compiled_rng.bit_generator.state
    after = np.random.get_state()
    assert before[0] == after[0] and before[2:] == after[2:]
    np.testing.assert_array_equal(before[1], after[1])


def test_optional_fallback_and_invalid_input(monkeypatch):
    monkeypatch.setattr(bootstrap, "_compiled_stationary_indices", None)
    np.testing.assert_array_equal(
        bootstrap.stationary_indices(11, 3, 5, 0, use_numba=True), reference_indices(11, 3, 5, 0)
    )
    for enabled in (False, True):
        with pytest.raises(ValueError, match="n_obs must be > 0"):
            bootstrap.stationary_indices(0, 1, 2, 0, use_numba=enabled)


@pytest.mark.parametrize("values", [[], [0.0], [0.0] * 15, [np.nan, .03, -.02, np.inf, .01, -.03] * 10])
def test_public_sharpes_preserve_reference(values):
    expected = stationary_bootstrap_sharpes(values, 20, 4, 42, use_numba=False)
    actual = stationary_bootstrap_sharpes(values, 20, 4, 42, use_numba=True)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def test_compiled_index_change_preserves_compiled_scores_bitwise(monkeypatch):
    import quantbt.walkforward as wf

    values = np.random.default_rng(12).normal(0.001, .01, 2000)
    actual = wf.stationary_bootstrap_sharpes(values, 31, 17, 123, use_numba=True)
    monkeypatch.setattr(
        wf, "_stationary_bootstrap_indices",
        lambda n_obs, n_samples, block_length, seed, **kwargs: reference_indices(n_obs, n_samples, block_length, seed),
    )
    expected = wf.stationary_bootstrap_sharpes(values, 31, 17, 123, use_numba=True)
    np.testing.assert_array_equal(actual, expected)


class CountingReport:
    def __init__(self):
        self.calls = []
        self.sharpe = 1.5
        self.metadata = {"turnover": 4.0, "rejected_count": 1, "fill_count": 3}
        self.equity = pd.Series([100., 110.])
        self.margin = pd.DataFrame({"initial_margin": [10., 22.]})

    def full_report(self, *, trading_days, scope):
        self.calls.append((trading_days, scope))
        return {"sharpe": self.sharpe, "num_trades": 3., "max_drawdown_pct": 2., "profit_factor": 1.3}


def test_objective_one_report_preserves_constraints_and_metadata():
    result = CountingReport()
    objective = ReportMetricObjective(
        value_metrics=("sharpe", "trades", "margin_util", "rejections"),
        trading_days=252, scope="full", constraints=(min_trades_constraint(4),),
        metadata_builder=lambda result, params, metrics: {"params": dict(params), "metrics": dict(metrics)},
    )
    actual = objective(result, {"a": 1})
    assert actual.values == (1.5, 3., .2, .25)
    assert actual.constraints == (1.,)
    assert actual.metrics["turnover"] == 4.
    assert actual.metadata["metrics"] == actual.metrics
    assert result.calls == [(252, "full")]
    result.sharpe = 2.0
    assert objective(result, {}).values[0] == 2.0
    assert result.calls == [(252, "full")] * 2  # No cache across evaluations.


def test_optional_metrics_and_required_values_remain_distinct():
    result = CountingReport()
    assert metrics_from_result(result, names=("not_present", "trades")) == {"num_trades": 3.}
    assert len(result.calls) == 1
    with pytest.raises(MissingOptimizationMetricError, match="not_present"):
        ReportMetricObjective(value_metrics=("not_present",))(result, {})
    assert len(result.calls) == 2
    assert metric_from_result(result, "not_present", required=False, default=-7.) == -7.
    assert metrics_from_result(SimpleNamespace(metadata={"report": {"sharpe": 2}}), names=("sharpe",)) == {"sharpe": 2.}


def test_value_metrics_do_not_expand_display_or_constraint_surface():
    observed = []
    result = CountingReport()
    objective = ReportMetricObjective(
        value_metrics=("sharpe",), metric_names=(),
        constraints=(lambda metrics, params, result: observed.append(dict(metrics)) or 0.,),
    )
    actual = objective(result, {})
    assert actual.values == (1.5,) and actual.metrics == {} and observed == [{}]
    assert len(result.calls) == 1
