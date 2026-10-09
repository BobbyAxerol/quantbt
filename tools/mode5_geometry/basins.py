"""Observed local support, downside and separate basin representatives."""

import math

import numpy as np


def local_summary(center_utility, neighborhood, evaluations, *, quality_floor, reference_scale, reference_id):
    if (not all(math.isfinite(v) for v in (center_utility, quality_floor, reference_scale)) or
            reference_scale <= 0 or not reference_id):
        raise ValueError("same-channel utilities and frozen positive reference required")
    expected = {r.point.identity for r in neighborhood.rows if r.status == "READY"}
    if set(evaluations) != expected:
        raise ValueError("one record per unique effective probe, including failed evaluations")
    valid, failed = [], []
    for identity, row in evaluations.items():
        value = row.get("utility")
        if row.get("status") == "COMPLETE" and value is not None and math.isfinite(value):
            valid.append(float(value))
        else:
            failed.append(identity)
    worst = min([center_utility, *valid])
    downside = max(0., center_utility-worst)
    complete = bool(expected) and not failed and neighborhood.coverage["status"] == "OBSERVED_REQUIRED_RADII"
    quality = center_utility >= quality_floor
    status = "INSUFFICIENT_COVERAGE" if not complete else (
        "QUALITY_FAIL" if not quality else ("FRAGILE_CENTER" if worst < quality_floor else "OBSERVED_QUALITY_BASIN"))
    return dict(status=status,
        center_utility=center_utility, center_quality_pass=quality,
        empirical_worst_utility=worst, max_downside=downside, reference_normalized_downside=downside/reference_scale,
        reference_id=reference_id, reference_scale=reference_scale,
        valid_probes=len(valid), failed_probe_ids=failed, expected_unique_probes=len(expected),
        quality_survival_fraction=sum(v >= quality_floor for v in valid)/len(valid) if valid else None,
        downside_values=[max(0., center_utility-v) for v in valid],
        lower_tail_utility=min(valid) if valid else None,
        lower_tail_definition="observed_minimum_v1_not_CVaR",
        covariance_status=neighborhood.covariance_status, coverage=neighborhood.coverage,
        claim="finite tested neighbors only; not a ball-wide bound or unseen-market generalization")


def held_support(selection, validation):
    if (selection.role != "selection_probe" or validation.role != "local_validation" or selection.seed == validation.seed):
        raise ValueError("independent registered probe roles/seeds required")
    used = {r.point.identity for r in selection.rows if r.point}
    held = {r.point.identity for r in validation.rows if r.point}
    return dict(selection_unique=len(used), validation_unique=len(held),
        overlapping_effective=len(used & held), held_distinct=len(held-used),
        status="HAS_DISTINCT_HELD_PROBES" if held-used else "INSUFFICIENT_DISTINCT_HELD_PROBES",
        interpretation="held design directions on development, not temporal holdout")


def representative(geometry, points, *, kind):
    if not points or len({p.identity for p in points}) != len(points):
        raise ValueError("distinct supported basin members required")
    if kind == "medoid":
        best = min(points, key=lambda p: (sum(geometry.distance(p, q) for q in points), p.identity))
        return dict(kind=kind, point=best, actual_evaluation_required=False)
    if kind != "centroid":
        raise ValueError("unknown representative")
    numeric = geometry.numeric_names(points[0])
    if (any(p.active_names != points[0].active_names for p in points) or
            any(s.choices and s.variable and s.name in points[0].active_names for s in geometry.specs)):
        raise ValueError("categorical/conditional representatives require finite-support medoid")
    params = points[0].params
    for name in numeric:
        params[name] = geometry.decode(name, float(np.mean([geometry.coordinate(name, p.params[name]) for p in points])))
    point = geometry.resolve(params)
    return dict(kind="schema_quantized_centroid_v1", point=point,
        actual_evaluation_required=point.identity not in {p.identity for p in points})


def basin_catalog(geometry, points, *, linkage_radius, minimum_members):
    if not 0 < linkage_radius <= 1 or minimum_members < 2 or len({p.identity for p in points}) != len(points):
        raise ValueError("frozen linkage/minimum distinct member policies required")
    remaining, groups = set(range(len(points))), []
    while remaining:
        component = {min(remaining)}
        changed = True
        while changed:
            new = {j for j in remaining-component if any(geometry.distance(points[i], points[j]) <= linkage_radius for i in component)}
            changed = bool(new)
            component.update(new)
        remaining.difference_update(component)
        members = tuple(points[i] for i in sorted(component))
        groups.append(dict(basin_id="basin-"+str(len(groups)), members=members,
            status="SUPPORTED_OBSERVED_COMPONENT" if len(members) >= minimum_members else "INSUFFICIENT_MEMBERS",
            medoid=representative(geometry, members, kind="medoid")["point"],
            interpretation="schema-radius connected component, not inferred economic quality"))
    return tuple(groups)
