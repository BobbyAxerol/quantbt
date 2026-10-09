"""Seeded coverage/proposal ledgers; infeasible and effective duplicates retained."""

from dataclasses import dataclass
import json
import math

import numpy as np
from scipy.stats import qmc

from tools.mode5_diagnostics.identity import canonical, digest
from .schema import ResolvedPoint


@dataclass(frozen=True)
class ProbeRow:
    row_id: int
    role: str
    direction: str
    requested_json: str
    point: ResolvedPoint | None
    status: str
    duplicate_of: int | None
    reason: str | None


class ProposalLedger:
    def __init__(self, geometry, *, role):
        if role not in {"exploration", "geometry_fit", "selection_probe", "local_validation"}:
            raise ValueError("unknown probe data role")
        self.geometry, self.role = geometry, role
        self._rows, self._seen = [], {}

    @property
    def rows(self):
        return tuple(self._rows)

    def reserve_center(self, point):
        if self._rows or point.schema_id != self.geometry.identity:
            raise ValueError("center must be reserved before proposals")
        self._seen[point.identity] = -1

    def add(self, params, *, direction, reason=None):
        requested = canonical(params)
        index = len(self._rows)
        try:
            point = self.geometry.resolve(json.loads(requested))
        except ValueError as exc:
            row = ProbeRow(index, self.role, direction, requested, None, "INFEASIBLE", None, str(exc))
        else:
            duplicate = self._seen.get(point.identity)
            row = ProbeRow(index, self.role, direction, requested, point,
                "COLLISION" if duplicate is not None else "READY", duplicate, reason)
            self._seen.setdefault(point.identity, index)
        self._rows.append(row)
        return row

    def coverage(self):
        points = [r.point for r in self.rows if r.status == "READY"]
        counts = {name: len({p.params[name] for p in points if name in p.active_names})
            for name in {s.name for s in self.geometry.specs if s.variable and s.name not in dict(self.geometry.inactive)}}
        return dict(raw_rows=len(self.rows), unique_effective=len(points),
            collisions=sum(r.status == "COLLISION" for r in self.rows),
            infeasible=sum(r.status == "INFEASIBLE" for r in self.rows), axis_unique_values=counts,
            status="INSUFFICIENT_COVERAGE" if any(n < 2 for n in counts.values()) else "OBSERVED_AXIS_VARIATION",
            claim="budget/axis variation is not full-dimensional corner or robustness coverage")


def neutral_coverage(geometry, *, branches, seed):
    """Explicit branch quotas, Sobol numeric coverage; no outcome-dependent rejection."""
    if type(seed) is not int or not 0 <= seed < 2**32 or not branches:
        raise ValueError("registered seed and branch allocation required")
    ledger = ProposalLedger(geometry, role="exploration")
    for branch_index, (fixed, count) in enumerate(branches):
        if type(count) is not int or count < 1 or count & (count-1):
            raise ValueError("each Sobol branch quota must be a positive power of two")
        for name, value in fixed.items():
            spec = next((s for s in geometry.specs if s.name == name), None)
            if spec is None:
                raise ValueError("unknown fixed branch axis")
            spec.validate(value)
        cube = qmc.Sobol(len(geometry.specs), scramble=True, seed=(seed+branch_index) % 2**32,
            optimization=None).random_base2(int(math.log2(count)))
        for sample in cube:
            params = {}
            for s, u in zip(geometry.specs, sample):
                if s.name in dict(geometry.inactive) or not s.active(params):
                    continue
                if s.name in fixed:
                    value = fixed[s.name]
                elif s.fixed:
                    value = s.value
                elif s.choices:
                    value = s.choices[min(len(s.choices)-1, int(u*len(s.choices)))]
                elif not s.variable:
                    value = s.low
                else:
                    value = geometry.decode(s.name, float(u))
                params[s.name] = value
            if any(name not in params or params[name] != value for name, value in fixed.items()):
                raise ValueError("branch allocation contains an inactive/ignored override")
            ledger.add(params, direction=f"branch:{branch_index}")
    return ledger


@dataclass(frozen=True)
class SaltelliLayout:
    base_n: int
    dimensions: int
    second_order: bool
    rows: int
    stress_multiplier: int
    schema: str = "saltelli_layout_v1"

    @property
    def execution_cells(self):
        return self.rows*self.stress_multiplier


def saltelli_layout(base_n, dimensions, *, second_order=False, stress_multiplier=1):
    if any(type(v) is not int or v <= 0 for v in (base_n, dimensions, stress_multiplier)) or type(second_order) is not bool:
        raise ValueError("positive exact counts required")
    return SaltelliLayout(base_n, dimensions, second_order,
        base_n*(2*dimensions+2 if second_order else dimensions+2), stress_multiplier)


def design_identity(rows, *, method, seed, schema_id):
    return digest(dict(method=method, seed=seed, schema=schema_id,
        rows=[dict(raw=r.requested_json, status=r.status, direction=r.direction) for r in rows]))
