"""Fail-closed receipts and complete portable CI wiring, no mocked PASS runs."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools import qms_installed_execution as gate
from tools.qms_e08_consumer import EXPECTED, GROUPS


def valid(group):
    manifest = dict(core="1.1.2", native="0.4.3", native_extension_sha256="hash", core_inventory={"__init__.py": "source"})
    row = dict(schema="qms-e08-installed-execution-v1", group=group,
        counts=dict(tests=EXPECTED[group], failures=0, errors=0, skipped=0),
        identity=dict(core="1.1.2", native="0.4.3", native_sha256="hash", modules=1,
            core_origin="/tmp/consumer/lib/python3.12/site-packages/quantbt",
            native_origin="/tmp/consumer/lib/python3.12/site-packages/_quantbt_native/core.so"),
        threads=dict(mismatches=[], inspection_limits=[]),
        source_sha256={name: gate.digest(gate.ROOT/"tests/meta_selection"/name) for name in GROUPS[group]},
        publication=False, empirical_promotion=False)
    return row, manifest


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("mutation", ("missing", "skip", "error", "thread", "origin", "hash", "source", "publish"))
def test_incomplete_receipt_cannot_pass(group, mutation):
    row, manifest = valid(group)
    gate.validate_row(row, group, manifest)
    changed = deepcopy(row)
    if mutation == "missing": changed["counts"]["tests"] -= 1
    elif mutation == "skip": changed["counts"]["skipped"] = 1
    elif mutation == "error": changed["counts"]["errors"] = 1
    elif mutation == "thread": changed["threads"]["mismatches"] = [{"numba": 4}]
    elif mutation == "origin": changed["identity"]["core_origin"] = "/tmp/checkout/src/quantbt"
    elif mutation == "hash": changed["identity"]["native_sha256"] = "other"
    elif mutation == "source": changed["source_sha256"].pop(next(iter(changed["source_sha256"])))
    else: changed["publication"] = True
    with pytest.raises(ValueError):
        gate.validate_row(changed, group, manifest)


def test_workflow_covers_both_os_three_interpreters_and_all_execution_proofs():
    path = gate.ROOT/".github/workflows/qms-candidate.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["installed-candidate"]
    assert job["strategy"]["matrix"] == {"runner": ["ubuntu-22.04", "ubuntu-24.04"], "python": ["3.11", "3.12", "3.13"]}
    assert set(job["env"].values()) == {"1"}
    assert set(job["env"]) == {"OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS"}
    assert any("tools.qms_installed_execution" in step.get("run", "") for step in job["steps"])
    assert "installed-execution-proof/*" in job["steps"][-1]["with"]["path"]
    filters = workflow["on"]["pull_request"]["paths"]
    assert all(p in filters for p in ("tools/qms_e06*", "tools/qms_e07*", "tools/qms_e08*", "src/quantbt/wfo_execution.py"))


def test_wrong_lane_cannot_be_qualified(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        gate.qualify(tmp_path)
