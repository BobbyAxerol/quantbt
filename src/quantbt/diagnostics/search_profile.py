"""Observed search support only; no global dimension or sampler-volume estimator."""

from collections import Counter

from .identity import canonical, digest


def search_profile(owner, rows, research):
    byid = {row.evaluation_id: row for row in rows}
    points = {row.point.identity: row.point for row in rows}
    axes, branches = [], {}
    for spec in owner.geometry.specs:
        active = [point.params[spec.name] for point in points.values() if spec.name in point.params]
        numeric = active if not spec.choices else []
        axes.append(dict(name=spec.name, kind=spec.kind, fixed=not spec.variable,
            conditional=bool(spec.active_if), source_inactive_reason=dict(owner.geometry.inactive).get(spec.name),
            active_effective_points=len(active), observed_values=len({canonical(v) for v in active}),
            declared_low=spec.low, declared_high=spec.high, step=spec.step, log=spec.log,
            observed_min=min(numeric) if numeric else None, observed_max=max(numeric) if numeric else None,
            low_boundary_points=sum(v == spec.low for v in numeric),
            high_boundary_points=sum(v == spec.high for v in numeric),
            declared_choices=list(spec.choices), observed_choices=sorted({canonical(v) for v in active}) if spec.choices else []))
    for point in points.values():
        categories = {s.name: point.params[s.name] for s in owner.geometry.specs
                      if s.choices and s.name in point.params}
        key = digest(dict(active=point.active_names, categories=categories))
        branch = branches.setdefault(key, dict(branch_id=key, categories=categories,
            active_axes=list(point.active_names), effective_points=0))
        branch['effective_points'] += 1
    ledger = research.trials
    attempts = dict(status='OBSERVED' if ledger else 'NOT_SUPPLIED',
        attempted=len(ledger) if ledger else None,
        declared_budget=research.requested_trials,
        remaining_declared_slots=max(0, research.requested_trials-len(ledger)) if ledger and research.requested_trials else None,
        over_declared_slots=max(0,len(ledger)-research.requested_trials) if ledger and research.requested_trials else None,
        status_counts=dict(sorted(Counter(t.status for t in ledger).items())),
        prune_reasons=dict(sorted(Counter(t.reason for t in ledger if t.status=='PRUNED').items())),
        measured_time_attempts=sum(t.elapsed_seconds is not None for t in ledger),
        missing_time_attempts=sum(t.elapsed_seconds is None for t in ledger),
        summed_observed_attempt_seconds=sum(t.elapsed_seconds for t in ledger if t.elapsed_seconds is not None) if ledger else None,
        time_convention='sum of producer attempt durations; not wall time or nonoverlapping CPU time',
        reason=None if ledger else 'No terminal attempt ledger supplied; observation count cannot stand in for trials.')
    curve, best, seen = [], None, set()
    sign = 1 if owner.context.direction=='maximize' else -1
    for trial in ledger:
        row = byid.get(trial.evaluation_id)
        if trial.status=='COMPLETE' and row.status in {'COMPLETE','NO_TRADE'}:
            seen.add(row.point.identity)
            value = row.metrics.data[owner.context.primary_metric]
            if value is not None and (best is None or sign*value>sign*best):
                best = value
        curve.append(dict(attempt=trial.ordinal+1, observed_effective_points=len(seen),
                          best_observed_primary=best))
    return dict(attempts=attempts, retained_observations=len(rows),
        unique_effective_points=len(points), duplicate_effective_observations=len(rows)-len(points),
        unique_complete_points=len({r.point.identity for r in rows if r.status in {'COMPLETE','NO_TRADE'}}),
        effective_transform_counts=dict(sorted(Counter(reason for point in points.values()
            for _,reason in point.changes).items())),
        axes=axes, branches=[branches[k] for k in sorted(branches)],
        nominal_variable_axes=sum(s.variable for s in owner.geometry.specs),
        observed_varying_axes=sum(a['observed_values']>1 for a in axes),
        effective_dimension=dict(status='NOT_ESTIMATED', value=None,
            reason='Observed coordinate variation is not a qualified intrinsic-dimension estimate.'),
        constraint_count=len(owner.geometry.constraints), constraints=[dict(names=list(c.names),strict=c.strict) for c in owner.geometry.constraints],
        constraint_coverage=dict(status='NOT_ESTIMATED',value=None,
            reason='Retained feasible points do not enumerate attempted infeasible regions or manifold volume.'),
        attempt_curve=curve, curve_metric=owner.context.primary_metric,
        limitations=['Sampled density and adaptive budget curves are not basin volume or neutral-design sensitivity.',
                     'No extrapolation to an unexecuted 256/412-trial study or independent origin count.'])
