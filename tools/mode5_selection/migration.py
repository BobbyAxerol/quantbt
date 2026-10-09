"""Append-only objective versions; reanalysis never rewrites old study observations."""
from dataclasses import asdict, dataclass
import math

from tools.mode5_diagnostics.identity import digest
from .objectives import evaluate


@dataclass(frozen=True)
class Observation:
    candidate_id: str
    score: float
    component_hash: str

    def __post_init__(self):
        if not self.candidate_id or not self.component_hash or not math.isfinite(self.score):
            raise ValueError("finite completed observation with component identity required")


@dataclass(frozen=True)
class StageLedger:
    plan_identity: str
    observations: tuple[Observation, ...] = ()
    parent_ledger: str | None = None

    def __post_init__(self):
        if not self.plan_identity:
            raise ValueError("frozen objective stage identity required")
        object.__setattr__(self, "observations", tuple(self.observations))
        if len({o.candidate_id for o in self.observations}) != len(self.observations):
            raise ValueError("observations are append-only; no duplicate/update")

    @property
    def identity(self):
        return digest(asdict(self))

    def append(self, plan, row):
        if plan.identity != self.plan_identity:
            raise ValueError("moving objective/reference blocked; rescore the full stage into a revision")
        if (row.get("plan_identity") != plan.identity or row.get("formula_identity") != plan.formula.identity
                or row.get("reference_identity") != plan.reference_identity):
            raise ValueError("observation components belong to a different formula/reference/plan")
        if not row["eligible"] or row["score"] is None:
            raise ValueError("only completed admissible observations can be sent to the study")
        observation = Observation(row["candidate_id"], row["score"], digest(row))
        return StageLedger(self.plan_identity, (*self.observations, observation), self.parent_ledger)


def rescore_revision(old_ledger, panel, new_plan, *, local_evidence=()):
    if new_plan.identity == old_ledger.plan_identity:
        raise ValueError("reanalysis requires a distinct registered plan/reference/formula revision")
    if set(o.candidate_id for o in old_ledger.observations) != {c.candidate_id for c in panel.candidates}:
        raise ValueError("rescore all comparable completed candidates, not only previous winners")
    rows = evaluate(panel, new_plan, local_evidence=local_evidence)
    out = StageLedger(new_plan.identity, parent_ledger=old_ledger.identity)
    for row in rows:
        out = out.append(new_plan, row)
    return out
