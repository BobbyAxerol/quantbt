"""Frozen estimands and append-only research attempts, independent of alpha names."""
from dataclasses import asdict, dataclass
import json

from tools.mode5_diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_diagnostics.identity import canonical, digest


@dataclass(frozen=True)
class ComparisonScope:
    study_id: str
    revision: str
    level: str
    candidate_ids: tuple[str, ...]
    environment_ids: tuple[str, ...]
    cohort_id: str
    target_id: str
    economic_contract: str
    access: AccessPolicy

    def __post_init__(self):
        for name in ("study_id", "revision", "cohort_id", "target_id", "economic_contract"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError("complete versioned estimand identity required")
        if self.level not in {"selector_only", "sampler_only", "end_to_end"}:
            raise ValueError("comparison level must not conflate search and selection")
        for name in ("candidate_ids", "environment_ids"):
            values = tuple(getattr(self, name))
            object.__setattr__(self, name, values)
            if not values or len(set(values)) != len(values) or any(not isinstance(v,str) or not v for v in values):
                raise ValueError("nonempty distinct ordered roster required")
        if not isinstance(self.access, AccessPolicy) or self.access.purpose != "selection":
            raise ValueError("explicit development selection rights required")

    @property
    def identity(self):
        return digest(asdict(self))

    def require_panel(self, panel):
        if (tuple(c.candidate_id for c in panel.candidates) != self.candidate_ids
                or panel.reference.environment_ids != self.environment_ids
                or panel.access != self.access):
            raise ValueError("matched full candidate/environment/rights roster required")

    def compare_cohort(self, *, cohort_id, target_id):
        matched = cohort_id == self.cohort_id and target_id == self.target_id
        return dict(status="COMPARABLE" if matched else "INCOMPARABLE", same_cohort=cohort_id==self.cohort_id,
            same_target=target_id==self.target_id, decision_value_claim=False,
            reason=None if matched else "ablation changed scored cohort or prediction target")


@dataclass(frozen=True)
class SupportPolicy:
    minimum_days: int
    minimum_origins: int
    minimum_seeds: int
    minimum_campaigns: int
    minimum_fills: int
    version: str = "m508.claim_support.v1"

    def __post_init__(self):
        if self.version != "m508.claim_support.v1" or any(type(getattr(self,n)) is not int or getattr(self,n)<1
            for n in ("minimum_days","minimum_origins","minimum_seeds","minimum_campaigns","minimum_fills")):
            raise ValueError("preregistered positive support thresholds required")

    def check(self, *, days, origins, seeds, campaigns, fills):
        actual = dict(days=days, origins=origins, seeds=seeds, campaigns=campaigns, fills=fills)
        thresholds = dict(days=self.minimum_days, origins=self.minimum_origins, seeds=self.minimum_seeds,
                          campaigns=self.minimum_campaigns, fills=self.minimum_fills)
        if any(v is not None and (type(v) is not int or v<0) for v in actual.values()):
            raise ValueError("measured integral support or explicit unavailable required")
        reasons = tuple(n for n,v in actual.items() if v is None or v<thresholds[n])
        return dict(status="ADEQUATE_WITHIN_REGISTERED_SCOPE" if not reasons else "INSUFFICIENT_EVIDENCE",
                    actual=actual, required=thresholds, missing_or_insufficient=reasons,
                    universal_superiority=False)


@dataclass(frozen=True)
class HypothesisLedger:
    scope: ComparisonScope
    entries: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self,"entries",tuple(self.entries))
        if not isinstance(self.scope,ComparisonScope) or any(not isinstance(e,str) for e in self.entries):
            raise ValueError("typed scope and immutable canonical entries required")
        for entry in self.entries:
            row = json.loads(entry)
            if canonical(row)!=entry or row.get("scope")!=self.scope.identity:
                raise ValueError("ledger entries bind exact scope/revision")

    def register(self, hypothesis_id, recipes, witness):
        self.scope.access.require(witness)
        if not hypothesis_id or not recipes or len(set(recipes)) != len(recipes):
            raise ValueError("explicit unique comparison recipes required")
        if any(json.loads(e)["hypothesis_id"]==hypothesis_id for e in self.entries):
            raise ValueError("new recipe/radius/window requires a new hypothesis revision")
        row = dict(scope=self.scope.identity, hypothesis_id=hypothesis_id, state="REGISTERED",
                   recipes=tuple(recipes), witness=witness.identity)
        return HypothesisLedger(self.scope,self.entries+(canonical(row),))

    def observe(self,hypothesis_id,*,outcome,evidence_refs):
        records = [json.loads(e) for e in self.entries if json.loads(e)["hypothesis_id"]==hypothesis_id]
        if len(records)!=1 or records[0]["state"]!="REGISTERED" or not evidence_refs:
            raise ValueError("outcome requires a single earlier registration and evidence")
        if outcome not in {"POSITIVE_WITHIN_SCOPE","NEGATIVE_WITHIN_SCOPE","INCONCLUSIVE","NOT_EVALUABLE"}:
            raise ValueError("explicit scientific outcome required")
        row = dict(scope=self.scope.identity,hypothesis_id=hypothesis_id,state="OBSERVED",
                   outcome=outcome,evidence_refs=tuple(evidence_refs))
        return HypothesisLedger(self.scope,self.entries+(canonical(row),))

    def revise(self,new_scope,*,hypothesis_id,recipes,witness,parent_reason):
        if (new_scope.study_id!=self.scope.study_id or new_scope.revision==self.scope.revision
                or not parent_reason or witness.role not in {"diagnostic_development","DEVELOPMENT_REVIEWED"}):
            raise ValueError("new revision and reviewed-development reclassification required")
        child = HypothesisLedger(new_scope).register(hypothesis_id,recipes,witness)
        return dict(parent_identity=digest(self.entries), parent_entries=self.entries,
                    child=child, reason=parent_reason, contamination="REVIEWED_DEVELOPMENT")
