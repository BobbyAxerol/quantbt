"""Canonical cold R/Q arithmetic and the existing fractional empirical tail."""

import numpy as np


def raw_effect(ia, iw, oa, ow):
    if not all(
        isinstance(v, (int, float)) and np.isfinite(v) for v in (ia, iw, oa, ow)
    ):
        raise ValueError("finite raw Sharpe required")
    r = (ia - oa) - (iw - ow)
    q = ow - oa
    effect = ia - iw
    if not np.isclose(r, effect + q, rtol=1e-12, atol=1e-12):
        raise ValueError("R/Q accounting identity")
    return dict(
        R=r,
        Q=q,
        IS_contribution=effect,
        anchor_is=ia,
        selected_is=iw,
        anchor_forward=oa,
        selected_forward=ow,
    )


def worst_fraction(values, fraction=0.2):
    if not 0 < fraction <= 1:
        raise ValueError("tail mass")
    ordered = np.sort(np.asarray(values, dtype=float))
    if not len(ordered) or not np.isfinite(ordered).all():
        raise ValueError("finite nonempty tail")
    mass = len(ordered) * fraction
    full = int(mass)
    return float(
        (ordered[:full].sum() + (mass - full) * ordered[min(full, len(ordered) - 1)])
        / mass
    )


def opportunity(revision, winner, predictions, *, floor=-0.1):
    task = revision.task
    anchor = task.anchor_candidate_evaluation_id
    outcomes = {o.evaluation_id: o.observation for o in revision.outcomes}
    fixed = set(revision.panel.base_members) | {anchor}
    valid = {
        eid: o.raw_sharpe
        for eid, o in outcomes.items()
        if eid in fixed and o.status.value == "VALID"
    }
    anchor_o = outcomes.get(anchor)
    if not valid or anchor_o is None or anchor_o.status.value != "VALID":
        return dict(
            status="UNDEFINED_FIXED_PANEL", valid=len(valid), members=len(fixed)
        )
    best = max(valid, key=lambda e: (valid[e], e))
    p = {p["evaluation_id"]: p for p in predictions}
    passed = [
        v
        for e, v in valid.items()
        if e in p and p[e].get("qhat") is not None and p[e]["qhat"] >= floor
    ]
    return dict(
        status="OBSERVED_FIXED_BASE_PANEL",
        valid=len(valid),
        members=len(fixed),
        best_forward=valid[best],
        anchor_forward=anchor_o.raw_sharpe,
        best_vs_anchor=valid[best] - anchor_o.raw_sharpe,
        best_id=best,
        winner_preexisting_forward=outcomes[winner].raw_sharpe
        if winner in outcomes and outcomes[winner].status.value == "VALID"
        else None,
        best_excluded_by_Q=best in p
        and p[best].get("qhat") is not None
        and p[best]["qhat"] < floor,
        best_passing_forward=max(passed) if passed else None,
        q_floor=floor,
        interpretation="finite preexisting acquisition panel; not full-pool oracle; new queried winners excluded",
    )
