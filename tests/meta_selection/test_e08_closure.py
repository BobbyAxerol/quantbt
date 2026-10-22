"""Independent current-scope privacy and exact regression evidence checks."""

import json
import xml.etree.ElementTree as ET

import pytest

from tools import qms_e08_closure as gate


def privacy_patch(tmp_path, monkeypatch, name, payload):
    path = tmp_path/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "verify", lambda: {"exact": True})
    def output(args, **kwargs):
        return name+"\n" if "--name-only" in args else ""
    monkeypatch.setattr(gate.subprocess, "check_output", output)
    return path


def test_current_e08_privacy_checks_public_patch(tmp_path, monkeypatch):
    privacy_patch(tmp_path, monkeypatch, "docs/meta_selection/QMSE08_REPORT.md", "public diagnostic")
    assert gate.privacy() == dict(checked_files=1, private_alpha_access=False, private_study=False, publication=False)


@pytest.mark.parametrize("name", ("src/quantbt/endpoint.py", "private_alpha.py", "rust/unknown.rs"))
def test_unreviewed_e08_scope_rejected(tmp_path, monkeypatch, name):
    privacy_patch(tmp_path, monkeypatch, name, "unreviewed")
    with pytest.raises(ValueError, match="unapproved E08"):
        gate.privacy()


@pytest.mark.parametrize("payload", ("ghp_"+"a"*30, "pypi-"+"x"*40))
def test_e08_credentials_cannot_be_published(tmp_path, monkeypatch, payload):
    privacy_patch(tmp_path, monkeypatch, "docs/report.md", payload)
    with pytest.raises(ValueError, match="credential"):
        gate.privacy()


def evidence(tmp_path, monkeypatch, *, failed=False):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "verify", lambda: {"exact": True})
    monkeypatch.setattr(gate, "commands", lambda: {"meta": ["registered"], "wfo": ["registered"]})
    monkeypatch.setattr(gate, "REGISTERED_NA", frozenset())
    path = tmp_path/"result.json"
    path.write_text("{}")
    path.with_suffix(".log").write_text("actual execution log")
    tree = ET.Element("testsuite")
    key = ("public.fixture", "required")
    ET.SubElement(tree, "testcase", classname=key[0], name=key[1])
    if failed:
        repair = next(iter(gate.META_REPAIR))
        case = ET.SubElement(tree, "testcase", classname=repair[0], name=repair[1])
        ET.SubElement(case, "failure", message="old privacy scope")
    ET.ElementTree(tree).write(path.with_suffix(".xml"))
    registration = dict(source_guard={"exact": True}, command=["registered"], admitted_na=[], publication=False)
    path.with_suffix(".registration.json").write_text(json.dumps(registration))
    row = dict(returncode=int(failed), log_sha256=gate.digest(path.with_suffix(".log")),
        xml_sha256=gate.digest(path.with_suffix(".xml")), publication=False,
        distinct_pass=1, cases=[key], admitted_skips=0)
    return path, row, key


def test_regression_counts_are_recomputed_from_xml(tmp_path, monkeypatch):
    path, row, key = evidence(tmp_path, monkeypatch)
    actual, summary = gate.regression("wfo", path, row)
    assert actual == {key} and summary["distinct_pass"] == 1


@pytest.mark.parametrize("mutation", ("count", "cases", "log", "command", "guard", "skip", "failure"))
def test_regression_cannot_self_attest_pass(tmp_path, monkeypatch, mutation):
    path, row, _ = evidence(tmp_path, monkeypatch)
    if mutation == "count":
        row["distinct_pass"] = 2
    elif mutation == "cases":
        row["cases"] = [("other", "case")]
    elif mutation == "log":
        path.with_suffix(".log").write_text("changed")
    elif mutation in {"command", "guard"}:
        p = path.with_suffix(".registration.json")
        registration = json.loads(p.read_text())
        registration["command" if mutation == "command" else "source_guard"] = {}
        p.write_text(json.dumps(registration))
    else:
        p = path.with_suffix(".xml")
        tree = ET.parse(p)
        ET.SubElement(next(tree.iter("testcase")), "skipped" if mutation == "skip" else "failure")
        tree.write(p)
        row["xml_sha256"] = gate.digest(p)
    with pytest.raises(ValueError):
        gate.regression("wfo", path, row)


def test_only_registered_privacy_failure_has_a_repair_path(tmp_path, monkeypatch):
    path, row, key = evidence(tmp_path, monkeypatch, failed=True)
    actual, summary = gate.regression("meta", path, row, repaired_by=gate.META_REPAIR)
    assert actual == {key} and summary["repaired_failures"] == [list(next(iter(gate.META_REPAIR)))]
    p = path.with_suffix(".xml")
    tree = ET.parse(p)
    case = list(tree.iter("testcase"))[-1]
    case.set("name", "accounting_failure")
    tree.write(p)
    row["xml_sha256"] = gate.digest(p)
    with pytest.raises(ValueError, match="unexpected failure"):
        gate.regression("meta", path, row, repaired_by=gate.META_REPAIR)
