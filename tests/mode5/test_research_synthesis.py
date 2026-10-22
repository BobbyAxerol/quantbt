from copy import deepcopy

import pytest

from tools.mode5_research.research_synthesis import (
    account_snapshot, regime_snapshot, tradeoff_against, winner_snapshot,
)


def account():
    def view(label, count, result, utility):
        return dict(environment_id=label, daily_count=count, net_return=result,
            raw_sharpe=1., max_drawdown=.1, daily_loss_es=.02, daily_returns=[99.] * 3,
            utility=dict(value=utility, status="VALID", unit="decimal_return"),
            params={"secret": "never_copy"}, final_equity=22000., initial_capital=20000.)
    return dict(whole=view("whole_path", 638, .2, .08),
        annual=[view("2025", 365, .1, -.02), view("2026", 273, .09, -.03)],
        activity=dict(fills=12, closed_campaigns=4, secret="not_for_report"),
        common_eligible=True, positive_years=2, calendar_views=2,
        annual_floor_return=.09, annual_floor_utility=-.03, worst_annual_dd=.1)


def held():
    return dict(center=account(), double_fee=account(), held=[dict(candidate_id="a", summary=account())],
        full_mandate_survival=1., held_whole_utility=dict(status="INSUFFICIENT_COVERAGE",
            expected_unique_probes=1, valid_probes=1,
            coverage=dict(status="INSUFFICIENT_COVERAGE", uncovered_axes=["x"])))


def regimes():
    states = [dict(state=i, diagnostic_support=3, undefined_diagnostic=0,
        candidates=[dict(private_params="never_copy")],
        winners=dict(raw=dict(candidate_id="center", comparison_to_diagnostic_panel=dict(regret=.01),
            observation=dict(state=i, days=10, pnl=20., mean_net_daily_return=.001,
                exposed_bars=3, daily_returns=[99.], raw_private="never_copy")))) for i in (-1, 0)]
    family = dict(states=states, rank_associations=[dict(left=i, right=j, spearman=None,
        paired_candidates=3) for i in (-1, 0) for j in (-1, 0)])
    return dict(diagnostic_candidates=3, selected_arms=1, unit="decimal return/day",
        rank_basis="diagnostic only", views=dict(descriptive=dict(trend=deepcopy(family),
            volatility=deepcopy(family)), vintage=dict(trend=deepcopy(family))))


def test_account_keeps_negative_year_utility_without_every_year_gate_or_daily_copy():
    source = account()
    before = deepcopy(source)
    result = account_snapshot(source)
    assert result["common_eligible"] and result["annual_floor_utility"] == -.03
    assert result["positive_years"] == result["positive_year_denominator"] == 2
    assert result["partial_calendar_environments"] == ["2026"]
    assert "daily_returns" not in str(result) and "never_copy" not in str(result)
    assert source == before


def test_legacy_unavailable_ledger_and_exposure_basis_remain_explicit():
    source = account()
    source["activity"].update(fills=None, closed_campaigns=None, fee_sum=None,
        cost_ledger="UNAVAILABLE_LEGACY_NOT_ZERO", exposure_fraction=.3,
        exposure_basis="signal weights, not fills", fee_one_way=.0004,
        legacy_fee_parameter=.0008, limitation="no accepted-fill ledger")
    result = account_snapshot(source)["activity"]
    assert result["fills"] is None and result["fee_sum"] is None
    assert result["cost_ledger"] == "UNAVAILABLE_LEGACY_NOT_ZERO"
    assert result["exposure_basis"] == "signal weights, not fills"
    assert result["fee_one_way"] == .0004 and result["legacy_fee_parameter"] == .0008
    assert result["limitation"] == "no accepted-fill ledger"


@pytest.mark.parametrize("key,value", [("positive_years", 1), ("calendar_views", 3),
    ("annual_floor_utility", .03), ("worst_annual_dd", .2)])
def test_account_rejects_inconsistent_claims(key, value):
    source = account()
    source[key] = value
    with pytest.raises(ValueError, match="disagrees"):
        account_snapshot(source)


