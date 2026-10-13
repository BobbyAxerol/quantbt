import numpy as np
import pytest

from tools.mode5_research.full_scope_views import (
    DAY, HOUR, DailyObservations, feature_partitions, finite_panel_environment_comparison,
)


def account(days=20):
    n = days * 24
    return dict(times_ns=np.arange(n, dtype=np.int64) * HOUR,
        equity=100. + np.arange(n) * .1, positions=np.ones(n), fees=np.full(n, .01))


def test_daily_and_unknown_state_marks_conserve_pnl_costs_and_cross_state_positions():
    raw = account()
    obs = DailyObservations.from_account(raw, initial_capital=100.)
    labels = np.tile([-1, 0, 1, 0, 2], 4)
    out = obs.attribute(labels)
    assert out["grouped_pnl"] == pytest.approx(raw["equity"][-1] - 100., abs=1e-12)
    assert sum(r["fees"] for r in out["rows"]) == pytest.approx(raw["fees"].sum())
    assert out["rows"][0]["status"] == "UNKNOWN"
    assert all(r["annualized_sharpe"] is None for r in out["rows"])
    raw["equity"][:] = 0
    assert obs.equity_after.array()[-1] > 100


def test_bankrupt_returns_are_not_zero_imputed_for_conditional_statistics():
    raw = account()
    raw["equity"][240:] = -10
    out = DailyObservations.from_account(raw, initial_capital=100.).attribute(np.zeros(20, dtype=int))
    assert out["rows"][0]["return_status"] == "BANKRUPT"
    assert out["rows"][0]["conditional_period_sharpe"] is None
    assert out["whole_pnl"] == pytest.approx(-110., abs=1e-12)


def test_flat_warmup_stays_in_calendar_and_keeps_original_account_baseline():
    raw = account(days=20)
    warmup = 5 * 24
    raw["equity"][:warmup] = 100.
    raw["positions"][:warmup] = 0.
    raw["fees"][:warmup] = 0.
    obs = DailyObservations.from_account(raw, initial_capital=100.)
    np.testing.assert_array_equal(obs.returns.array()[:5], np.zeros(5))
    assert len(obs.times.array()) == 20
    labels = np.r_[np.full(5, -1), np.zeros(15, dtype=int)]
    output = obs.attribute(labels)
    unready = output["rows"][0]
    assert unready["days"] == 5
    assert unready["pnl"] == unready["fees"] == unready["exposed_bars"] == 0
    assert output["grouped_pnl"] == pytest.approx(raw["equity"][-1] - 100.)


def test_incomplete_day_clock_does_not_get_annualized_as_full_day():
    raw = {k: v[:-1] for k, v in account().items()}
    with pytest.raises(ValueError, match="complete hourly"):
        DailyObservations.from_account(raw, initial_capital=100.)


def feature_market():
    t = np.arange(24 * 32, dtype=np.int64) * HOUR
    close = 100 + .03 * np.arange(len(t)) + np.sin(np.arange(len(t)) / 7.)
    volume = 100 + np.arange(len(t)) % 79
    return t, close, volume


def test_decision_vintage_labels_survive_future_mutation_and_current_bar_price_change():
    t, close, volume = feature_market()
    args = dict(window=24, fit_start_ns=0, fit_stop_ns=10 * DAY, cutoff_ns=10 * DAY,
        purpose="decision_vintage")
    base = feature_partitions(t, close, volume, **args)
    altered_c, altered_v = close.copy(), volume.copy()
    cut = 24 * 20
    altered_c[cut:] *= 1.5
    altered_v[cut:] *= 2
    new = feature_partitions(t, altered_c, altered_v, **args)
    for name in base:
        np.testing.assert_array_equal(base[name]["labels"][:cut + 1], new[name]["labels"][:cut + 1])
        assert base[name]["thresholds"] == new[name]["thresholds"]
        assert base[name]["fit_identity"] == new[name]["fit_identity"]
        assert not base[name]["valid"][:240].any()


def test_full_development_descriptive_fit_has_explicit_different_rights():
    t, close, volume = feature_market()
    kwargs = dict(window=24, fit_start_ns=0, fit_stop_ns=32 * DAY, cutoff_ns=32 * DAY)
    x = feature_partitions(t, close, volume, purpose="asof_calibration_descriptive", **kwargs)
    assert all(v["purpose"] == "asof_calibration_descriptive" for v in x.values())
    assert x["volatility"]["valid"][25]


def test_rank_reversal_does_not_disqualify_a_stable_best_candidate():
    values = np.array([[10., 10., 10.], [9., 1., 5.], [1., 9., 4.], [3., 3., 6.]])
    out = finite_panel_environment_comparison(["best", "a", "b", "c"], ["x", "y", "z"], values)
    assert all(r["candidate_id"] == "best" for r in out["leave_out"])
    assert all(r["near_optimal_intersection"] == ["best"] for r in out["pairs"])


def test_held_environment_is_not_used_in_leave_out_pool_or_rank():
    values = np.array([[1., 1., np.nan], [0., .5, 20.]])
    out = finite_panel_environment_comparison(["a", "b"], ["x", "y", "held"], values)
    row = out["leave_out"][-1]
    assert row["candidate_id"] == "a" and row["held_utility"] is None


def test_missing_pairs_and_constant_outcome_keep_nulls_and_support():
    out = finite_panel_environment_comparison(["a", "b"], ["x", "y"], [[1., np.nan], [1., 2.]])
    row = next(r for r in out["pairs"] if r["left"] == "x" and r["right"] == "y")
    assert row["spearman"] is None and row["common_candidates"] == 1
