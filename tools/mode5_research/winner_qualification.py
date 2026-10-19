"""Cold, original-account robustness views; never search, select or simulate."""

from dataclasses import asdict

import numpy as np

from quantbt.diagnostics.geometry.neighborhoods import active_neighbors
from quantbt.mode5.diagnostics.identity import digest
from tools.mode5_research.full_scope_views import DailyObservations, HOUR, feature_partitions


def environment_views(frame, *, descriptive_stop_ns, historical_fit_stop_ns):
    """Reuse the registered feature owner; keep retrospective rights explicit."""
    times = frame.index.asi8
    if (not len(times) or times[-1] + HOUR != descriptive_stop_ns
            or not times[0] < historical_fit_stop_ns <= descriptive_stop_ns):
        raise ValueError("exact market scope and mature historical fit required")
    views = {}
    for purpose, stop in (("asof_calibration_descriptive", descriptive_stop_ns),
                          ("decision_vintage", historical_fit_stop_ns)):
        views[purpose] = feature_partitions(times, frame.close.to_numpy(), frame.volume.to_numpy(),
            window=168, cutoff_ns=stop, purpose=purpose, fit_start_ns=int(times[0]),
            fit_stop_ns=stop, quantiles=(.25, .75))
    return views


def attribute_original_account(frame, arrays, views, *, initial_capital):
    """Attribute actual marks without resetting or joining disjoint prices."""
    owned = {name: np.asarray(arrays[name]).reshape(-1) for name in ("equity", "positions")}
    if "fees" in arrays:
        owned["fees"] = np.asarray(arrays["fees"]).reshape(-1)
    owned["times_ns"] = frame.index.asi8
    daily = DailyObservations.from_account(owned, initial_capital=initial_capital)
    results = {}
    returns, valid, pnl = (getattr(daily, name).array() for name in ("returns", "valid_returns", "pnl"))
    for namespace, families in views.items():
        results[namespace] = {}
        for family, partition in families.items():
            labels = np.asarray(partition["labels"])[::24]
            attribution = daily.attribute(labels)
            if not np.isclose(attribution["conservation_residual"], 0., rtol=0., atol=1e-7):
                raise ValueError("state attribution does not conserve original account PnL")
            for row in attribution["rows"]:
                mask = labels == row["state"]
                observed = returns[mask & valid]
                row.update(mean_net_daily_return=float(observed.mean()) if len(observed) else None,
                    positive_return_days=int((observed > 0).sum()),
                    negative_return_days=int((observed < 0).sum()),
                    zero_return_days=int((observed == 0).sum()),
                    undefined_return_days=int((mask & ~valid).sum()),
                    positive_day_pnl=float(np.maximum(pnl[mask], 0.).sum()),
                    negative_day_loss=float(-np.minimum(pnl[mask], 0.).sum()),
                    conditional_geometric_return=(float(np.prod(1. + observed) - 1.)
                        if bool(valid[mask].all()) else None),
                    geometric_interpretation="descriptive selected-day factors; not a traded regime path",
                    mean_pnl_on_initial_capital=float(pnl[mask].mean()/initial_capital))
            metadata = {key: value for key, value in partition.items() if key not in {"labels", "valid"}}
            results[namespace][family] = dict(attribution=attribution, partition=metadata)
    return dict(schema="mode5.actual_winner_environment_readback.v1", views=results,
        daily_observations=len(returns), initial_capital=initial_capital,
        whole_pnl=float(pnl.sum()), optimizer_proposals=0, financial_executions=0,
        roles="descriptive readback; no prior advice/selection is changed",
        overlapping_families_are_independent=False)


def winner_neighborhood(geometry, params, *, radius=.05, seed=731):
    """Complete existing schema design, including invalid and duplicate rows."""
    center = geometry.resolve(params)
    numeric = geometry.numeric_names(center)
    groups = (numeric,) if len(numeric) > 1 else ()
    neighborhood = active_neighbors(geometry, center, radius=radius, seed=seed,
        role="local_validation", minimum_radius=radius, joint_groups=groups)
    rows = []
    for proposal in neighborhood.rows:
        row = asdict(proposal)
        row["point"] = None if proposal.point is None else dict(
            candidate_id=proposal.point.identity, params=proposal.point.params,
            active_names=proposal.point.active_names)
        rows.append(row)
    body = dict(schema="mode5.actual_winner_held_design.v1", center_id=center.identity,
        geometry_id=geometry.identity, radius=radius, seed=seed, role="local_validation",
        rows=rows, coverage=neighborhood.coverage, covariance_status=neighborhood.covariance_status,
        used_for_selection=False, temporal_independent_oos=False)
    return dict(body, design_id=digest(body)), neighborhood
