from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np
import pytest

from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations, ReturnObservations, reduce_account

from .reference_oracle import DAY_NS, account_growth, drawdown_episodes, period_statistics, utc_ns


FIXTURES = json.loads((Path(__file__).parent / "fixtures/manual.json").read_text())


def policy(times, baseline=100., **kwargs):
    return ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=baseline, baseline_time_ns=int(times[0]), scope_end_ns=int(times[-1]),
        sampling="explicit_period_returns", annual_periods=1., equity_clock="bar_close", **kwargs)


def coverage():
    return ReportingCoverageV1(result_identity="public-fixture", producer="recorded-test",
        profile="compact", ledger="omitted", retained_rows=0, dropped_rows=0,
        reason="account paths do not certify a fill ledger")


def observations(times, marks, returns=None, mask=None):
    r = None if returns is None else ReturnObservations(values=returns,
        end_times_ns=times[:len(returns)], partial_mask=[False] * len(returns) if mask is None else mask,
        sampling="explicit_period_returns", witness="explicit test period population")
    return AccountObservations(times_ns=times, equity=marks, coverage=coverage(), returns=r)


def assert_value(metric, value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        assert metric.value is None and metric.status != "valid"
    elif math.isinf(value):
        assert metric.status == "no_loss" and metric.value is None
    else:
        assert metric.status == "valid"
        assert metric.value == pytest.approx(value, rel=1e-11, abs=1e-12)


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("case", FIXTURES["drawdowns"], ids=lambda c: c["id"])
def test_met02_t01_t03_manual_drawdown_matches_independent_oracle(case, backend):
    times = [utc_ns(t) for t in case["times"]]
    obs = observations(times, case["equity"])
    contract = policy(times, case["baseline"])
    actual = reduce_account(obs, contract, backend=backend, retain_episodes=True)
    expected = drawdown_episodes(times, case["equity"], case["baseline"], times[0])
    assert actual.episodes.to_rows() == expected["episodes"]
    for name in ("max_depth", "mean_underwater_depth", "mean_episode_depth",
                 "mean_recovered_duration_ns", "longest_recovered_duration_ns",
                 "current_open_duration_ns", "ulcer_index"):
        assert_value(actual.metric("drawdown." + name), expected[name])
    growth = account_growth(times, case["equity"], case["baseline"], times[0])
    assert_value(actual.metric("account.total_return"), growth["total_return"])
    assert_value(actual.metric("account.cagr_elapsed"), growth["cagr_elapsed"])


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("sample", [[.01, .02, -.01, 0], [0, 0], [.1, .1], [-.1, -.1],
                                  [-1, 0], [.1], [.01, -.01]])
@pytest.mark.parametrize("conditional", [False, True])
def test_met02_t01_t02_period_oracle(sample, backend, conditional):
    times = list(range(len(sample)))
    contract = policy(times, mar_per_period=.005, risk_free_per_period=.003,
                      omega_threshold_per_period=.002,
                      sortino_denominator="negative_observations" if conditional else "all_observations")
    actual = reduce_account(observations(times, [100.] * len(sample), sample), contract, backend=backend)
    expected = period_statistics(sample, rf=.003, mar=.005, omega_threshold=.002, conditional_downside=conditional)
    for key, value in expected.items():
        assert_value(actual.metric("period." + key), value)


def test_met02_t02_scoped_baseline_short_and_partial_periods():
    times = [0, DAY_NS // 12]
    contract = replace(policy(times, 120.), scope="scoped", partial_periods="exclude_disclosed")
    actual = reduce_account(observations(times, [120., 132.], [0., .1], [True, False]), contract)
    assert actual.metric("account.total_return").value == pytest.approx(.1)
    assert actual.metric("account.cagr_elapsed").status == "insufficient"
    assert actual.metric("period.count").value == 1
    assert json.loads(actual.provenance_json)["partial_periods"] == 1
    assert actual.metric("drawdown.episode_count").value == 0
    assert actual.metric("account.calmar").status == "undefined"


@pytest.mark.parametrize("terminal", [0., -20.])
def test_met02_t02_liquidation_does_not_abs_growth(terminal):
    obs = observations([0, DAY_NS], [100., terminal])
    report = reduce_account(obs, policy([0, DAY_NS]))
    assert report.metric("account.cagr_elapsed").status == "undefined"
    assert report.metric("drawdown.max_depth").value == 1 - terminal / 100.
    assert report.metric("period.sharpe").status == "unavailable"


@pytest.mark.parametrize("backend", ["python", "numba"])
def test_met02_t03_deepest_longest_gap_tie_and_tolerance(backend):
    times = [i * DAY_NS for i in range(9)]
    marks = [100, 50, 100, 90, 95, 96, 97, 100, 95]
    obs, contract = observations(times, marks), policy(times)
    expected = drawdown_episodes(times, marks, 100, 0)
    report = reduce_account(obs, contract, backend=backend, retain_episodes=True)
    assert report.episodes.to_rows() == expected["episodes"]
    meta = json.loads(report.provenance_json)
    assert meta["deepest_episode_index"] == 0 and meta["longest_episode_index"] == 1
    near = observations([0, DAY_NS], [100., 99.999999999])
    tolerant = reduce_account(near, replace(policy([0, DAY_NS]), recovery_relative_tolerance=1e-10),
                              backend=backend, retain_episodes=True)
    assert not tolerant.episodes.to_rows()
    assert tolerant.metric("drawdown.max_depth").value > 0
    assert np.array_equal(near.equity, [100., 99.999999999])


def test_met02_t02_observed_daily_no_fill_and_first_fee():
    times = [0, DAY_NS // 2, 3 * DAY_NS, 3 * DAY_NS + DAY_NS // 2]
    obs = observations(times, [90, 90, 95, 99])
    contract = replace(policy(times), sampling="observed_daily_utc", annual_periods=365., equity_clock="daily_close")
    derived = obs.with_derived_returns(contract, partial_mask=[True, True], witness="two partial UTC days")
    assert derived.returns.end_times_ns.tolist() == [DAY_NS // 2, times[-1]]
    assert derived.returns.values == pytest.approx([-.1, .1])
    report = reduce_account(derived, contract)
    assert report.metric("account.total_return").value == pytest.approx(-.01)
    assert report.metric("period.count").value == 2
    assert "ffill" not in json.dumps(report.to_metadata())


@pytest.mark.parametrize("times,marks", [([], []), ([0], []), ([1, 0], [100, 90]),
    ([0, 0], [100, 90]), ([0], [float("nan")]), ([0], [float("inf")]), ([.5], [100])])
def test_met02_t02_invalid_observations_are_not_cleaned(times, marks):
    with pytest.raises(ValueError):
        observations(times, marks)


def test_met02_t02_scope_frequency_cashflow_and_nonpositive_denominator_guards():
    obs, contract = observations([0, DAY_NS], [100, 101], [0, .01]), policy([0, DAY_NS])
    with pytest.raises(ValueError, match="sampling"):
        reduce_account(obs, replace(contract, sampling="observed_bar"))
    with pytest.raises(ValueError, match="scope"):
        reduce_account(obs, replace(contract, scope_end_ns=2 * DAY_NS))
    with pytest.raises(NotImplementedError, match="flow"):
        replace(contract, cashflows="deposit")
    with pytest.raises(ValueError, match="nonpositive"):
        observations([0, DAY_NS, 2 * DAY_NS], [100, 0, 0]).with_derived_returns(
            replace(policy([0, DAY_NS, 2 * DAY_NS]), sampling="observed_bar"),
            partial_mask=[False] * 3, witness="complete bars")
    with pytest.raises(ValueError, match="boolean"):
        observations([0, DAY_NS], [100, 101], [0, .01], [0, 1])


def test_met02_t08_t10_snapshot_immutable_identity_and_no_eager_numba():
    marks = np.array([100., 90., 100.])
    obs = observations([0, DAY_NS, 2 * DAY_NS], marks)
    signature = obs.identity
    marks[1] = 50
    assert obs.equity[1] == 90 and obs.identity == signature
    for array in (obs.equity, obs.times_ns):
        with pytest.raises(ValueError):
            array.setflags(write=True)
    assert observations([0, DAY_NS, 2 * DAY_NS], marks).identity != signature
    with pytest.raises(NotImplementedError, match="V2"):
        reduce_account(obs, policy([0, DAY_NS, 2 * DAY_NS]), backend="rust")


@pytest.mark.parametrize("seed", range(5))
def test_met02_t01_t08_random_differential_and_scalar_detail(seed):
    rng = np.random.default_rng(seed)
    marks = np.r_[100., 100 * np.cumprod(1 + rng.uniform(-.15, .15, 299))]
    times = np.cumsum(rng.integers(1, DAY_NS, len(marks), dtype=np.int64))
    obs = observations(times, marks)
    contract = policy(times)
    oracle = drawdown_episodes(times.tolist(), marks.tolist(), 100, int(times[0]))
    python = reduce_account(obs, contract, retain_episodes=True)
    native = reduce_account(obs, contract, backend="numba", retain_episodes=True)
    scalar = reduce_account(obs, contract, backend="numba")
    assert python.episodes.to_rows() == oracle["episodes"] == native.episodes.to_rows()
    for left, right, tiny in zip(python.metrics, native.metrics, scalar.metrics):
        assert left.status == right.status == tiny.status
        assert_value(right, left.value)
        assert_value(tiny, left.value)
    assert scalar.episodes is None
    json.dumps(native.to_metadata(), allow_nan=False)
