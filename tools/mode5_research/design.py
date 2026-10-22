"""Outcome-independent, branch-balanced effective configuration admission."""

from collections import defaultdict, deque
from dataclasses import dataclass

from tools.mode5_geometry.design import design_identity, neutral_coverage
from tools.mode5_diagnostics.identity import digest


@dataclass(frozen=True)
class DiscoveryDesign:
    ledger: object
    selected: tuple
    requested_unique: int
    seed: int

    @property
    def identity(self):
        proposals = design_identity(self.ledger.rows, method="branch_balanced_sobol_v1",
            seed=self.seed, schema_id=self.ledger.geometry.identity)
        return digest(dict(proposals=proposals, requested_unique=self.requested_unique,
            admission="structural_round_robin_v1", selected=[row.row_id for row in self.selected]))

    def coverage(self):
        points = [row.point for row in self.selected]
        return dict(raw_proposals=len(self.ledger.rows),
            unique_effective=len(points), requested_unique=self.requested_unique,
            branch_counts={branch: sum(row.direction == branch for row in self.selected)
                for branch in sorted({row.direction for row in self.ledger.rows})},
            axis_values={spec.name: len({point.params[spec.name] for point in points
                if spec.name in point.active_names}) for spec in self.ledger.geometry.specs
                if spec.variable and spec.name not in dict(self.ledger.geometry.inactive)},
            status="READY" if len(points) == self.requested_unique else "INSUFFICIENT_COVERAGE",
            claim="effective unique coverage, not exact global Sobol sensitivity or full-space proof")


def discovery_design(geometry, *, branches, target=128, seed=731):
    """Only structural feasibility/collisions may affect inclusion, never outcomes.

    Each registered branch has its own finite Sobol proposal cap. Round-robin
    admission makes branch quotas explicit even with unequal feasible yield.
    All rejected and surplus proposals remain in the ledger.
    """
    if type(target) is not int or target < 1:
        raise ValueError("positive unique target required")
    ledger = neutral_coverage(geometry, branches=branches, seed=seed)
    buckets = defaultdict(deque)
    for row in ledger.rows:
        if row.status == "READY":
            buckets[row.direction].append(row)
    selected = []
    while len(selected) < target and any(buckets.values()):
        for branch in sorted(buckets):
            if buckets[branch] and len(selected) < target:
                selected.append(buckets[branch].popleft())
    return DiscoveryDesign(ledger, tuple(selected), target, seed)
