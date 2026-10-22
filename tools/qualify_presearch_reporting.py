"""Local source/math and bounded cold-report proof, never financial execution."""

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

from quantbt.diagnostics import AlphaDiagnosticReport
from quantbt.mode5.dossier.records import Record
from examples.shared_presearch_researcher import example_inputs

ROOT=Path(__file__).resolve().parents[1]


def pin(path):
    return dict(path=str(path),bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest())


def qualify(baseline):
    preserved=[]
    def math_body(text):
        tree=ast.parse(text)
        tree.body=[node for node in tree.body if not isinstance(node,(ast.Import,ast.ImportFrom))]
        return ast.dump(tree,include_attributes=False)
    for name in ('attribution','manifests'):
        old=subprocess.check_output(['git','show',f'{baseline}:tools/mode5_environments/{name}.py'],cwd=ROOT,text=True)
        path=ROOT/f'src/quantbt/diagnostics/environments/{name}.py'
        if math_body(old)!=math_body(path.read_text()):
            raise ValueError('existing attribution/calendar mathematical body changed')
        preserved.append(pin(path))
    protected=('src/quantbt/endpoint.py','src/quantbt/walkforward.py','src/quantbt/core',
        'src/quantbt/optimization','src/quantbt/metrics','src/quantbt/backends','rust')
    changed=subprocess.check_output(['git','diff','--name-only',baseline,'--',*protected],cwd=ROOT,text=True).splitlines()
    if changed:
        raise ValueError('protected execution/metric/model source changed: '+repr(changed))
    from tools.meta_model_research.admission import verify_freeze
    frozen=verify_freeze()
    py_state,np_state=random.getstate(),np.random.get_state()
    measured=[]
    for count in (128,1024):
        owner,rows,research,advice=example_inputs(count)
        started=time.perf_counter()
        report=owner.analyze(rows,research=research,advice=advice)
        assembly=time.perf_counter()-started
        started=time.perf_counter(); payload=report.to_json(); json_time=time.perf_counter()-started
        started=time.perf_counter(); text=report.to_markdown(); markdown_time=time.perf_counter()-started
        restored=AlphaDiagnosticReport(Record.of(json.loads(payload)))
        assert restored.identity==report.identity and restored.to_markdown()==text
        for copied in (deepcopy(report),pickle.loads(pickle.dumps(report))):
            assert copied.to_json()==payload
        assert owner.analyze(rows,research=research,advice=advice).identity==report.identity
        assert 'synthetic-alpha' not in report.to_json(public=True)
        measured.append(dict(observations=count,assembly_seconds=assembly,json_seconds=json_time,
            markdown_seconds=markdown_time,json_bytes=len(payload.encode()),markdown_bytes=len(text.encode())))
    assert random.getstate()==py_state
    now=np.random.get_state()
    np.testing.assert_array_equal(now[1],np_state[1]); assert now[2:]==np_state[2:]
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    if peak>512:
        raise ValueError('registered reporting-process RSS cap exceeded')
    return dict(schema='quantbt.presearch_reporting_source_qualification.v1',status='PASS',
        baseline=baseline,math_bodies_preserved=preserved,protected_source_changes=changed,
        frozen_ridge=frozen,workloads=measured,peak_rss_mib=peak,financial_executions=0,
        source_pins=[pin(p) for p in sorted((ROOT/'src/quantbt/diagnostics').rglob('*.py'))]+
            [pin(Path(__file__)),pin(ROOT/'examples/shared_presearch_researcher.py')],
        optimizer_proposals=0,model_fits=0,global_rng_unchanged=True,
        limitations='Local deterministic source/readback proof, not installed-wheel, engine-speedup or economic promotion.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default='7c18ebb')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=qualify(args.baseline)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result,stream,sort_keys=True,allow_nan=False)
    print(json.dumps(result,sort_keys=True))
