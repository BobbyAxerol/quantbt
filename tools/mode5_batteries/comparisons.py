"""Reuse canonical selection; leave-out diagnostics do not rerun any sampler."""
from dataclasses import replace

from tools.mode5_diagnostics.identity import AnalysisKey, digest
from tools.mode5_selection.contracts import Panel
from tools.mode5_selection.pareto import nondominated
from tools.mode5_selection.selectors import select
from tools.mode5_statistics.tails import FrozenReference


def compare_selectors(scope,panel,requests):
    if scope.level!="selector_only" or not requests:
        raise ValueError("explicit selector-only requests required")
    scope.require_panel(panel)
    decisions = []
    for plan, kwargs in requests:
        decisions.append(select(panel,plan,**kwargs).metadata)
    return dict(scope=scope.identity, level=scope.level, panel_identity=panel.identity,
                all_candidate_ids=scope.candidate_ids, decisions=tuple(decisions),
                sampler_advantage_claim=False, end_to_end_advantage_claim=False)


def fixed_panel_leave_out(panel,plan):
    if len(panel.reference.environment_ids)<2 or plan.formula.version not in {
            "environment_floor_mean_v1","environment_lower_tail_v2","finite_panel_minimax_regret_v1"}:
        raise ValueError("environment-family leave-out needs at least two views")
    plan.require(panel)
    outputs=[]
    for omitted in range(len(panel.reference.environment_ids)):
        keep=tuple(i for i in range(len(panel.reference.environment_ids)) if i!=omitted)
        ref=FrozenReference(panel.reference.reference_id+f"-leave-{omitted}",
            tuple(panel.reference.environment_ids[i] for i in keep),tuple(panel.reference.values[i] for i in keep),
            tuple(panel.reference.weights[i] for i in keep),panel.channel.identity,panel.reference.revision+"-leave-out")
        candidates=tuple(replace(c,metrics=tuple(c.metrics[i] for i in keep),witnesses=tuple(c.witnesses[i] for i in keep),
            analyses=tuple(replace(c.analyses[i],normalization_reference=ref.identity) for i in keep)) for c in panel.candidates)
        child=Panel(panel.context_id,panel.revision+f"-leave-{omitted}",panel.channel,ref,candidates,
                    panel.access,panel.generation,panel.generation_evidence)
        child_plan=replace(plan,plan_id=plan.plan_id+f"-leave-{omitted}",reference_identity=ref.identity)
        chosen=select(child,child_plan).metadata["chosen_candidate"]
        source=next((c for c in panel.candidates if c.candidate_id==chosen),None)
        held=None if source is None else source.metrics[omitted].to_metadata()
        outputs.append(dict(omitted_environment=panel.reference.environment_ids[omitted],chosen_candidate=chosen,
            held_metric=held,refit_sampler=False,claim="fixed-panel exploratory leave-out; not unseen OOS"))
    return tuple(outputs)


def same_front(values, candidate_ids, selected_ids, *, directions):
    if len(values)!=len(candidate_ids) or len(set(candidate_ids))!=len(candidate_ids):
        raise ValueError("distinct complete finite panel required")
    front=tuple(sorted(candidate_ids[i] for i in nondominated(values,directions)))
    if any(s not in candidate_ids for s in selected_ids):
        raise ValueError("selected point outside actual panel")
    return dict(front_ids=front,front_identity=digest(front),selected_ids=tuple(selected_ids),
                hypervolume_discriminates_selectors=False,hypervolume_value=None,
                reason="same declared front/reference has the same hypervolume; compare actual compromise outcomes")
