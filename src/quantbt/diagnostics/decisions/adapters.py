"""Read original public WFO metadata; never restore an unverified JSON history."""

from dataclasses import replace

from quantbt.mode5.dossier.records import Record
from quantbt.optimization.meta_selection.history import SealedTaskRevision
from quantbt.optimization.meta_selection.records import MetaTask
from quantbt.optimization.meta_selection.selection import MetaSelectionDecision

from ..access import AccessWitness
from .contracts import FoldDecisionEvidence,FoldSlot


def from_walk_forward(metadata,*,access,source_ref,role,**options):
    from .report import ResearchDecisionReport
    if (metadata.get('optimization_mode')!='mode_4_is_only_robust'
            or metadata.get('optimization_schedule')!='per_fold_causal'):
        raise ValueError('this reader certifies Mode4/per_fold_causal only; it does not activate other modes')
    meta=metadata.get('meta_selection')
    if (not isinstance(meta,dict) or meta.get('schema')!='qms-public-run-v1'
            or meta.get('current_outer_oos_used_for_selection') is not False):
        raise ValueError('original causal public meta metadata required')
    tasks=meta.get('tasks',())
    records=meta.get('records',())
    revisions=meta.get('observed_revisions',())
    if (not tasks or any(not isinstance(t,MetaTask) for t in tasks)
            or any(not isinstance(r,SealedTaskRevision) for r in revisions)):
        raise ValueError('typed original tasks/revisions required; use the existing witnessed persistence decoder for stored JSON')
    if not revisions:
        raise ValueError('no observed revisions: R/Q unavailable; enable an approved observer or supply retained original records, never replay from reporting')
    if len(records)!=len(tasks) or len({t.task_id for t in tasks})!=len(tasks):
        raise ValueError('original task/decision roster mismatch')
    bytask={r.task.task_id:r for r in revisions}
    if len(bytask)!=len(revisions) or not set(bytask)<={t.task_id for t in tasks}:
        raise ValueError('ambiguous revision/correction or unknown task; select exact reviewed revisions first')
    activation=meta.get('config',{}).get('mode')
    if activation not in {'active','shadow'}:
        raise ValueError('original active/shadow activation must be explicit')
    rows=[]; roster=[]
    for task,record in zip(tasks,records):
        if (record.get('task_id')!=task.task_id or record.get('current_outer_oos_used_for_selection') is not False
                or record.get('native_optimization_mode')!='mode_4_is_only_robust'):
            raise ValueError('sidecar belongs to another task, mode or information scope')
        fold_id=str(record['fold_id'])
        roster.append(FoldSlot(fold_id,int(task.forward_start.value),int(task.forward_end.value)+1))
        revision=bytask.get(task.task_id)
        if revision is None:
            continue
        if revision.task!=task:
            raise ValueError('observed revision differs from original decision task')
        proposal=record['proposal']
        proposal=proposal if isinstance(proposal,MetaSelectionDecision) else MetaSelectionDecision(**proposal)
        actual=record['selected_evaluation_id']
        decision=replace(proposal,mode=activation,actual_evaluation_id=actual)
        if record.get('selected_params')!=dict(next(c for c in task.candidates if c.evaluation_id==actual).effective_params):
            raise ValueError('recorded applied params differ from original selected candidate')
        witness=AccessWitness(task.corpus_id,role,int(task.is_start.value),int(task.forward_end.value)+1,
            int(revision.revision_available_at.value))
        rows.append(FoldDecisionEvidence(fold_id,revision,decision,witness,source_ref+'#fold/'+fold_id,
            model_support=Record.of(dict(matured_origins=record.get('matured_origins'),
                training_snapshot_id=record.get('training_snapshot_id'),source_ref=source_ref))))
    return ResearchDecisionReport.mode4(rows,roster=roster,access=access,**options)
