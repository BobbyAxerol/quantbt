"""Cold qualification of frozen winners; no search or financial execution."""

from quantbt.diagnostics.geometry.basins import local_summary
from quantbt.mode5.continuous_eligibility import WholeAccountEligibility
from quantbt.mode5.diagnostics.identity import digest


def account_summary(record):
    """Use the existing mandate, not an every-year-positive replacement."""
    whole, annual = record["whole"], record["annual"]
    if not annual:
        raise ValueError("original annual account views required")
    utilities = [row["utility"]["value"] for row in annual]
    # Daily paths remain in the authoritative observation, not copied per view.
    compact = lambda row: {key: value for key, value in row.items() if key != "daily_returns"}
    return dict(whole=compact(whole), annual=[compact(row) for row in annual],
        activity=record.get("original_measurement"),
        common_eligible=WholeAccountEligibility().eligible(whole, annual),
        positive_years=sum(row["net_return"] > 0 for row in annual),
        calendar_views=len(annual),
        annual_floor_utility=min(utilities) if all(v is not None for v in utilities) else None,
        annual_floor_return=min(row["net_return"] for row in annual),
        worst_annual_dd=max(row["max_drawdown"] for row in annual),
        daily_paths="retained in original observation; omitted from this summary")


def qualify_held(design, neighborhood, center, neighbors, stress):
    """Fail closed on identity/role gaps and retain bad feasible neighbors."""
    expected = {row.point.identity for row in neighborhood.rows if row.status == "READY"}
    if (set(neighbors) != expected or center["candidate_id"] != design["center_id"]
            or stress["candidate_id"] != design["center_id"]
            or center["fee_multiplier"] != 1. or stress["fee_multiplier"] != 2.):
        raise ValueError("exact frozen center, neighbors and fee stress required")
    for cid, row in neighbors.items():
        if (row["candidate_id"] != cid or row["role"] != "held_local_validation"
                or row["fee_multiplier"] != 1. or row["design_role"] != "local_validation"):
            raise ValueError("held identity/role/economics mismatch")
    if stress["role"] != "held_local_validation" or stress.get("actual_strategy_rerun") is not True:
        raise ValueError("fee stress must rerun the actual strategy/account")
    evaluated = {cid: dict(status="COMPLETE" if row["whole"]["utility"]["status"] == "VALID" else "INVALID",
        utility=row["whole"]["utility"]["value"]) for cid, row in neighbors.items()}
    local = local_summary(center["whole"]["utility"]["value"], neighborhood, evaluated,
        quality_floor=0., reference_scale=1., reference_id="whole_economic_utility_decimal_return")
    detail = [dict(candidate_id=cid, summary=account_summary(row)) for cid, row in sorted(neighbors.items())]
    return dict(center=account_summary(center), held_whole_utility=local, held=detail,
        full_mandate_survival=sum(row["summary"]["common_eligible"] for row in detail)/len(detail) if detail else None,
        double_fee=account_summary(stress), design_id=design["design_id"],
        original_selected_unchanged=True,
        interpretation="frozen actual winner, finite held points; not a full-radius basin, objective basin or independent temporal holdout")


def require_same_design(actual, frozen):
    if digest(actual) != digest(frozen):
        raise ValueError("registered held design changed")
