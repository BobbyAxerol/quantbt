"""Independent proof negatives; no local private receipt is required by CI."""

from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tools import qms_e02_audit as audit
from tools.qms_e02_gate import check_parity, check_resources, check_tests


def test_e02_t06_snapshot_json_roundtrip_cannot_create_false_tuple_list_mismatch(monkeypatch):
    import tests.meta_selection.test_local_reactive as fixture
    monkeypatch.setattr(audit, "native_snapshot", lambda: dict(lanes=[], guide_sha256="guide", historical_receipts={}))
    monkeypatch.setattr(audit, "execute", lambda *a, **kw: dict(scientific_signature="same",
        selected_params_by_fold={}, observer_attempts=0, observer_failures=0, switches=0,
        account_authority="original", records=[]))
    result = SimpleNamespace(metadata={"meta_selection": {"tasks": [], "records": [dict(
        family_id="family", native_selected_evaluation_id="anchor", selected_evaluation_id="anchor",
        panel_members=("anchor", "other"), final_selection_reason="native")]}},
        params_by_fold={0: {"direction": 1.}}, trial_table=pd.DataFrame({"objective": [np.inf, 1.]}),
        fold_results=[])
    monkeypatch.setattr(fixture, "execute", lambda *a: (result, None, SimpleNamespace(close=lambda: None)))
    actual = audit.snapshot()
    restored = json.loads(json.dumps(actual))
    assert actual == restored
    assert audit.compare(restored, actual)


@pytest.mark.parametrize("status", ["failure", "error", "skipped", "missing", "empty"])
def test_e02_t06_independent_gate_requires_all_six_actual_passing_junit_groups(tmp_path, status):
    cases = "".join(f'<testcase classname="contracts" name="test_e02_t{i:02}_executed" />' for i in range(1, 7))
    if status == "missing":
        cases = cases.replace('<testcase classname="contracts" name="test_e02_t06_executed" />', "")
    elif status == "empty":
        cases = ""
    else:
        cases += f'<testcase classname="contracts" name="extra"><{status} /></testcase>'
    file = tmp_path / "tests.xml"
    file.write_text(f'<testsuite>{cases}</testsuite>')
    with pytest.raises(ValueError):
        check_tests([file])


def test_e02_t06_junit_repeated_runs_are_not_summed(tmp_path):
    file = tmp_path / "tests.xml"
    file.write_text('<testsuite>'+"".join(f'<testcase classname="contracts" name="test_e02_t{i:02}_executed" />'
        for i in range(1, 7))+'</testsuite>')
    assert check_tests([file, file])["unique_tests"] == 6


@pytest.mark.parametrize("receipt", [{}, {"schema": "qms-e02-matched-resources-v1", "repeats": 3, "rows": []}])
def test_e02_t06_gate_rejects_missing_actual_resource_logs(receipt):
    with pytest.raises(ValueError):
        check_resources(receipt)


def test_e02_t06_gate_rejects_synthetic_pass_without_executed_lane_matrix():
    missing = dict(exact_parity=True, native={"lanes": []}, scalar={}, reactive={})
    with pytest.raises(ValueError):
        check_parity(deepcopy(missing), missing)
