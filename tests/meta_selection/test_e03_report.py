"""E03 final report requires executed distinct groups, never partial/failing evidence."""

import xml.etree.ElementTree as ET
from copy import deepcopy
from hashlib import sha256

import pytest

from tools import qms_e03_report as report


def junit(tmp_path, *, state=None, omit=None, duplicate=False):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for group in range(1, 7):
        if group == omit:
            continue
        case = ET.SubElement(suite, "testcase", classname="scalar", name=f"test_e03_t{group:02d}_example")
        if state and group == 1:
            ET.SubElement(case, state)
    if duplicate:
        ET.SubElement(suite, "testcase", classname="scalar", name="test_e03_t01_example")
    path = tmp_path / "evidence.xml"
    ET.ElementTree(root).write(path)
    return path


def test_e03_t06_final_receipt_counts_unique_executions(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "file_ref", lambda p: dict(sha256="fixture"))
    receipt = report.test_receipt(junit(tmp_path))
    assert receipt["distinct_tests"] == 6
    assert all(n == 1 for n in receipt["e03_members"].values())


@pytest.mark.parametrize("bad", [dict(state="failure"), dict(state="error"), dict(state="skipped"),
                                  dict(omit=5), dict(duplicate=True)])
def test_e03_t06_bad_final_test_evidence_never_passes(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(report, "file_ref", lambda p: dict(sha256="fixture"))
    with pytest.raises(ValueError):
        report.test_receipt(junit(tmp_path, **bad))


def test_e03_t04_exact_baseline_waives_only_reviewed_manifest_not_account_or_historical_receipts(tmp_path, monkeypatch):
    name = "benchmarks/optimization/meta_selection/qms_e03_reviewed_source.json"
    file = tmp_path/name
    file.parent.mkdir(parents=True)
    file.write_text("reviewed")
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(report, "verify", lambda: True)
    baseline = dict(schema="qms-e02-baseline-v1", native=dict(lanes={"account":"fixed"}, guide_sha256="guide",
        historical_receipts={name:"before", "qms08_receipt":"immutable"}), scalar={}, reactive={"account":"fixed"})
    current = deepcopy(baseline)
    current["native"]["historical_receipts"][name] = sha256(file.read_bytes()).hexdigest()
    assert report.baseline_parity(baseline, current)
    for mutation in ("account", "receipt", "manifest"):
        wrong = deepcopy(current)
        if mutation == "account": wrong["native"]["lanes"]["account"] = "changed"
        elif mutation == "receipt": wrong["native"]["historical_receipts"]["qms08_receipt"] = "changed"
        else: wrong["native"]["historical_receipts"][name] = "unverified"
        with pytest.raises(AssertionError):
            report.baseline_parity(baseline, wrong)


def test_e03_t06_summary_counts_unique_params_per_origin_and_separates_execution_from_export():
    sample = dict(trials=[dict(schedule_fold_id=0, params={"window":12}),
                          dict(schedule_fold_id=0, params={"window":12}),
                          dict(schedule_fold_id=1, params={"window":12})],
        attempts=3, completed=2, pruned=1, wall_seconds=4., cpu_seconds=3.,
        after_memory=dict(peak_rss_mib=100.), after_export_memory=dict(peak_rss_mib=200.),
        cold_export_seconds_before_receipt=2., account_check_seconds=1.)
    before = deepcopy(sample)
    result = report.execution_summary(sample)
    assert result["unique_requested_params_by_fold"] == 2
    assert result["attempts"] == 3 and result["failed"] == 0
    assert result["wall_seconds"] == 4. and result["cpu_seconds"] == 3.
    assert result["execution_memory"]["peak_rss_mib"] == 100.
    assert result["export_memory"]["peak_rss_mib"] == 200.
    assert result["independent_account_check_seconds"] == 1.
    assert sample == before
    sample["completed"] = 3
    with pytest.raises(AssertionError):
        report.execution_summary(sample)


def test_e03_t06_explicit_failed_assessment_never_weakens_default_prepared_certificate():
    trial = dict(trial_id=1, params={"window":22}, objective=-2.5,
                 mean_is_sharpe=-2.5, pruned=False, fold_id=0)
    plain = dict(trials=[trial], params={0:{"window":22}})
    assert report.prepared_comparison(plain, plain)["gate"] == "PASS"
    bad = dict(trials=[{**trial, "objective":-4.1}], params={0:{"window":24}})
    with pytest.raises(AssertionError):
        report.prepared_comparison(plain, bad)
    result = report.prepared_comparison(plain, bad, assessment_only=True)
    assert result["gate"] == "FAIL" and result["parity_failure"]
    assert result["full_trial_pool_parity"] is False
    assert result["selected_params_exact"] is False
    assert plain["params"] == {0:{"window":22}}
