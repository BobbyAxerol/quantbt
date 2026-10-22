"""Synthetic shared diagnostics: no strategy, market download, optimizer or fit."""

from dataclasses import asdict
import numpy as np

from quantbt.diagnostics import (AccessPolicy, AccessWitness, AlphaDiagnostics,
    DiagnosticAccount, DiagnosticAdvice, DiagnosticContext, DiagnosticObservation,
    DiagnosticResearch, DiagnosticTrial, ExecutionEvidence)
from quantbt.diagnostics.evidence import FrozenBuffer
from quantbt.diagnostics.identity import digest


def example_inputs(count=128):
    day=86_400_000_000_000
    context=DiagnosticContext('synthetic-alpha','synthetic-market','synthetic-economics',
        'caller-declared-route',(('quality','synthetic_utility'),('risk','synthetic_risk')),
        'quality','maximize','reviewed_synthetic_panel',activity_definition='synthetic_entry_count')
    witness=AccessWitness('synthetic-prefix','synthetic',0,4*day,4*day+1)
    access=AccessPolicy('presearch',('synthetic',),('synthetic-prefix',),4*day+1,'diagnostic')
    owner=AlphaDiagnostics({'window':(1,count),'threshold':(0.,1.)},context=context,access=access)
    rows=tuple(DiagnosticObservation.from_params(geometry=owner.geometry,
        params={'window':i+1,'threshold':i/count},metrics={'quality':float(i)/count,'risk':0.1},
        evaluation_id=f'candidate-{i}',context_id=context.identity,witness=witness,
        source_ref=f'synthetic-result-{i}',activity_count=i%5) for i in range(count))
    tape=ExecutionEvidence.from_arrays('synthetic-account',witness,
        dict(timestamps=np.arange(4,dtype=np.int64)*day,equity=np.array([100.,110.,105.,100.]),
             positions=np.array([0.,1.,1.,0.]),fees=np.array([0.,.1,.1,.1])),
        source_ref='synthetic-actual-marks',backend='retained-fixture')
    account=DiagnosticAccount(rows[0].evaluation_id,digest(asdict(rows[0])),tape,100.,'USD',
        labels=FrozenBuffer.from_array('source-labels',np.array([0,0,1,1],dtype=np.int64)),
        label_witness=witness,label_source_ref='synthetic-label-source',
        label_names=((0,'synthetic-bull'),(1,'synthetic-bear')))
    research=DiagnosticResearch(context.identity,witness,'registered-synthetic-inputs',trials=tuple(
        DiagnosticTrial(str(i),i,'COMPLETE',row.evaluation_id,elapsed_seconds=.01)
        for i,row in enumerate(rows)),requested_trials=count,accounts=(account,))
    advice=(DiagnosticAdvice('sampler','tpe_legacy','Keep the registered comparator until a matched comparison exists.',
        ('geometry','coverage'),('matched sampler comparison',)),
        DiagnosticAdvice('selector','is_only_robust','Do not invent annual/local metrics from aggregate quality.',
        ('coverage',),('authorized local and environment evidence',)))
    return owner,rows,research,advice


def build_example_report(count=128):
    owner,rows,research,advice=example_inputs(count)
    return owner.analyze(rows,research=research,advice=advice)


if __name__=='__main__':
    print(build_example_report().to_markdown())
