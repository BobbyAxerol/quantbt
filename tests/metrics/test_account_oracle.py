import json
import math
from pathlib import Path

import pytest

from .reference_oracle import DAY_NS, account_growth, drawdown_episodes, period_statistics, utc_ns


FIXTURES = json.loads((Path(__file__).parent / "fixtures/manual.json").read_text())


@pytest.mark.parametrize("case", FIXTURES["drawdowns"], ids=lambda c: c["id"])
def test_t03_manual_episode_clocks(case):
    times = [utc_ns(t) for t in case["times"]]
    report = drawdown_episodes(times, case["equity"], case["baseline"], times[0])
    episode, = report["episodes"]
    assert report["max_depth"] == pytest.approx(case["max_depth"])
    assert episode["elapsed_ns"] / DAY_NS == pytest.approx(case["elapsed_days"])
    assert episode["observed_underwater_marks"] == case["underwater_marks"]
    assert episode["observed_underwater_days"] == case["underwater_days"]
    assert episode["inclusive_underwater_calendar_days"] == case["calendar_days"]
    assert episode["recovered"] == case["recovered"]
    assert (episode["recovery_time_ns"] is None) != case["recovered"]


def test_t03_deepest_is_not_longest_or_mean_underwater():
    marks = [100, 50, 100, 90, 95, 96, 97, 100, 95]
    report = drawdown_episodes([i * DAY_NS for i in range(9)], marks, 100, 0)
    assert report["deepest"]["elapsed_ns"] == 2 * DAY_NS
    assert report["longest"]["elapsed_ns"] == 5 * DAY_NS
    assert report["mean_recovered_duration_ns"] == 3.5 * DAY_NS
    assert report["current_open_duration_ns"] == DAY_NS
    assert report["mean_episode_depth"] == pytest.approx((.5 + .1 + .05) / 3)
    assert report["mean_underwater_depth"] == pytest.approx((.5 + .1 + .05 + .04 + .03 + .05) / 6)
    assert report["ulcer_index"] == pytest.approx(math.sqrt((.25 + .01 + .0025 + .0016 + .0009 + .0025) / 9))


def test_t03_tie_breaks_and_tolerance_do_not_mutate_equity():
    values = [100, 90, 90, 100, 90, 100]
    before = list(values)
    report = drawdown_episodes([i * DAY_NS for i in range(6)], values, 100, 0)
    assert report["deepest"]["trough_time_ns"] == DAY_NS
    assert values == before
    near = [100., 99.999999999]
    exact = drawdown_episodes([0, DAY_NS], near, 100, 0)
    tolerant = drawdown_episodes([0, DAY_NS], near, 100, 0, recovery_tolerance=1e-10)
    assert exact["episodes"] and not tolerant["episodes"]
    assert tolerant["depths"] == exact["depths"]


def test_t03_timezone_dst_and_nanosecond_elapsed():
    assert utc_ns("2025-01-01T07:00:00+07:00") == utc_ns("2025-01-01T00:00:00Z")
    before = utc_ns("2025-03-09T01:00:00-05:00")
    after = utc_ns("2025-03-09T03:00:00-04:00")
    report = drawdown_episodes([before, after, after + 123], [100, 90, 100], 100, before)
    assert report["episodes"][0]["elapsed_ns"] == 3_600_000_000_123
    with pytest.raises(ValueError, match="timezone"):
        utc_ns("2025-01-01")


@pytest.mark.parametrize("values", [[100], [100, 100], [100, 110]])
def test_t03_flat_or_rising_has_no_episode(values):
    report = drawdown_episodes([i * DAY_NS for i in range(len(values))], values, 100, 0)
    assert report["max_depth"] == report["current_open_duration_ns"] == 0
    assert report["mean_recovered_duration_ns"] is None


@pytest.mark.parametrize("times,marks,baseline,start", [
    ([], [], 100, 0), ([0], [], 100, 0), ([1, 0], [100, 90], 100, 0),
    ([0, 0], [100, 90], 100, 0), ([0], [100], 0, 0),
    ([0], [float("nan")], 100, 0), ([0], [float("inf")], 100, 0),
    ([0], [100], 100, 1), ([.5], [100], 100, 0),
])
def test_t02_invalid_path_is_not_cleaned(times, marks, baseline, start):
    with pytest.raises(ValueError):
        account_growth(times, marks, baseline, start)


def test_t02_baseline_first_cost_scope_and_partial_cagr():
    full = account_growth([0, DAY_NS], [90, 90], 100, 0)
    assert full["total_return"] == pytest.approx(-.1)
    assert full["cagr_elapsed"] == pytest.approx(.9 ** 365.25 - 1)
    scoped = account_growth([0, DAY_NS], [120, 132], 120, 0)
    assert scoped["total_return"] == pytest.approx(.1)
    short = account_growth([0, 2 * DAY_NS // 24], [100, 110], 100, 0)
    assert short["total_return"] == pytest.approx(.1) and short["cagr_elapsed"] is None
    with pytest.raises(NotImplementedError):
        account_growth([0, DAY_NS], [100, 200], 100, 0, cashflows=[100])


@pytest.mark.parametrize("end", [0, -20])
def test_t02_bankrupt_total_return_not_abs_cagr(end):
    report = account_growth([0, DAY_NS], [100, end], 100, 0)
    assert report["total_return"] == end / 100 - 1
    assert report["cagr_elapsed"] is None


def test_t02_disjoint_segments_have_independent_baselines():
    first = drawdown_episodes([0, DAY_NS], [100, 90], 100, 0)
    second = drawdown_episodes([10 * DAY_NS, 11 * DAY_NS], [90, 99], 90, 10 * DAY_NS)
    assert first["current_open_duration_ns"] == DAY_NS
    assert not second["episodes"]
    assert account_growth([10 * DAY_NS, 11 * DAY_NS], [90, 99], 90, 10 * DAY_NS)["total_return"] == pytest.approx(.1)


def test_t04_hand_return_distribution_and_denominators():
    expected = FIXTURES["periods"]
    report = period_statistics(expected["returns"])
    for actual, key in [("mean_arithmetic", "mean"), ("mean_geometric", "geometric"),
                        ("sharpe", "sharpe_unannualized"), ("sortino", "sortino_all"),
                        ("profit_factor", "profit_factor"), ("avg_win", "avg_win"),
                        ("avg_loss", "avg_loss"), ("win_rate", "win_rate")]:
        assert report[actual] == pytest.approx(expected[key])
    assert period_statistics(expected["returns"], conditional_downside=True)["sortino"] == .5
    assert period_statistics(expected["returns"], rf=.005)["sharpe"] == pytest.approx(0.)
    assert period_statistics([.01, -.01], mar=.005)["sortino"] == pytest.approx(-math.sqrt(2) / 3)


@pytest.mark.parametrize("sample,profit_factor,geometric", [
    ([0, 0], None, 0), ([.1, .1], math.inf, .1), ([-.1, -.1], 0, -.1),
    ([-1, 0], 0, None), ([.1], math.inf, .1),
])
def test_t04_zero_loss_flat_short_and_bankrupt(sample, profit_factor, geometric):
    report = period_statistics(sample)
    assert report["profit_factor"] == profit_factor
    assert report["mean_geometric"] == pytest.approx(geometric) if geometric is not None else report["mean_geometric"] is None
    if len(set(sample)) == 1:
        assert report["sharpe"] is None


@pytest.mark.parametrize("sample", [[], [float("nan")], [float("inf")]])
def test_t04_returns_not_silently_dropped(sample):
    with pytest.raises(ValueError):
        period_statistics(sample)
