"""Branch-local rank associations on a declared outcome-blind finite panel."""

from collections import Counter
from collections.abc import Mapping

import numpy as np
from scipy.stats import rankdata

from .estimators import _bootstrap_config


def _nullable_number(value):
    if value is None:
        return None
    if (
        not isinstance(value, (float, int, np.number))
        or np.iscomplexobj(value)
        or not np.isfinite(value)
    ):
        raise ValueError(
            "finite numeric columns or explicit null required; categories belong in branch_id"
        )
    number = float(value)
    if not np.isfinite(number):
        raise ValueError("finite representable numeric column required")
    return number


def _association(rows, axis, metric):
    valid = [
        r
        for r in rows
        if r["status"] in {"COMPLETE", "NO_TRADE"}
        and r["parameters"][axis] is not None
        and r["metrics"][metric] is not None
    ]
    count = len(valid)
    x = np.array([r["parameters"][axis] for r in valid])
    y = np.array([r["metrics"][metric] for r in valid])
    support = dict(
        paired_candidates=count,
        unique_axis_values=len(np.unique(x)),
        unique_metric_values=len(np.unique(y)),
    )
    if count < 3:
        return "INSUFFICIENT_PAIRED_CANDIDATES", None, support
    if support["unique_axis_values"] < 2:
        return "NO_AXIS_VARIATION_ON_PANEL", None, support
    if support["unique_metric_values"] < 2:
        return "CONSTANT_METRIC_ON_PANEL", None, support
    x, y = rankdata(x, method="average"), rankdata(y, method="average")
    x, y = x - x.mean(), y - y.mean()
    rho = float(
        np.clip(np.dot(x / np.linalg.norm(x), y / np.linalg.norm(y)), -1.0, 1.0)
    )
    return (
        "OBSERVED_RANK_ASSOCIATION" if rho else "NO_RANK_ASSOCIATION_ON_PANEL",
        rho,
        support,
    )


