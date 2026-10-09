"""Shared-date overlap, fixed family weights and explicit support/missingness."""

import numpy as np

from tools.mode5_diagnostics.identity import digest
from .manifests import calendar


def overlap_support(times_ns, views, *, family_weights, exposure, campaigns_per_day,
                    minimum_days, minimum_exposed_bars, minimum_campaigns):
    times = calendar(times_ns)
    if (any(type(v) is not int or v < 0 for v in (minimum_days,minimum_exposed_bars,minimum_campaigns))
            or minimum_days < 1 or not views or not family_weights
            or any(not np.isfinite(v) or v <= 0 for v in family_weights.values())
            or not np.isclose(sum(family_weights.values()),1.,rtol=0,atol=1e-12)):
        raise ValueError("frozen family weights and explicit support requirements required")
    exposed, campaigns = np.asarray(exposure), np.asarray(campaigns_per_day)
    if (exposed.shape != times.shape or campaigns.shape != times.shape or not np.isfinite(exposed).all()
            or not np.isfinite(campaigns).all() or np.any(exposed < 0) or np.any(campaigns < 0)):
        raise ValueError("qualified daily exposure/campaign support required")
    if np.any(exposed != np.floor(exposed)) or np.any(campaigns != np.floor(campaigns)):
        raise ValueError("exposure bars and campaign counts must be exact integers")
    unique, duplicates, seen = [], [], {}
    for name,row in sorted(views.items()):
        if set(row) != {"family", "membership"} or row["family"] not in family_weights:
            raise ValueError("known family membership required")
        raw = np.asarray(row["membership"])
        if raw.shape != times.shape or raw.dtype.kind not in "iu" or not np.isin(raw,[-1,0,1]).all():
            raise ValueError("1=member, 0=nonmember, -1=unavailable; missing is not a normal state")
        identity = digest(dict(family=row["family"], calendar=times.tolist(), membership=raw.tolist()))
        if identity in seen:
            duplicates.append(dict(view=name, duplicate_of=seen[identity]))
        else:
            seen[identity] = name
            unique.append((name,row["family"],raw))
    masks = np.array([raw == 1 for _,_,raw in unique])
    weights = np.zeros(masks.shape,dtype=np.float64)
    for family,weight in family_weights.items():
        indices = [i for i,(_,f,_) in enumerate(unique) if f == family]
        if not indices:
            continue
        count = masks[indices].sum(axis=0)
        weights[indices] = weight * masks[indices] / np.where(count,count,1)
    rows = []
    for i,(name,family,raw) in enumerate(unique):
        mask = masks[i]
        days, active, completed = int(mask.sum()), int(exposed[mask].sum()), int(campaigns[mask].sum())
        episodes = int(np.sum(mask & np.r_[True,~mask[:-1]]))
        if not days:
            status = "MISSING" if np.any(raw == -1) else "EMPTY"
        elif active == 0:
            status = "NO_TRADE"
        elif days < minimum_days or active < minimum_exposed_bars or completed < minimum_campaigns:
            status = "INSUFFICIENT_SUPPORT"
        else:
            status = "SUPPORTED_DESCRIPTIVE"
        rows.append(dict(view=name,family=family,observed_days=days,unavailable_days=int(np.sum(raw == -1)),
            exposed_bars=active,closed_campaigns=completed,contiguous_episodes=episodes,
            allocated_date_mass=float(weights[i].sum()),status=status,
            independent_observations=None, cold_start_dependence="episodes share one market/account; recurrence is not IID support"))
    return dict(schema="quantbt.mode5.environment_overlap.v1", rows=rows, duplicate_views=duplicates,
        overlap_days=(masks.astype(np.int64) @ masks.astype(np.int64).T).tolist(),
        ordered_views=[name for name,_,_ in unique], unique_observed_dates=len(times),
        covered_unique_dates=int(masks.any(axis=0).sum()), repeated_memberships=int(masks.sum()-masks.any(axis=0).sum()),
        family_weights=dict(family_weights), allocated_mass_by_date=weights.sum(axis=0).tolist(),
        total_allocated_mass=float(weights.sum()), unallocated_mass=float(len(times)-weights.sum()),
        policy="fixed family mass split within family per date; missing mass not silently redistributed",
        independent_information_count=None, bootstrap_contract="common date/block draws shared across candidates and both families")
