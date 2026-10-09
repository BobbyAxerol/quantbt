"""Dossier authority is advisory until separate whole-procedure qualification."""
from dataclasses import asdict, dataclass

from tools.mode5_diagnostics.access import AccessWitness
from tools.mode5_diagnostics.identity import digest
from .contracts import nonempty


@dataclass(frozen=True)
class AdvisoryDossier:
    version: str
    dossier_id: str
    context_id: str
    evidence_refs: tuple[str, ...]
    ranked_recipes: tuple[tuple[str, str], ...]
    witness: AccessWitness
    routing_evidence_status: str = "ADVISORY_ONLY"

    def __post_init__(self):
        if self.version != "mode5.advisory.v1" or self.routing_evidence_status != "ADVISORY_ONLY":
            raise ValueError("V1 dossier does not authorize automatic deployment/routing")
        for name in ("dossier_id", "context_id"):
            nonempty(getattr(self, name))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "ranked_recipes", tuple(tuple(row) for row in self.ranked_recipes))
        if not self.evidence_refs or not self.ranked_recipes or len(set(self.ranked_recipes)) != len(self.ranked_recipes):
            raise ValueError("measured evidence and distinct ranked recipe IDs required")
        for ref in self.evidence_refs:
            nonempty(ref)
        for selector, formula_identity in self.ranked_recipes:
            if selector not in {"full_dro_cvar", "full_sam_basin", "full_pareto_chebyshev"}:
                raise ValueError("dossier shortlist must use an explicit nonadaptive selector")
            nonempty(formula_identity)
        if not isinstance(self.witness, AccessWitness):
            raise TypeError("dossier readiness/access witness required")

    @property
    def identity(self):
        return digest(asdict(self))


def resolve_advisory(panel, plan, dossier, *, researcher_choice, reason):
    if not isinstance(dossier, AdvisoryDossier) or dossier.context_id != panel.context_id:
        raise ValueError("matching versioned dossier/economics/schema/scope required")
    panel.access.require(dossier.witness)
    audit = dict(dossier_identity=dossier.identity, routing_evidence_status=dossier.routing_evidence_status,
        ranked_recipes=dossier.ranked_recipes, evidence_refs=dossier.evidence_refs,
        researcher_choice=researcher_choice, override_reason=reason, automatic_routing=False)
    if researcher_choice is None:
        if reason is not None:
            raise ValueError("override reason without a researcher decision")
        return None, audit
    nonempty(reason)
    chosen = (researcher_choice, plan.formula.identity)
    if chosen not in dossier.ranked_recipes:
        raise ValueError("unqualified recipe override needs a new registered dossier/plan")
    audit["overrode_first_advice"] = chosen != dossier.ranked_recipes[0]
    return researcher_choice, audit