def finite_panel_screen(
    candidates,
    *,
    panel_id,
    axis_names,
    active_axes_by_branch,
    units,
    outcome_blind,
    bootstrap_seed,
    bootstrap_resamples,
    confidence_level=0.95,
):
    """Multi-metric Spearman associations, never Sobol or causal importance.

    Each candidate has candidate_id, branch_id, parameters, metrics, status.
    Every active numeric axis and metric must be present (explicit nulls for
    missing measurements). Cast ties use midranks. Categorical states belong
    in declared branches, not scalar label ranks. NO_TRADE rows with measured
    metrics remain eligible; failed/unavailable rows remain in the ledger.

    The caller declares that the roster was chosen without these outcomes.
    Within each branch, a private seeded RNG resamples whole candidate records
    jointly for every axis/metric; ranks are recomputed in every replication.
    Intervals are CONDITIONAL_FINITE_PANEL, not market, causal or population CI.
    """
    if (
        type(panel_id) is not str
        or not panel_id.strip()
        or outcome_blind is not True
        or type(axis_names) is not tuple
        or not axis_names
        or any(type(a) is not str or not a.strip() for a in axis_names)
        or len(set(axis_names)) != len(axis_names)
        or not isinstance(active_axes_by_branch, Mapping)
        or not active_axes_by_branch
        or not isinstance(units, Mapping)
        or not units
        or any(
            type(k) is not str or not k.strip() or type(v) is not str or not v.strip()
            for k, v in units.items()
        )
    ):
        raise ValueError(
            "declared outcome-blind panel, axes, branches and metric units required"
        )
    _bootstrap_config(bootstrap_seed, bootstrap_resamples, confidence_level)
    active = {}
    for branch, axes in active_axes_by_branch.items():
        if (
            type(branch) is not str
            or not branch.strip()
            or type(axes) is not tuple
            or any(type(a) is not str for a in axes)
            or len(set(axes)) != len(axes)
            or not set(axes) <= set(axis_names)
        ):
            raise ValueError(
                "branch active axes must be distinct declared numeric axes"
            )
        active[branch] = axes
    if set().union(*map(set, active.values())) != set(axis_names):
        raise ValueError("every declared axis must be active in at least one branch")
    rows, seen = [], set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("explicit candidate records required")
        cid, branch, status = (
            candidate.get(k) for k in ("candidate_id", "branch_id", "status")
        )
        params, metrics = candidate.get("parameters"), candidate.get("metrics")
        if (
            type(cid) is not str
            or not cid.strip()
            or cid in seen
            or type(branch) is not str
            or branch not in active
            or type(status) is not str
            or status
            not in {"COMPLETE", "NO_TRADE", "FAILED", "INFEASIBLE", "CANCELLED"}
            or not isinstance(params, Mapping)
            or not set(active[branch]) <= set(params)
            or not set(params) <= set(axis_names)
            or not isinstance(metrics, Mapping)
            or set(metrics) != set(units)
        ):
            raise ValueError(
                "unique candidate identity, declared branch/status and complete columns required"
            )
        seen.add(cid)
        rows.append(
            dict(
                candidate_id=cid,
                branch_id=branch,
                status=status,
                parameters={k: _nullable_number(v) for k, v in params.items()},
                metrics={k: _nullable_number(v) for k, v in metrics.items()},
            )
        )
    rng = np.random.default_rng(bootstrap_seed)
    branches, missing = {}, []
    for branch in sorted(active):
        records = [r for r in rows if r["branch_id"] == branch]
        associations, draws = {}, {}
        for axis in axis_names:
            associations[axis] = {}
            for metric, unit in units.items():
                if axis not in active[branch]:
                    associations[axis][metric] = dict(
                        status="INACTIVE_ON_BRANCH",
                        rho=None,
                        output_unit=unit,
                        confidence_interval=None,
                        bootstrap=None,
                        support=dict(
                            paired_candidates=0,
                            unique_axis_values=0,
                            unique_metric_values=0,
                        ),
                    )
                    continue
                status, rho, support = _association(records, axis, metric)
                support.update(
                    branch_candidates=len(records),
                    excluded_status_rows=sum(
                        r["status"] not in {"COMPLETE", "NO_TRADE"} for r in records
                    ),
                    missing_axis_rows=sum(
                        r["parameters"][axis] is None for r in records
                    ),
                    missing_metric_rows=sum(
                        r["metrics"][metric] is None for r in records
                    ),
                )
                associations[axis][metric] = dict(
                    status=status,
                    rho=rho,
                    output_unit=unit,
                    support=support,
                    confidence_interval=None,
                    bootstrap=None,
                )
                if rho is None:
                    missing.append(
                        dict(branch_id=branch, axis=axis, metric=metric, reason=status)
                    )
                else:
                    draws[(axis, metric)] = []
        if draws:
            for _ in range(bootstrap_resamples):
                sample = [
                    records[i] for i in rng.integers(len(records), size=len(records))
                ]
                for (axis, metric), values in draws.items():
                    values.append(_association(sample, axis, metric)[1])
        alpha = (1 - confidence_level) / 2
        for (axis, metric), values in draws.items():
            invalid = sum(v is None for v in values)
            result = associations[axis][metric]
            result["bootstrap"] = dict(
                status="AVAILABLE"
                if not invalid
                else "UNAVAILABLE_DEGENERATE_RESAMPLES",
                valid_resamples=bootstrap_resamples - invalid,
                invalid_resamples=invalid,
            )
            if not invalid:
                result["confidence_interval"] = np.quantile(
                    values, [alpha, 1 - alpha]
                ).tolist()
        branches[branch] = dict(
            active_axes=list(active[branch]),
            candidate_ids=[r["candidate_id"] for r in records],
            status_counts=dict(sorted(Counter(r["status"] for r in records).items())),
            associations=associations,
        )
    return dict(
        method="branch_rank_association_v1",
        inference="CONDITIONAL_FINITE_PANEL",
        panel_id=panel_id,
        outcome_blind=True,
        axis_names=list(axis_names),
        units=dict(units),
        candidate_rows=rows,
        branches=branches,
        missing_support=missing,
        bootstrap=dict(
            method="candidate_percentile_bootstrap_v1",
            seed=bootstrap_seed,
            resamples=bootstrap_resamples,
            confidence_level=confidence_level,
            resample_unit="candidate_within_branch",
            paired_columns=True,
        ),
        sensitivity_indices=None,
        parameter_removal_authorized=False,
        interpretation="associations conditional on this finite roster/branch; dependent-axis confounding and selection remain possible; no causal, market-CI or global-importance claim",
    )
