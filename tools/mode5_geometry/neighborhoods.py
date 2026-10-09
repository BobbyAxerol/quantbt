"""Independent schema directions with optional basin-local covariance proposals."""

from dataclasses import dataclass
import math

import numpy as np

from .design import ProposalLedger


@dataclass(frozen=True)
class Neighborhood:
    rows: tuple
    covariance_status: str
    coverage: dict
    seed: int
    role: str


def active_neighbors(geometry, center, *, radius, seed, role, minimum_radius,
                     joint_groups=(), cloud=(), rho=.2, tau=.001, minimum_cloud=5, cloud_radius=.25):
    if center.schema_id != geometry.identity:
        raise ValueError("center/schema mismatch")
    if (role not in {"selection_probe", "local_validation"} or type(seed) is not int or seed < 0 or
            not math.isfinite(radius) or not 0 < minimum_radius <= radius <= 1 or
            not 0 <= rho <= 1 or not math.isfinite(tau) or tau < 0 or minimum_cloud < 2 or not 0 < cloud_radius <= 1):
        raise ValueError("registered role, radius and covariance policies required")
    ledger = ProposalLedger(geometry, role=role)
    params = center.params
    numeric = geometry.numeric_names(center)
    moved = {name: [] for name in center.active_names}

    def propose(changes, direction, *, clipped=False):
        row = ledger.add(params | changes, direction=direction, reason="boundary_clipped" if clipped else None)
        if row.point is not None:
            for name in center.active_names:
                if name in row.point.params and row.point.params[name] != params[name]:
                    s = next(s for s in geometry.specs if s.name == name)
                    delta = 1. if s.choices else abs(geometry.coordinate(name, row.point.params[name])-geometry.coordinate(name, params[name]))
                    moved[name].append(delta)
        return row

    for s in geometry.specs:
        if s.name not in center.active_names:
            continue
        if s.choices:
            for choice in s.choices:
                if choice == params[s.name]:
                    continue
                changes = {s.name: choice}
                # A branch switch needs explicit baseline values for newly active children.
                evolving = params | changes
                for child in geometry.specs:
                    if child.active(evolving) and child.name not in evolving and child.name not in dict(geometry.inactive):
                        evolving[child.name] = child.value if child.fixed else (child.choices[0] if child.choices else child.low)
                        changes[child.name] = evolving[child.name]
                propose(changes, f"category:{s.name}")
            continue
        z = geometry.coordinate(s.name, params[s.name])
        for sign in (-1, 1):
            target = z+sign*radius
            propose({s.name: geometry.decode(s.name, float(np.clip(target, 0, 1)))},
                f"axis:{s.name}:{sign}", clipped=not 0 <= target <= 1)
            if s.kind == "integer" or s.step:
                step = s.step or 1
                adjacent = params[s.name]+sign*step
                propose({s.name: adjacent}, f"adjacent:{s.name}:{sign}")
    for group in joint_groups:
        if len(group) < 2 or set(group)-set(numeric):
            raise ValueError("joint group must name active numeric axes")
        for sign in (-1, 1):
            changes, clipped = {}, False
            for name in group:
                z = geometry.coordinate(name, params[name])+sign*radius
                changes[name] = geometry.decode(name, float(np.clip(z, 0, 1)))
                clipped |= not 0 <= z <= 1
            propose(changes, "joint:"+",".join(group)+f":{sign}", clipped=clipped)
    cov_status = "SCHEMA_ONLY_NO_CLOUD"
    if cloud:
        if any(p.schema_id != center.schema_id or p.active_names != center.active_names or
               any(p.params[s.name] != params[s.name] for s in geometry.specs if s.choices and s.name in params) for p in cloud):
            raise ValueError("covariance requires a single declared active branch/basin")
        if any(geometry.distance(center, p) > cloud_radius for p in cloud):
            raise ValueError("covariance cloud exceeds registered basin-local radius")
        unique = {p.identity: p for p in cloud}
        if not numeric or len(unique) < minimum_cloud:
            cov_status = "SCHEMA_ONLY_SPARSE_CLOUD"
        else:
            x = np.array([[geometry.coordinate(name, p.params[name]) for name in numeric] for p in unique.values()])
            cov = np.atleast_2d(np.cov(x, rowvar=False, ddof=1))
            if np.linalg.matrix_rank(cov) < len(numeric):
                cov_status = "SCHEMA_ONLY_SINGULAR_CLOUD"
            else:
                regularized = (1-rho)*cov + rho*np.diag(np.diag(cov)) + tau*tau*np.eye(len(numeric))
                values, vectors = np.linalg.eigh(regularized)
                cov_status = "REGULARIZED_PROPOSALS_NOT_HESSIAN"
                rng = np.random.default_rng(seed)
                for index in range(max(2, 2*len(numeric))):
                    u = rng.normal(size=len(numeric))
                    u /= np.linalg.norm(u)
                    shift = radius*vectors@(np.sqrt(np.maximum(values, 0))*u)
                    changes, clipped = {}, False
                    for name, delta in zip(numeric, shift):
                        z = geometry.coordinate(name, params[name])+float(delta)
                        changes[name] = geometry.decode(name, float(np.clip(z, 0, 1)))
                        clipped |= not 0 <= z <= 1
                    propose(changes, f"covariance:{index}", clipped=clipped)
    coverage = ledger.coverage()
    coverage.update(axis_max_radius={k: max(v, default=0.) for k, v in moved.items()},
        uncovered_axes=[k for k, v in moved.items() if max(v, default=0.) < minimum_radius],
        joint_groups=[list(g) for g in joint_groups],
        effective_center_collisions=sum(r.point is not None and r.point.identity == center.identity for r in ledger.rows),
        clipped_rows=sum(r.reason == "boundary_clipped" for r in ledger.rows))
    coverage["status"] = "INSUFFICIENT_COVERAGE" if coverage["uncovered_axes"] else "OBSERVED_REQUIRED_RADII"
    return Neighborhood(ledger.rows, cov_status, coverage, seed, role)
