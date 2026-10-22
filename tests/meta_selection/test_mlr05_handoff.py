"""Final cold-report reproducibility and fresh optional-dependency absence."""

from copy import deepcopy
import json
import os
import random
import subprocess
import sys

import numpy as np
import pytest

from tools.meta_model_research.admission import PUBLIC, ROOT, read
from tools.meta_model_research.handoff_reporting import render_handoff


def inputs():
    return tuple(read(PUBLIC / name) for name in (
        'ml03_development_results.json','ml03_closure.json','ml04_closure.json'))


def test_final_report_regenerates_exactly_without_rng_or_financial_execution(monkeypatch):
    import tools.meta_model_research.families as families
    from quantbt import QuantBTEndpoint

    def forbidden(*args, **kwargs):
        raise AssertionError('cold reports cannot fit or execute')

    monkeypatch.setattr(families, 'fit_family', forbidden)
    monkeypatch.setattr(QuantBTEndpoint, 'backtest', forbidden)
    data = inputs()
    old = deepcopy(data)
    py_state, np_state = random.getstate(), np.random.get_state()
    text = render_handoff(*data)
    assert data == old
    assert random.getstate() == py_state
    after = np.random.get_state()
    assert np_state[0] == after[0] and np_state[2:] == after[2:]
    np.testing.assert_array_equal(np_state[1], after[1])
    assert text == (ROOT/'docs/meta_selection/M4_ML_05_FINAL_DECISION.md').read_text()
    charge = data[1]['cumulative_research_numeric_fit_charge'] + data[2]['numeric_reference_qualification_fit_charge']
    assert f'**{charge}**' in text
    assert '**COMPLETE_LOCAL_REGISTERED_RESEARCH / KEEP_FROZEN_V1.**' in text


def test_undefined_summary_values_stay_undefined_and_are_not_zero():
    data = list(inputs())
    m = data[0]['summaries']['base']['macro']['X2']
    m['served_loss']['mean'] = None
    m['paired_vs_P0']['relative_mse_change_percent_from_matched_means'] = None
    text = render_handoff(*data)
    assert '| X2: CPU trees depth 2 | undefined | undefined |' in text


@pytest.mark.parametrize('index,field,value',[
    (0,'schema','unknown'),(0,'required_rows',479),
    (1,'schema','stale'),(1,'decision','PROMOTE'),(1,'no_nominees',False),
    (2,'schema','stale'),(2,'decision','PROMOTE'),(2,'public_activation',True),
])
def test_unqualified_or_changed_disposition_cannot_be_rendered_as_keep(index,field,value):
    data = list(inputs())
    data[index][field] = value
    with pytest.raises(ValueError,match='unqualified'):
        render_handoff(*data)


def test_fresh_source_without_private_xgb_can_import_and_fit_ridge():
    env = dict(os.environ, PYTHONPATH=str(ROOT/'src')+os.pathsep+str(ROOT),
               PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',
               MKL_NUM_THREADS='1',NUMBA_NUM_THREADS='1',RAYON_NUM_THREADS='1')
    code = '''
import importlib.util, json, sys
import quantbt
from quantbt.optimization.meta_selection.model import RidgeLearner
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from tests.meta_selection.test_mlr02_linear import corpus
from tools.meta_model_research.families import _xgboost, FamilyUnavailableError
assert importlib.util.find_spec("xgboost") is None, "absence proof requires a genuinely absent optional library"
assert "xgboost" not in sys.modules
data=corpus()
fit=RidgeLearner(runtime=NumericRuntime(native_policy="reference")).fit(
    data[0],data[2],fit_completed_at=data[3].decision_sealed_at)
assert fit.model is not None and fit.model.settings.lambda_reg == 10
try: _xgboost()
except FamilyUnavailableError: pass
else: raise AssertionError("missing optional dependency must fail explicitly")
assert "xgboost" not in sys.modules
print(json.dumps(dict(status="PASS",xgboost_absent=True,ridge_fit=True,lambda_reg=10)))
'''
    child = subprocess.run([sys.executable,'-B','-c',code],cwd=ROOT,env=env,
                           text=True,capture_output=True,check=True,timeout=60)
    assert json.loads(child.stdout) == dict(status='PASS',xgboost_absent=True,ridge_fit=True,lambda_reg=10)
