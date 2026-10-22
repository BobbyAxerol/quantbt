"""Fixed research ablations over sealed predictions, without outcome access."""

from __future__ import annotations

import math

from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.selection import select_indices

from .protocol import GROUPS

POLICIES = ("N", "R", "X", "G", "F")
VERSION = "m4.ml06.fixed-policy.v1"
TOLERANCE = 1e-10


def choose(predictions, anchor, policy):
    if policy not in POLICIES:
        raise ValueError("unknown research policy")
    if len({p["evaluation_id"] for p in predictions}) != len(predictions):
        raise ValueError("duplicate prediction identity")
    if policy == "N":
        return dict(winner=anchor, tie_set=[anchor], safe_count=None)
    scored = [p for p in predictions if p["yhat"] is not None]
    if not scored:
        return dict(winner=anchor, tie_set=[anchor], safe_count=0)
    by_id = {p["evaluation_id"]: p for p in scored}
    if anchor not in by_id or any(
        by_id[anchor][k] != 0 for k in ("yhat", "qhat", "distance")
    ):
        raise ValueError("exact scored anchor required")
    if any(
        not math.isfinite(p[k]) for p in scored for k in ("yhat", "qhat", "distance")
    ):
        raise ValueError("finite prediction required")
    floor = 0.0 if policy == "G" else -0.1
    safe = [p for p in scored if p["qhat"] >= floor]
    score = (lambda p: -p["qhat"]) if policy == "F" else (lambda p: p["yhat"])
    best = min(map(score, safe))
    tied = [p for p in safe if score(p) <= best + TOLERANCE]
    winner = min(
        tied, key=lambda p: (p["distance"], p["candidate_id"], p["evaluation_id"])
    )
    return dict(
        winner=winner["evaluation_id"],
        tie_set=sorted(p["evaluation_id"] for p in tied),
        safe_count=len(safe),
    )


def zero_control(predictions, anchor, candidates):
    scored = [p for p in predictions if p["yhat"] is not None]
    if not scored:
        return dict(status="NOT_APPLICABLE_NO_SCORED_PREDICTIONS")
    ai = next(p["raw_is"] for p in scored if p["evaluation_id"] == anchor)
    zeros = [dict(p, yhat=0.0, qhat=p["raw_is"] - ai) for p in scored]
    result = choose(zeros, anchor, "R")
    selected = result["winner"]
    return dict(
        status="CHECKED",
        same_id=selected == anchor,
        same_effective_params=digest(candidates[selected].effective_params)
        == digest(candidates[anchor].effective_params),
        winner=selected,
        tie_count=len(result["tie_set"]),
    )


def assert_native_reduction(predictions, expected):
    """Independent research reducer must agree with the existing numeric seam."""
    scored = [p for p in predictions if p["yhat"] is not None]
    if not scored:
        return
    index, ties, _ = select_indices(
        [p["yhat"] for p in scored],
        [p["qhat"] for p in scored],
        [p["distance"] for p in scored],
        [(p["candidate_id"], p["evaluation_id"]) for p in scored],
        epsilon=0.1,
        tie_tolerance=TOLERANCE,
    )
    if scored[index]["evaluation_id"] != expected["winner"] or set(
        expected["tie_set"]
    ) != {scored[i]["evaluation_id"] for i in ties}:
        raise ValueError("research versus canonical selection differs")


def query_key(task, candidate, *, route_identity):
    return digest(
        dict(
            schema="m4.ml06.forward-query.v1",
            family=task.family,
            params=candidate.effective_params,
            cutoff=task.data_cutoff,
            forward_start=task.forward_start,
            forward_end=task.forward_end,
            is_input_signature=candidate.observation.input_signature,
            economics=candidate.observation.economics_id,
            metric=candidate.observation.metric_contract_id,
            seed=task.resolved_fold_seed,
            route_identity=route_identity,
            state="original_reset_flat_preload_prefix_original_terminal",
        )
    )


def query_queue(rows):
    """Order by fixed policy, then origin and group; never read outcome values."""
    eligible = [
        r
        for r in rows
        if r["fold"] >= 25
        and r["policy"] in ("X", "G", "F")
        and r["witness_status"] == "MISSING_EXECUTION"
    ]
    eligible.sort(
        key=lambda r: (
            ("X", "G", "F").index(r["policy"]),
            r["fold"],
            GROUPS.index(r["group"]),
        )
    )
    seen, result = set(), []
    for row in eligible:
        key = row["query_id"]
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {k: row[k] for k in ("group", "fold", "policy", "winner", "query_id")}
        )
    return result
