"""Pure cold summaries of qualified accounts; no selection or execution authority."""

from collections.abc import Mapping
import calendar
from copy import deepcopy
import math


ACCOUNT_FIELDS = (
    "account_identity", "environment_id", "start_ns", "stop_ns", "initial_capital",
    "baseline_equity", "baseline_source", "baseline_time_ns", "final_equity",
    "money_pnl", "net_return", "raw_sharpe", "max_drawdown", "daily_loss_es",
    "daily_count", "partial_days", "liquidated", "quality_pass", "risk_pass",
    "support_pass", "carried_watermark_drawdown", "carried_watermark_equity",
    "fill_support_status", "campaign_support_status", "fills", "closed_campaigns",
    "closed_records", "open_campaigns", "closed_record_unit", "metric_contract",
)
METRIC_FIELDS = ("metric_id", "value", "status", "reason", "unit", "sample_count")
STATE_FIELDS = (
    "state", "status", "days", "episodes", "pnl", "exposed_bars", "fees",
    "daily_loss_es", "mean_net_daily_return", "mean_pnl_on_initial_capital",
    "positive_return_days", "negative_return_days", "zero_return_days",
    "undefined_return_days", "positive_day_pnl", "negative_day_loss",
    "top_negative_day_pnl", "top_positive_day_pnl", "return_status",
    "conditional_geometric_return", "conditional_period_sharpe", "annualized_sharpe",
)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value, label):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"non-negative integer required: {label}")
    return value


def _project(row, keys):
    return {key: deepcopy(row[key]) for key in keys if key in row}


def _view(row):
    result = _project(row, ACCOUNT_FIELDS)
    for name in ("utility", "psr"):
        if name in row:
            result[name] = _project(row[name], METRIC_FIELDS)
    if "stream_sums" in row:
        result["stream_sums"] = _project(row["stream_sums"], ("fees", "funding"))
    return result


def _utility(row):
    metric = row.get("utility", {})
    value = metric.get("value")
    return value if metric.get("status") == "VALID" and _finite(value) else None


def account_snapshot(summary):
    """Preserve measured units and undefined views without copying daily arrays."""
    annual = [_view(row) for row in summary["annual"]]
    ids = [row["environment_id"] for row in annual]
    if not annual or len(ids) != len(set(ids)):
        raise ValueError("distinct original annual account views required")
    if not isinstance(summary.get("common_eligible"), bool):
        raise ValueError("measured common eligibility required")
    returns = [row.get("net_return") for row in annual]
    utilities = [_utility(row) for row in annual]
    dds = [row.get("max_drawdown") for row in annual]
    counts = [_count(row["daily_count"], "annual daily_count") for row in annual]
    positive = sum(value > 0 for value in returns if _finite(value))
    derived = dict(calendar_views=len(annual), positive_years=positive,
        annual_floor_return=min(returns) if all(map(_finite, returns)) else None,
        annual_floor_utility=min(utilities) if all(map(_finite, utilities)) else None,
        worst_annual_dd=max(dds) if all(map(_finite, dds)) else None)
    for name, value in derived.items():
        supplied = summary.get(name, value)
        if supplied is None or value is None:
            equal = supplied is value
        else:
            equal = math.isclose(supplied, value, rel_tol=0., abs_tol=1e-10)
        if not equal:
            raise ValueError(f"summary disagrees with original annual views: {name}")
    activity = summary.get("activity") or {}
    observed = _project(activity, ("fills", "closed_campaigns", "open_campaigns",
        "exposure_fraction", "fee_sum", "num_trades", "unit", "cost_ledger",
        "exposure_basis", "fee_one_way", "legacy_fee_parameter", "limitation"))
    whole = _view(summary["whole"])
    if whole.get("daily_count") != sum(counts):
        raise ValueError("annual daily support must partition the original whole account")
    return dict(whole=whole, annual=annual, activity=observed,
        common_eligible=summary["common_eligible"], **derived,
        positive_year_denominator=len(annual),
        undefined_annual_returns=sum(not _finite(value) for value in returns),
        undefined_annual_utilities=sum(value is None for value in utilities),
        partial_calendar_environments=[row["environment_id"] for row in annual
            if str(row["environment_id"]).isdigit() and row["daily_count"] <
                (366 if calendar.isleap(int(row["environment_id"])) else 365)],
        interpretation="annual views of one continuous account; not reset accounts or independent samples")


