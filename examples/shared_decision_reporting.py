"""Synthetic original-record reporting, without accounts, optimization or fitting."""

import pandas as pd

from quantbt.diagnostics import (AccessPolicy,AccessWitness,FoldDecisionEvidence,FoldSlot,
    ReportCohort,ResearchDecisionReport)
from quantbt.optimization.meta_selection import (CandidateISRecord,CandidateRoleRef,
    CompatibilityFamily,MetaTask,MetricObservation,OutcomeStatus,CandidateForwardRecord)
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.history import SealedTaskRevision
from quantbt.optimization.meta_selection.panel import freeze_panel
from quantbt.optimization.meta_selection.selection import MetaSelectionDecision


def example_inputs(count=12):
    """Illustrative saved predictions, not a claim that a model was fitted."""
    schema=DescriptorSchema({'lookback':(8,16,8)})
    family=CompatibilityFamily('synthetic-strategy',schema.space.identity,schema.schema_id,
        'synthetic-market','1h','synthetic-rolling-quarterly','synthetic-raw-sharpe',
        'synthetic-economics','original-synthetic-observation','mode4-native-anchor',
        'retained-synthetic-pool','independent-reset-diagnostic')
    folds=[]; slots=[]
    for number in range(count):
        start=pd.Timestamp('2021-01-01',tz='UTC')+pd.DateOffset(months=number*3)
        end=start+pd.DateOffset(months=3)-pd.Timedelta(hours=1)
        cutoff=start-pd.Timedelta(hours=1)
        train_start=start-pd.Timedelta(days=365)
        seal=cutoff+pd.Timedelta(seconds=10)
        observations=tuple(MetricObservation(OutcomeStatus.VALID,quality,12,365,.1,
            family.metric_contract_id,family.economics_id,train_start,cutoff,cutoff,
            20_000.,20_000.,f'is-{number}-{i}',f'input-is-{number}','original_result')
            for i,quality in enumerate((2.,1.)))
        candidates=tuple(CandidateISRecord(f'evaluation-{number}-{i}',f'candidate-{number}-{i}',i,
            {'lookback':lookback},{'lookback':lookback},quality,observations[i],seal,{})
            for i,(lookback,quality) in enumerate(((8,2.),(16,1.))))
        anchor,winner=candidates
        task=MetaTask(family,'synthetic-corpus','synthetic-run',cutoff,train_start,cutoff,start,end,
            cutoff,731,candidates,anchor.evaluation_id,(CandidateRoleRef('native_anchor','synthetic',anchor.evaluation_id),),
            seal,seal,seal,start,end+pd.Timedelta(hours=1),'historical_replay','synthetic-forward','synthetic-research',{})
        predictions=tuple(dict(evaluation_id=c.evaluation_id,candidate_id=c.candidate_id,
            raw_is=c.observation.raw_sharpe,yhat=0. if i==0 else -1.,qhat=0.,distance=float(i),eligible=True,
            exclusion=None) for i,c in enumerate(candidates))
        decision=MetaSelectionDecision(task.task_id,anchor.evaluation_id,winner.evaluation_id,winner.evaluation_id,
            dict(winner.effective_params),anchor.evaluation_id,'synthetic-not-fitted-model','synthetic-history',
            cutoff,seal,seal,seal,'historical_replay','active','META_MODEL_PROPOSAL',predictions,
            (winner.evaluation_id,),(),dict(epsilon=.1,tie_tolerance=1e-10),{})
        panel=freeze_panel(task,schema,sealed_at=seal)
        available=end+pd.Timedelta(hours=1)
        outcomes=tuple(CandidateForwardRecord(task.task_id,c.evaluation_id,
            MetricObservation(OutcomeStatus.VALID,quality,8,90,.1,family.metric_contract_id,family.economics_id,
                start,end,end,20_000.,20_000.,f'forward-{number}-{i}',f'input-forward-{number}','original_result'),
            available,3600) for i,(c,quality) in enumerate(zip(candidates,(.5,.3+number*.03))))
        revision=SealedTaskRevision(task,panel,outcomes,available)
        witness=AccessWitness(task.corpus_id,'synthetic',int(train_start.value),int(end.value)+1,int(available.value))
        fold_id=str(number)
        folds.append(FoldDecisionEvidence(fold_id,revision,decision,witness,f'synthetic-record-{number}'))
        slots.append(FoldSlot(fold_id,int(start.value),int(end.value)+1))
    policy=AccessPolicy('synthetic-report-rights',('synthetic',),('synthetic-corpus',),max(f.witness.ready_ns for f in folds),'diagnostic')
    cohorts=(ReportCohort('declared-evaluation',tuple(str(i) for i in range(count//2,count)),'synthetic-registration'),)
    return folds,slots,policy,cohorts


def build_example_report(count=12):
    folds,slots,policy,cohorts=example_inputs(count)
    return ResearchDecisionReport.mode4(folds,roster=slots,access=policy,cohorts=cohorts)


if __name__=='__main__':
    print(build_example_report().to_markdown())
