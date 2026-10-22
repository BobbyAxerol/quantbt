from types import SimpleNamespace

import pytest

from tools.meta_model_research.decision_policy import (
    assert_native_reduction,
    choose,
    query_queue,
    zero_control,
)


def prediction(eid, raw, y, q, distance=1):
    return dict(
        evaluation_id=eid,
        candidate_id=eid,
        raw_is=raw,
        yhat=y,
        qhat=q,
        distance=distance,
    )


def test_fixed_arms_isolate_guard_from_ranking_and_keep_anchor():
    rows = [
        prediction("a", 2.0, 0.0, 0.0, 0),
        prediction("b", 0.0, -1.95, -0.05),
        prediction("c", 2.2, -0.5, 0.7),
    ]
    assert choose(rows, "a", "N")["winner"] == "a"
    assert choose(rows, "a", "R")["winner"] == "b"
    assert choose(rows, "a", "G")["winner"] == "c"
    assert choose(rows, "a", "F")["winner"] == "c"
    assert_native_reduction(rows, choose(rows, "a", "R"))


def test_signed_decay_and_guard_pass_are_not_realized_forward_guarantees():
    ia, oa, ib, ob = 2.0, 1.0, 0.0, 0.8
    R = (ia - oa) - (ib - ob)
    Q = ob - oa
    assert R > 0 and Q < 0 and R == pytest.approx(ia - ib + Q)
    assert (
        choose(
            [prediction("a", ia, 0, 0, 0), prediction("b", ib, -1.95, -0.05)], "a", "R"
        )["winner"]
        == "b"
    )


@pytest.mark.parametrize("policy", ["R", "X", "G", "F"])
def test_cold_fallback(policy):
    assert choose([], "a", policy)["winner"] == "a"


def test_zero_control_retains_incumbent_and_detects_zero_distance_alias():
    rows = [prediction("b", 1, 0, 0, 0), prediction("a", 1, 0, 0, 0)]
    candidates = {
        k: SimpleNamespace(effective_params={"x": i}) for i, k in enumerate(("a", "b"))
    }
    result = zero_control(rows, "b", candidates)
    assert result["same_id"] is False and result["same_effective_params"] is False
    rows[0]["distance"], rows[1]["distance"] = 0, 1
    assert zero_control(rows, "b", candidates)["same_id"]


def test_tie_is_two_pass_and_order_independent():
    rows = [
        prediction("z", 1, 0, 0, 0),
        prediction("b", 2, -1, 0.5, 1),
        prediction("c", 2, -1 + 5e-11, 0.5, 0.5),
    ]
    assert choose(rows, "z", "R")["winner"] == "c"
    assert choose(rows[::-1], "z", "R") == choose(rows, "z", "R")


def test_queue_priority_dedup_and_independence_from_outcome_values():
    def row(g, f, p, qid, status="MISSING_EXECUTION"):
        return dict(
            group=g, fold=f, policy=p, winner="w", query_id=qid, witness_status=status
        )

    rows = [
        row("A-HMA", 25, "G", "same"),
        row("A-SC", 26, "X", "late"),
        row("A-HMA", 25, "X", "same"),
        row("A-SC", 25, "X", "first"),
        row("A-SC", 25, "F", "undefined", "NO_VARIANCE"),
    ]
    queue = query_queue(rows)
    assert [r["query_id"] for r in queue] == ["first", "same", "late"]
    assert query_queue([dict(r, Q=-99, R=88) for r in rows[::-1]]) == queue


def test_malformed_scored_anchor_fails():
    with pytest.raises(ValueError, match="anchor"):
        choose([prediction("a", 1, 0.01, 0, 0)], "a", "R")