def winner_snapshot(row):
    """Keep incomplete radii explicit even when every feasible point was measured."""
    if row.get("status") == "NO_SELECTION":
        return {"status": "NO_SELECTION"}
    center, stress = account_snapshot(row["center"]), account_snapshot(row["double_fee"])
    for name in ("account_identity", "environment_id", "start_ns", "stop_ns"):
        if name != "account_identity" and center["whole"].get(name) != stress["whole"].get(name):
            raise ValueError("fee stress and center calendar differ")
    local = row["held_whole_utility"]
    expected = _count(local["expected_unique_probes"], "expected_unique_probes")
    valid = _count(local["valid_probes"], "valid_probes")
    held = row["held"]
    ids = [item["candidate_id"] for item in held]
    if len(ids) != len(set(ids)) or len(ids) != expected or valid > expected:
        raise ValueError("exact distinct held roster required")
    survivors = sum(item["summary"]["common_eligible"] is True for item in held)
    survival = survivors / expected if expected else None
    reported = row["full_mandate_survival"]
    if ((survival is None) != (reported is None)
            or survival is not None and not math.isclose(survival, reported, rel_tol=0., abs_tol=1e-12)):
        raise ValueError("full mandate survival disagrees with held observations")
    coverage = local["coverage"]
    known = ("INSUFFICIENT_COVERAGE", "QUALITY_FAIL", "FRAGILE_CENTER", "OBSERVED_QUALITY_BASIN")
    if local["status"] not in known:
        raise ValueError("unknown local_summary status")
    complete = expected > 0 and valid == expected and coverage["status"] == "OBSERVED_REQUIRED_RADII"
    if (local["status"] == "INSUFFICIENT_COVERAGE") == complete:
        raise ValueError("local status disagrees with required radii and measured support")
    return dict(status="QUALIFIED_REGISTERED_FINITE_WINNER_CHECKS", center=center,
        double_fee=stress, full_mandate_survival=survival,
        held_whole_utility=_project(local, (
            "status", "expected_unique_probes", "valid_probes", "center_utility",
            "center_quality_pass", "quality_survival_fraction", "empirical_worst_utility",
            "lower_tail_utility", "lower_tail_definition", "max_downside",
            "reference_normalized_downside", "reference_id", "reference_scale",
            "covariance_status")),
        geometric_coverage=_project(coverage, (
            "status", "raw_rows", "unique_effective", "clipped_rows", "collisions",
            "effective_center_collisions", "infeasible", "uncovered_axes", "uncovered_groups")),
        feasible_measurements_complete=valid == expected and expected > 0,
        basin_certified=False,
        claim="finite held whole-utility/mandate survival, not selected-objective or full-radius basin")


def regime_snapshot(panel, selected):
    """Read the existing diagnostic-only reference; never recompute a winner."""
    support = _count(panel["diagnostic_candidates"], "diagnostic_candidates")
    if not support or panel["selected_arms"] != len(selected):
        raise ValueError("measured diagnostic and selected support required")
    result, identity = {}, dict(selected)
    for namespace, families in panel["views"].items():
        result[namespace] = {}
        for family, source in families.items():
            states, rosters = [], []
            for state in source["states"]:
                winners = state["winners"]
                if {arm: value["candidate_id"] for arm, value in winners.items()} != identity:
                    raise ValueError("regime winners differ from actual frozen selections")
                defined = _count(state["diagnostic_support"], "diagnostic_support")
                missing = _count(state["undefined_diagnostic"], "undefined_diagnostic")
                if defined + missing != support:
                    raise ValueError("undefined diagnostic states cannot disappear")
                rosters.append(state["state"])
                states.append(dict(state=state["state"], diagnostic_support=defined,
                    undefined_diagnostic=missing,
                    **_project(state, ("positive_mean_candidates", "negative_mean_candidates", "flat_mean_candidates")),
                    winners={arm: dict(candidate_id=value["candidate_id"],
                        observation=_project(value["observation"], STATE_FIELDS),
                        comparison_to_diagnostic_panel=deepcopy(value["comparison_to_diagnostic_panel"]))
                        for arm, value in winners.items()}))
            if len(rosters) != len(set(rosters)) or not rosters:
                raise ValueError("distinct non-empty regime state roster required")
            associations = deepcopy(source["rank_associations"])
            if len(associations) != len(rosters)**2:
                raise ValueError("complete original pairwise regime matrix required")
            result[namespace][family] = dict(states=states, rank_associations=associations)
    for arm in identity:
        partitions = []
        for families in result.values():
            for family in families.values():
                rows = [state["winners"][arm]["observation"] for state in family["states"]]
                pnl = [row.get("pnl") for row in rows]
                if not all(map(_finite, pnl)):
                    raise ValueError("measured state PnL required for conservation")
                partitions.append((sum(pnl), sum(row["days"] for row in rows)))
        if partitions and any(not math.isclose(pnl, partitions[0][0], rel_tol=0., abs_tol=1e-7)
                or days != partitions[0][1] for pnl, days in partitions[1:]):
            raise ValueError("overlapping family PnL/support must conserve the same whole account")
    return dict(diagnostic_candidates=support, selected=identity, views=result,
        unit=panel["unit"], rank_basis=panel["rank_basis"], independent_regimes=False,
        family_totals_are_additive=False)


def tradeoff_against(candidate, baseline):
    """Signed descriptive differences, not a dominance score or significance test."""
    paths = dict(whole_sharpe=("whole", "raw_sharpe"), whole_return=("whole", "net_return"),
        whole_dd=("whole", "max_drawdown"), whole_daily_es95=("whole", "daily_loss_es"),
        annual_floor_utility=("annual_floor_utility",), annual_floor_return=("annual_floor_return",),
        worst_annual_dd=("worst_annual_dd",), positive_years=("positive_years",))
    def get(row, path):
        for key in path:
            row = row.get(key) if isinstance(row, Mapping) else None
        return row
    result = {}
    for name, path in paths.items():
        x, y = get(candidate, path), get(baseline, path)
        result[name] = x - y if _finite(x) and _finite(y) else None
    return dict(delta=result, direction="candidate minus reference; lower DD/tail is favorable",
        statistical_significance="NOT_TESTED_BY_THIS_COLD_JOIN")
