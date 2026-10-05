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
