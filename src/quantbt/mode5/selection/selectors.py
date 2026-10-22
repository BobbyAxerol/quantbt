"""Four pure research slots with explicit gates, components and incumbent audit."""
from dataclasses import replace

from quantbt.mode5.diagnostics.identity import digest
from .advisory import resolve_advisory
from .contracts import FORMULAS, decision
from .objectives import evaluate
from .pareto import reduce_pareto


def select(panel, plan, *, local_evidence=(), pareto_preference=None, dossier=None,
           researcher_choice=None, override_reason=None):
    plan.require(panel)
    resolved, advisory = plan.requested_selector, None
    if resolved == "full_alpha_adaptive_invariant":
        resolved, advisory = resolve_advisory(panel, plan, dossier,
            researcher_choice=researcher_choice, reason=override_reason)
        if resolved is None:
            return decision(panel, plan, dict(status="NO_SELECTION", reason="RESEARCHER_DECISION_REQUIRED",
                chosen_candidate=None, resolved_selector=None, advisory=advisory, component_rows=(),
                pre_incumbent_candidate=None, post_incumbent_candidate=None))
        # Validate the same frozen formula against the explicitly chosen slot.
        replace(plan, requested_selector=resolved)
    elif dossier is not None or researcher_choice is not None or override_reason is not None:
        raise ValueError("advisory inputs only belong to the adaptive slot")
    family = FORMULAS[plan.formula.version][0]
    front = ()
    if family == "pareto":
        if pareto_preference is None or local_evidence:
            raise ValueError("explicit Pareto preference and no unused local inputs required")
        rows, front = reduce_pareto(panel, plan, pareto_preference)
    else:
        if pareto_preference is not None:
            raise ValueError("unused Pareto preference would obscure objective identity")
        rows = evaluate(panel, plan, local_evidence=local_evidence)
    eligible = [r for r in rows if r["eligible"] and r["score"] is not None
                and (family != "pareto" or r["pareto_front"])]
    best = min(eligible, key=lambda r: (-r["score"], r["candidate_id"])) if eligible else None
    chosen, incumbent_guard = best, "NO_INCUMBENT"
    incumbent = next((r for r in rows if r["candidate_id"] == plan.incumbent_id), None)
    if incumbent is not None:
        incumbent_guard = "INCUMBENT_INELIGIBLE"
        if incumbent["eligible"] and incumbent["score"] is not None:
            incumbent_guard = "CHALLENGER_ACCEPTED"
            if best is None or best["score"]-incumbent["score"] < plan.minimum_improvement:
                chosen, incumbent_guard = incumbent, "INCUMBENT_RETAINED_BY_DECLARED_MARGIN"
    metadata = dict(status="SELECTED" if chosen else "NO_SELECTION",
        reason=None if chosen else "NO_SUPPORTED_CONFIGURATION", resolved_selector=resolved,
        chosen_candidate=chosen["candidate_id"] if chosen else None,
        chosen_params_digest=chosen["params_digest"] if chosen else None,
        compared_candidate_ids=tuple(c.candidate_id for c in panel.candidates), component_rows=rows,
        component_hash=digest(rows), pareto_candidate_ids=front,
        front_metric_claim="not_selected_point_performance" if family == "pareto" else None,
        selector_algorithm="pareto_post_selection_chebyshev" if family == "pareto" else plan.formula.version,
        pre_incumbent_candidate=best["candidate_id"] if best else None,
        post_incumbent_candidate=chosen["candidate_id"] if chosen else None,
        incumbent_guard=incumbent_guard, minimum_improvement=plan.minimum_improvement, advisory=advisory,
        interpretation="finite declared development panel; not future edge or deployment authority")
    return decision(panel, plan, metadata, local_refs=tuple(row.identity for row in local_evidence),
                    preference_ref=pareto_preference.identity if pareto_preference else "none")
