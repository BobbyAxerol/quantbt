"""Matched cold rendering cost; no account execution, search or model fitting."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import random
import resource
import time


def measure(call, repeats):
    samples=[]
    for _ in range(repeats):
        start=time.perf_counter(); result=call(); samples.append(time.perf_counter()-start)
    ordered=sorted(samples)
    raw=result.encode() if isinstance(result,str) else json.dumps(result,sort_keys=True,allow_nan=False).encode()
    return dict(seconds=samples,median_seconds=ordered[len(ordered)//2],min_seconds=min(samples),
        max_seconds=max(samples),output_bytes=len(raw),output_sha256=sha256(raw).hexdigest())


def run(args):
    started=time.perf_counter()
    import numpy as np
    from quantbt.diagnostics import ResearchDecisionReport,AccessPolicy,AccessWitness
    from quantbt.mode5 import DecisionReport
    from quantbt.mode5.dossier.records import Record
    from quantbt import QuantBTEndpoint
    from quantbt.walkforward import WalkForwardEngine
    from quantbt.optimization.meta_selection.model import RidgeLearner
    import optuna
    imports=time.perf_counter()-started
    def forbidden(*a,**k):
        raise AssertionError('cold benchmark invoked execution/search/model fitting')
    QuantBTEndpoint.backtest=QuantBTEndpoint.simulate=forbidden
    WalkForwardEngine.run=WalkForwardEngine.optimize_params=forbidden
    RidgeLearner.fit=optuna.create_study=forbidden
    state=(random.getstate(),np.random.get_state())
    start=time.perf_counter()
    input_ref=None
    if args.input is None:
        from examples.shared_decision_reporting import build_example_report
        report=build_example_report(args.folds)
    else:
        raw=args.input.read_bytes()
        input_ref=dict(path=str(args.input.resolve()),bytes=len(raw),sha256=sha256(raw).hexdigest())
        value=json.loads(raw)
        if value.get('schema')=='quantbt.research_decision_report.v1':
            report=ResearchDecisionReport.from_json(raw.decode())
        else:
            original=DecisionReport.from_json(raw.decode())
            runtime=original.to_dict(private=True)['runtime']; scope=runtime['account_scope']
            ready=time.time_ns()
            witness=AccessWitness('reviewed-retained-source','diagnostic_development',
                scope['full_start_ns'],scope['full_stop_ns'],ready)
            access=AccessPolicy('reviewed-report-benchmark',('diagnostic_development',),
                (witness.manifest_id,),ready,'diagnostic')
            report=ResearchDecisionReport.mode5(original,access=access,witness=witness,
                source_ref=input_ref['sha256'],max_report_bytes=16*1024**2)
    assembly=time.perf_counter()-start
    methods=dict(public_summary=lambda:report.to_dict(),private_summary=lambda:report.to_dict(private=True),
        public_json=report.to_json,public_detail_json=lambda:report.to_json(detail=True),
        private_json=lambda:report.to_json(private=True),private_detail_json=lambda:report.to_json(private=True,detail=True),
        public_markdown=report.to_markdown,private_detail_markdown=lambda:report.to_markdown(private=True,detail=True))
    first={name:measure(call,1) for name,call in methods.items()}
    repeated={name:measure(call,args.repeats) for name,call in methods.items()}
    matched={}
    for private,detail in ((False,False),(False,True),(True,False),(True,True)):
        old=lambda:Record.of(report.to_dict(private=private,detail=detail)).payload
        new=lambda:report.to_json(private=private,detail=detail)
        assert old()==new()
        times={'original':[],'current':[]}
        for n in range(args.repeats):
            for key,call in ((('original',old),('current',new)) if n%2==0 else (('current',new),('original',old))):
                begin=time.perf_counter(); call(); times[key].append(time.perf_counter()-begin)
        medians={k:sorted(v)[len(v)//2] for k,v in times.items()}
        matched[f'private={private},detail={detail}']=dict(samples=times,medians=medians,
            original_over_current=medians['original']/medians['current'],byte_identical=True)
    assert random.getstate()==state[0]
    now=np.random.get_state(); np.testing.assert_array_equal(now[1],state[1][1]); assert now[2:]==state[1][2:]
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    assert peak<=512
    return dict(schema='quantbt.reporting.cold_cost.v1',status='PASS',input=input_ref,
        mode=report.to_dict()['mode'],synthetic_folds=args.folds if input_ref is None else None,
        imports_seconds=imports,assembly_seconds=assembly,first_call=first,repeated=repeated,
        repeats=args.repeats,matched_json=matched,peak_rss_mib=peak,global_rng_unchanged=True,
        new_finance_optimizer_fits=0,elapsed_seconds=time.perf_counter()-started,
        cost_scope='Fresh process imports/assembly, first call and repeated stateless rendering; five empirical samples are not a release p95 or end-to-end WFO speedup.',
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest())


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path)
    parser.add_argument('--folds',type=int,default=2,choices=(2,57))
    parser.add_argument('--repeats',type=int,default=5,choices=(5,))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(args)
    with args.output.open('x') as stream:
        json.dump(result,stream,sort_keys=True,allow_nan=False)
    print('PASS',result['mode'],result['synthetic_folds'],'peak MiB',result['peak_rss_mib'])
