"""Required source/artifact evidence cannot be replaced by a PASS word."""

import json
import xml.etree.ElementTree as ET

import pytest

from tools import qms_pre06_qualification as gate


def xml(tmp_path, marker=None):
    path = tmp_path / "result.xml"
    tree = ET.Element("testsuite")
    case = ET.SubElement(tree, "testcase", classname="public.fixture", name="required")
    if marker:
        ET.SubElement(case, marker, message="unregistered capability unavailable")
    ET.ElementTree(tree).write(path)
    return path


@pytest.mark.parametrize("marker", ["skipped", "error", "failure"])
def test_required_failure_or_skip_blocks_gate(tmp_path, marker):
    with pytest.raises(ValueError):
        gate.regression([xml(tmp_path, marker)])


def test_missing_registered_na_blocks_gate(tmp_path):
    with pytest.raises(ValueError, match="N/A"):
        gate.regression([xml(tmp_path)])


def test_installed_gate_rejects_status_only(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "LANE", tmp_path)
    lane = tmp_path / "package-v1"
    lane.mkdir()
    (lane / "proof.json").write_text(json.dumps({"status": "NOT_RUN"}))
    (tmp_path / "registration.json").write_text("{}")
    with pytest.raises(ValueError, match="incomplete"):
        gate.installed()


def test_privacy_gate_current_public_patch():
    result = gate.privacy(historical=True)
    assert result["private_alpha_access"] is False and result["publication"] is False
    assert result["historical"] is True and result["scope_revision"] == "b035d20"
    with pytest.raises(ValueError, match="unapproved phase scope"):
        gate.privacy()


def collection_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "LANE", tmp_path)
    monkeypatch.setattr(gate, "ACCOUNT", ("test_phase59_linear_accounting_fill_replay",))
    failure_paths = [tmp_path / n for n in ("account-regression.xml", "account-regression-v2.xml")]
    for path in failure_paths:
        tree = ET.Element("testsuite")
        case = ET.SubElement(tree, "testcase", classname="", name="tests.test_phase59_linear_accounting_fill_replay")
        ET.SubElement(case, "error", message="collection failure").text = (
            "ModuleNotFoundError: No module named 'hypothesis'")
        ET.ElementTree(tree).write(path)
    account = tmp_path / "account-regression-v3.xml"
    tree = ET.Element("testsuite")
    ET.SubElement(tree, "testcase", classname="tests.test_phase59_linear_accounting_fill_replay", name="property")
    ET.ElementTree(tree).write(account)
    (tmp_path / "test-dependency-reuse.json").write_text(json.dumps(dict(
        versions={"hypothesis": "6.164.0", "sortedcontainers": "2.4.0"},
        changed_numeric_dependencies=False, record_verified_sha256={"fixture": "verified"})))
    return failure_paths, account


def test_collection_disposition_requires_separate_account_pass(tmp_path, monkeypatch):
    failures, account = collection_fixture(tmp_path, monkeypatch)
    result = gate.collection_disposition(failures, account)
    assert result["counted_as_pass"] is False and result["account_cases"] == 1


@pytest.mark.parametrize("mutation", ["missing_attempt", "financial_failure", "wrong_dependency", "extra_case",
                                      "missing_module", "unverified_correction", "failed_rerun"])
def test_collection_disposition_cannot_waive_execution(tmp_path, monkeypatch, mutation):
    failures, account = collection_fixture(tmp_path, monkeypatch)
    if mutation == "missing_attempt":
        failures.pop()
    elif mutation == "missing_module":
        monkeypatch.setattr(gate, "ACCOUNT", ("test_phase59_linear_accounting_fill_replay", "required_module"))
    elif mutation == "unverified_correction":
        path = tmp_path / "test-dependency-reuse.json"
        data = json.loads(path.read_text())
        data["changed_numeric_dependencies"] = True
        path.write_text(json.dumps(data))
    else:
        path = account if mutation == "failed_rerun" else failures[0]
        tree = ET.parse(path)
        case = next(tree.iter("testcase"))
        if mutation in ("financial_failure", "failed_rerun"):
            ET.SubElement(case, "failure", message="accounting mismatch")
        elif mutation == "wrong_dependency":
            case.find("error").text = "ModuleNotFoundError: No module named 'required_financial_module'"
        elif mutation == "extra_case":
            ET.SubElement(tree.getroot(), "testcase", classname="financial.runtime", name="executed")
        tree.write(path)
    with pytest.raises(ValueError):
        gate.collection_disposition(failures, account)


def test_public_regression_retains_digest_not_parameterized_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "REGISTERED_NA", frozenset())
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({"junit_sha256": {}}))
    monkeypatch.setattr(gate, "PRE05", prior)
    result = gate.regression([xml(tmp_path)])
    assert result["distinct_pass"] == 1 and len(result["case_identity_sha256"]) == 64
    assert "cases" not in result


@pytest.mark.parametrize("mutation", ["none", "protected_drift", "new_environment"])
def test_reused_cleanup_requires_exact_protected_hashes_and_absent_scratch(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "LANE", tmp_path)
    monkeypatch.setattr(gate, "CLEANABLE", ("scratch",))
    monkeypatch.setattr(gate, "cleanup_path", lambda n: tmp_path/n)
    monkeypatch.setattr(gate, "prerequisites", lambda: {"source": "sealed"})
    protected = tmp_path / "artifact"
    protected.write_text("sealed")
    receipt = dict(source={"source": "sealed"}, runtime_source_unchanged=True,
                   deleted=["scratch"], protected_sha256={"artifact": gate.file_hash(protected)})
    (tmp_path/"cleanup.json").write_text(json.dumps(receipt))
    monkeypatch.setattr(gate, "checked_hashes", lambda values: [
        (_ for _ in ()).throw(ValueError("protected drift")) for n, expected in values.items()
        if gate.file_hash(tmp_path/n) != expected])
    if mutation == "protected_drift":
        protected.write_text("modified")
    elif mutation == "new_environment":
        (tmp_path/"scratch").mkdir()
    if mutation == "none":
        assert gate.cleanup() == receipt
    else:
        with pytest.raises(ValueError):
            gate.cleanup()
