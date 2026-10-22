"""Cold source/math/cost qualification, not a financial or installed-package gate."""

import argparse
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import pickle
import random
import resource
import subprocess
import time

import numpy as np

from examples.shared_decision_reporting import example_inputs
from quantbt.diagnostics import ResearchDecisionReport

ROOT=Path(__file__).resolve().parents[1]


def pin(path):
    return dict(path=str(path),bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest())


def qualify():
    baseline='017b421'
    previous=subprocess.check_output(['git','show',baseline+':tools/meta_model_research/decision_analysis.py'],cwd=ROOT,text=True)
    current=(ROOT/'src/quantbt/diagnostics/decisions/effects.py').read_text()
    def bodies(text):
        return {node.name:ast.dump(node,include_attributes=False) for node in ast.parse(text).body if isinstance(node,ast.FunctionDef)}
    old,new=bodies(previous),bodies(current)
    assert all(old[name]==new[name] for name in ('raw_effect','worst_fraction','opportunity'))
    paths=('src/quantbt/endpoint.py','src/quantbt/walkforward.py','src/quantbt/core','src/quantbt/optimization',
        'src/quantbt/metrics','src/quantbt/backends','rust','src/quantbt/mode5/decision_report.py')
    changes=subprocess.check_output(['git','diff','--name-only',baseline,'--',*paths],cwd=ROOT,text=True).splitlines()
    assert not changes
    from tools.meta_model_research.admission import verify_freeze
    frozen=verify_freeze()
    rng=(random.getstate(),np.random.get_state())
    measured=[]
    for count in (2,57):
        inputs=example_inputs(count)
        before=time.perf_counter()
        report=ResearchDecisionReport.mode4(inputs[0],roster=inputs[1],access=inputs[2],cohorts=inputs[3])
        assembly=time.perf_counter()-before
        results={}
        for name,call in dict(private_json=lambda:report.to_json(private=True,detail=True),
            public_json=report.to_json,private_detail_markdown=lambda:report.to_markdown(private=True,detail=True),
            public_markdown=report.to_markdown).items():
            begin=time.perf_counter(); output=call()
            results[name]=dict(seconds=time.perf_counter()-begin,bytes=len(output.encode()))
        for clone in (deepcopy(report),pickle.loads(pickle.dumps(report)),
                      ResearchDecisionReport.from_json(report.to_json(private=True,detail=True))):
            assert clone.identity==report.identity
        assert 'lookback' not in report.to_json(detail=True)
        measured.append(dict(folds=count,assembly_seconds=assembly,exports=results))
    assert random.getstate()==rng[0]
    after=np.random.get_state()
    np.testing.assert_array_equal(after[1],rng[1][1]); assert after[2:]==rng[1][2:]
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    assert peak<=512
    return dict(schema='quantbt.decision_reporting.source_proof.v1',status='PASS',
        baseline=baseline,math_bodies_preserved=['raw_effect','worst_fraction','opportunity'],
        protected_source_changes=changes,frozen_ridge=frozen,workloads=measured,peak_rss_mib=peak,
        source_pins=[pin(p) for p in sorted((ROOT/'src/quantbt/diagnostics').rglob('*.py'))]+
            [pin(Path(__file__)),pin(ROOT/'examples/shared_decision_reporting.py')],
        finance=0,optimizer=0,model_fits=0,global_rng_unchanged=True,
        cost_scope='Single observations, no percentile or comparative speedup claim; source-only, not installed or economic proof.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); result=qualify()
    with args.output.open('x') as stream:
        json.dump(result,stream,sort_keys=True,allow_nan=False)
    print('PASS source/math/RNG/cold cost',result['workloads'],result['peak_rss_mib'])
