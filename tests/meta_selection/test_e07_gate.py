"""E07 gates reject incomplete, cold, changed-output or unapproved source work."""

from copy import deepcopy
import json
import os
import subprocess
import sys

import pytest

from tools import qms_e07_contract as gate
from tests.meta_selection.e07_support import CASES


def matrix():
    return dict(rows=[dict(case=list(case), mode=mode, variant=variant, repeat=repeat,
        semantic_sha256="same", account_pool_sha256="same", models=1, minimum_origins=12,
        raw_pairs_checked=2, output_revisions=1, observer_failures=0, account_rebuild_exact=True)
        for case in CASES for mode in gate.MODES for variant in (False, True) for repeat in range(3)])


def test_e07_complete_matrix_requires_every_protocol_and_variant():
    assert gate.validate_matrix(matrix(), repeats=3) == 90


@pytest.mark.parametrize("change", ("missing", "duplicate", "cold", "no_model", "no_output", "wrong_pool", "account", "observer", "no_measurement"))
def test_e07_matrix_never_accepts_self_attested_empty_coverage(change):
    value = deepcopy(matrix())
    row = next(r for r in value["rows"] if r["mode"] == "active")
    if change == "missing":
        value["rows"].pop()
    elif change == "duplicate":
        value["rows"][-1] = value["rows"][-2]
    elif change == "cold":
        row["minimum_origins"] = 11
    elif change == "no_model":
        row["models"] = 0
    elif change == "no_output":
        row["output_revisions"] = 0
    elif change == "wrong_pool":
        row["semantic_sha256"] = "changed"
    elif change == "account":
        row["account_rebuild_exact"] = False
    elif change == "observer":
        row["observer_failures"] = 1
    else:
        row["raw_pairs_checked"] = 0
    with pytest.raises(ValueError):
        gate.validate_matrix(value, repeats=3)


def test_e07_source_amendment_preserves_every_other_runtime_byte():
    assert len(gate.source_guard()) == 322


def test_e07_actual_mature_process_transport_and_resource_cleanup():
    code = '''
import json, multiprocessing
from tests.meta_selection import e07_support as e07, pre_e06_02_support as shared
from tools.qms_pre05_workloads import Cell, load_history, semantic
from tools.qms_e07_contract import LANE
case = ("reactive_reset", "rust")
for mode in ("off", "shadow", "active"):
    path = LANE / "history/reactive_reset-rust.json"
    local = e07.run(case, mode, history=load_history(path) if mode != "off" else None)
    worker = e07.run(case, mode, history=load_history(path) if mode != "off" else None, process=True)
    assert local.result.params_by_fold == worker.result.params_by_fold
    shared.account_equal(local.result.fold_results[0].result, worker.result.fold_results[0].result)
    if mode != "off":
        shared.decision_equal(local, worker)
        assert worker.meta["records"][0]["matured_origins"] >= 12
        assert worker.meta["records"][0]["final_selection_reason"] == "META_MODEL_PROPOSAL"
        assert worker.meta["observed_revisions"] and worker.meta["witness_transport"]["worker_mode"] == "process"
    assert worker.endpoint._process_worker is None and worker.endpoint._meta_boundary is None
    assert not multiprocessing.active_children()
print(json.dumps({"mature_process_cells": 3, "children": 0}))
'''
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
        NUMBA_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
        PYTHONPATH=str(gate.ROOT / "src")+":"+str(gate.ROOT))
    process = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stdout + process.stderr
    assert json.loads(process.stdout.splitlines()[-1]) == dict(mature_process_cells=3, children=0)
