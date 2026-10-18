"""Project original typed decisions/observations without replay or prediction."""

from dataclasses import asdict

from quantbt.optimization.meta_selection.common import digest, wire

from .effects import opportunity, raw_effect


def _observation(observation):
    if observation is None:
        return dict(status='MISSING_EXECUTION',raw_sharpe=None,output_ref=None,identity=None)
    return dict(status=observation.status.value,raw_sharpe=observation.raw_sharpe,
        output_ref=observation.output_ref,identity=digest(observation),sample_count=observation.sample_count,
        sample_std=observation.sample_std,activity_count=observation.activity_count,
        initial_capital=observation.initial_capital,initial_mark_equity=observation.initial_mark_equity,
        metric_contract_id=observation.metric_contract_id,economics_id=observation.economics_id,
        window_start=observation.window_start.isoformat(),window_end=observation.window_end.isoformat(),
        input_frontier=observation.input_frontier.isoformat(),input_signature=observation.input_signature,
        verification=observation.verification)


def snapshot(evidence):
    revision,decision=evidence.revision,evidence.decision
    task=revision.task
    byid={c.evaluation_id:c for c in task.candidates}
    outcomes={o.evaluation_id:o.observation for o in revision.outcomes}
    supplements={m.evaluation_id:m for m in evidence.metrics}
    anchor=task.anchor_candidate_evaluation_id
    ids=dict(native=anchor,proposed=decision.proposed_evaluation_id if decision else None,
        applied=decision.actual_evaluation_id if decision else anchor)
    predictions={p['evaluation_id']:wire(p) for p in decision.predictions} if decision else {}
    model_ready=decision is not None and decision.status=='META_MODEL_PROPOSAL'
    acquired=[]
    if model_ready:
        for row in revision.training_rows:
            p=predictions.get(row.candidate_evaluation_id)
            if p and p.get('yhat') is not None:
                acquired.append(dict(evaluation_id=row.candidate_evaluation_id,original_origin_weight=row.origin_weight,
                    actual_y=row.y,actual_q=row.q,yhat=p['yhat'],qhat=p['qhat']))
    policies={}
    for policy,eid in ids.items():
        candidate=byid.get(eid)
        obs=[task.anchor.observation,candidate.observation if candidate else None,
             outcomes.get(anchor),outcomes.get(eid)]
        names=('anchor_is','selected_is','anchor_forward','selected_forward')
        operands={k:_observation(v) for k,v in zip(names,obs)}
        valid=all(v is not None and v.status.value=='VALID' for v in obs)
        effect=raw_effect(*(v.raw_sharpe for v in obs)) if valid else None
        if effect is not None:
            effect.update(anchor_decay=effect['anchor_is']-effect['anchor_forward'],
                          selected_decay=effect['selected_is']-effect['selected_forward'])
        elif candidate is not None:
            ia,iw,oa,ow=(v.raw_sharpe if v is not None and v.status.value=='VALID' else None for v in obs)
            effect=dict(R=None,Q=ow-oa if ow is not None and oa is not None else None,
                IS_contribution=ia-iw if ia is not None and iw is not None else None,
                anchor_decay=ia-oa if ia is not None and oa is not None else None,
                selected_decay=iw-ow if iw is not None and ow is not None else None)
        supplement=supplements.get(eid)
        guard_floor=-decision.guard['epsilon'] if decision and 'epsilon' in decision.guard else None
        policies[policy]=dict(evaluation_id=eid,candidate_id=candidate.candidate_id if candidate else None,
            params=wire(candidate.effective_params) if candidate else None,
            params_identity=digest(candidate.effective_params) if candidate else None,
            objective=candidate.objective if candidate else None,
            same_id=eid==anchor if eid else None,
            same_effective=dict(candidate.effective_params)==dict(task.anchor.effective_params) if candidate else None,
            measurement_status='VALID' if valid else 'MISSING_OR_UNDEFINED',
            missing_operands={k:v['status'] for k,v in operands.items() if v['status']!='VALID'},
            observations=operands,effect=effect,prediction=predictions.get(eid),
            guard_floor=guard_floor,
            extra_metrics=dict(values=supplement.values.data,units=supplement.units.data,
                source_ref=supplement.source_ref,observation_identity=supplement.observation_identity)
                if supplement else None,
            opportunity=opportunity(revision,eid,tuple(predictions.values()),floor=guard_floor)
                if guard_floor is not None and eid else None)
    return dict(fold_id=evidence.fold_id,task_id=task.task_id,revision_id=revision.revision_id,
        source_ref=evidence.source_ref,witness=asdict(evidence.witness),
        origin=task.origin.isoformat(),is_start=task.is_start.isoformat(),is_end=task.is_end.isoformat(),
        forward_start=task.forward_start.isoformat(),forward_end=task.forward_end.isoformat(),
        start_ns=int(task.forward_start.value),stop_ns=int(task.forward_end.value)+1,
        duration_days=(task.forward_end.value-task.forward_start.value+1)/86_400_000_000_000,
        decision_clock=dict(cutoff=task.data_cutoff.isoformat(),sealed=task.decision_sealed_at.isoformat(),
            first_forward_action=task.first_forward_action_at.isoformat(),clock_mode=task.clock_mode,
            outcome_available=revision.revision_available_at.isoformat()),
        decision_id=decision.decision_id if decision else None,
        model_ready=model_ready,model_status=decision.status if decision else 'META_DISABLED',
        activation=decision.mode if decision else 'off',model_id=decision.model_id if decision else None,
        snapshot_id=decision.training_snapshot_id if decision else None,
        fit_completed_at=decision.fit_completed_at.isoformat() if decision and decision.fit_completed_at is not None else None,
        raw_best_evaluation_id=decision.raw_best_evaluation_id if decision else None,
        model_support=evidence.model_support.data if evidence.model_support else None,
        tie_set=list(decision.tie_set) if decision else None,
        ranked_ids=list(decision.ranked_ids) if decision else None,
        guard=wire(decision.guard) if decision else None,
        pool=dict(eligible_candidates=len(task.candidates),base_label_members=len(revision.panel.base_members),
            union_label_members=len(revision.panel.members),forward_statuses={
                status:sum(o.observation.status.value==status for o in revision.outcomes)
                for status in sorted({o.observation.status.value for o in revision.outcomes})},
            original_sampling_provenance=wire(task.sampling_provenance)),
        state_labels=list(evidence.state_labels),
        execution_comparison=evidence.execution_comparison.data if evidence.execution_comparison else None,
        acquired_predictions=acquired,
        policies=policies)
