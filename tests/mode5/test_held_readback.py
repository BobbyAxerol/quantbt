from copy import deepcopy

import pytest

from quantbt.mode5.geometry.schema import EffectiveGeometry
from tools.mode5_research.held_readback import account_summary, qualify_held, require_same_design
from tools.mode5_research.winner_qualification import winner_neighborhood


def metric(value=.1, quality=True):
    return dict(quality_pass=quality, risk_pass=True, support_pass=True, raw_sharpe=.4,
        utility=dict(value=value, status="VALID"), net_return=.2, max_drawdown=.1,
        daily_returns=[.01, -.01])


def setup():
    geometry = EffectiveGeometry.from_ranges(dict(length=(2, 20), scale=dict(kind="float", low=.1, high=1.)))
    design, neighborhood = winner_neighborhood(geometry, dict(length=2, scale=.5), radius=.12, seed=733)
    def record(cid, multiplier=1.):
        return dict(candidate_id=cid, role="held_local_validation", design_role="local_validation",
            fee_multiplier=multiplier, actual_strategy_rerun=True, whole=metric(),
            annual=[metric(-.2, False), metric(.4)])
    center = record(design["center_id"])
    neighbors = {r.point.identity: record(r.point.identity) for r in neighborhood.rows if r.status == "READY"}
    return design, neighborhood, center, neighbors, record(design["center_id"], 2.)


def test_original_mandate_and_incomplete_radius_preserved():
    design, neighborhood, center, neighbors, stress = setup()
    original = deepcopy((center, neighbors, stress))
    result = qualify_held(design, neighborhood, center, neighbors, stress)
    assert result["center"]["common_eligible"]
    assert result["center"]["annual_floor_utility"] == -.2
    assert result["held_whole_utility"]["coverage"] == neighborhood.coverage
    assert result["full_mandate_survival"] == 1.
    assert (center, neighbors, stress) == original
    assert "daily_returns" not in result["center"]["whole"]


def test_bad_feasible_neighbor_is_not_dropped():
    design, neighborhood, center, neighbors, stress = setup()
    one = next(iter(neighbors.values()))
    one["whole"] = metric(-.5, False)
    result = qualify_held(design, neighborhood, center, neighbors, stress)
    assert result["held_whole_utility"]["empirical_worst_utility"] == -.5
    assert result["full_mandate_survival"] < 1.
    assert len(result["held"]) == len(neighbors)


@pytest.mark.parametrize("kind", ["missing", "wrong_candidate", "selection_role", "fee", "not_rerun"])
def test_mismatched_held_input_fails_closed(kind):
    design, neighborhood, center, neighbors, stress = setup()
    if kind == "missing":
        neighbors.pop(next(iter(neighbors)))
    elif kind == "wrong_candidate":
        stress["candidate_id"] = "not_the_winner"
    elif kind == "selection_role":
        next(iter(neighbors.values()))["role"] = "formal_search"
    elif kind == "fee":
        stress["fee_multiplier"] = 1.
    else:
        stress["actual_strategy_rerun"] = False
    with pytest.raises(ValueError):
        qualify_held(design, neighborhood, center, neighbors, stress)


def test_design_roundtrip_and_empty_annual_fail_closed():
    import json
    design, _, center, _, _ = setup()
    require_same_design(design, json.loads(json.dumps(design)))
    with pytest.raises(ValueError, match="design changed"):
        require_same_design({**design, "seed": 1}, design)
    with pytest.raises(ValueError, match="annual"):
        account_summary({**center, "annual": []})