def test_unknown_utility_is_preserved_not_replaced_with_zero_or_missing_year_dropped():
    source = account()
    source["annual"][0]["utility"].update(value=None, status="UNDEFINED", reason="no_support")
    source["annual_floor_utility"] = None
    result = account_snapshot(source)
    assert result["annual_floor_utility"] is None and result["undefined_annual_utilities"] == 1
    assert len(result["annual"]) == 2
    assert result["annual"][0]["utility"]["reason"] == "no_support"


def test_account_rejects_missing_or_duplicated_annual_support():
    source = account()
    source["annual"][0]["daily_count"] -= 1
    with pytest.raises(ValueError, match="partition"):
        account_snapshot(source)
    source = account()
    source["annual"][1]["environment_id"] = "2025"
    with pytest.raises(ValueError, match="distinct"):
        account_snapshot(source)


def test_all_feasible_probes_completed_is_not_full_radius_basin_certificate():
    result = winner_snapshot(held())
    assert result["feasible_measurements_complete"] and not result["basin_certified"]
    assert result["geometric_coverage"]["status"] == "INSUFFICIENT_COVERAGE"
    assert result["full_mandate_survival"] == 1.
    assert winner_snapshot(dict(status="NO_SELECTION")) == dict(status="NO_SELECTION")


@pytest.mark.parametrize("status", ["QUALITY_FAIL", "FRAGILE_CENTER", "OBSERVED_QUALITY_BASIN"])
def test_real_local_owner_statuses_require_observed_required_radii(status):
    source = held()
    source["held_whole_utility"]["status"] = status
    with pytest.raises(ValueError, match="radii"):
        winner_snapshot(source)
    source["held_whole_utility"]["coverage"]["status"] = "OBSERVED_REQUIRED_RADII"
    assert winner_snapshot(source)["held_whole_utility"]["status"] == status
    assert not winner_snapshot(source)["basin_certified"]


@pytest.mark.parametrize("change", ["duplicate", "survival", "missing", "stress_calendar"])
def test_held_summary_cannot_mask_missing_measurements_or_different_stress_scope(change):
    source = held()
    if change == "duplicate":
        source["held"] *= 2
    elif change == "survival":
        source["full_mandate_survival"] = .5
    elif change == "missing":
        source["held"] = []
    else:
        source["double_fee"]["whole"]["stop_ns"] = 42
    with pytest.raises(ValueError):
        winner_snapshot(source)


def test_regime_join_keeps_unknown_state_and_rank_nulls_without_duplicate_reference_panel():
    source = regimes()
    before = deepcopy(source)
    result = regime_snapshot(source, dict(raw="center"))
    assert result["views"]["descriptive"]["trend"]["states"][0]["state"] == -1
    assert result["views"]["descriptive"]["trend"]["rank_associations"][0]["spearman"] is None
    assert "daily_returns" not in str(result) and "never_copy" not in str(result)
    assert result["family_totals_are_additive"] is False
    assert source == before


@pytest.mark.parametrize("change", ["identity", "missing_count", "pnl", "days", "matrix"])
def test_regime_mismatch_is_not_rendered_as_complete(change):
    source = regimes()
    states = source["views"]["descriptive"]["trend"]["states"]
    if change == "identity":
        states[0]["winners"]["raw"]["candidate_id"] = "other"
    elif change == "missing_count":
        states[0]["undefined_diagnostic"] = 1
    elif change == "pnl":
        states[0]["winners"]["raw"]["observation"]["pnl"] += 1.
    elif change == "days":
        states[0]["winners"]["raw"]["observation"]["days"] -= 1
    else:
        source["views"]["descriptive"]["trend"]["rank_associations"].pop()
    with pytest.raises(ValueError):
        regime_snapshot(source, dict(raw="center"))


def test_tradeoffs_keep_opposing_directions_and_do_not_infer_dominance():
    baseline = account_snapshot(account())
    candidate = deepcopy(baseline)
    candidate["annual_floor_utility"] += .1
    candidate["whole"]["max_drawdown"] += .05
    candidate["whole"]["raw_sharpe"] = None
    result = tradeoff_against(candidate, baseline)
    assert result["delta"]["annual_floor_utility"] == pytest.approx(.1)
    assert result["delta"]["whole_dd"] == pytest.approx(.05)
    assert result["delta"]["whole_sharpe"] is None
    assert result["statistical_significance"] == "NOT_TESTED_BY_THIS_COLD_JOIN"
