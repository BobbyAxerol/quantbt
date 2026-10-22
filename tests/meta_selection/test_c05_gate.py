"""C05-T06: receipt cannot invent approval, qualification or runtime support."""

from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from tools.qms_c05_gate import require_no_production_changes, require_review_scope, test_evidence as inspect_tests


def receipt():
    return dict(schema="qms-c05-spec-gate-v1", technical_gate="PASS_LOCAL_SPEC",
        implementation_status="SPEC_AND_TESTS_COMPLETE_RUNTIME_NOT_ACTIVATED",
        production_activation=False, publication_authorized=False,
        economic_claim=False, speedup_claim=False,
        owner_methodology_approval="PENDING", remote_qualification="NOT_RUN")


def junit(tmp_path, change=None):
    root = ET.Element("testsuite", tests="6", errors="0", failures="0")
    for i in range(1, 7):
        case = ET.SubElement(root, "testcase", classname="test_c05_review", name=f"test_c05_t{i:02d}_fixture")
        if i == 6 and change in {"failure", "error", "skipped"}:
            ET.SubElement(case, change)
    if change == "missing":
        root.remove(case)
    elif change == "duplicate":
        root.append(deepcopy(case))
    elif change == "collection":
        root.set("errors", "1")
    path = tmp_path / "execution.xml"
    ET.ElementTree(root).write(path)
    return path


def test_c05_t06_passing_review_still_cannot_activate(tmp_path):
    require_review_scope(receipt())
    count, members = inspect_tests([junit(tmp_path)])
    assert count == 6 and all(len(rows) == 1 for rows in members.values())


@pytest.mark.parametrize("key,value", [("production_activation", True), ("publication_authorized", True),
    ("economic_claim", True), ("speedup_claim", True), ("owner_methodology_approval", "APPROVED"),
    ("remote_qualification", "PASS"), ("implementation_status", "FULLY_IMPLEMENTED"),
    ("technical_gate", "PRODUCTION_CERTIFIED"), ("schema", "new-v2"), ("production_activation", 0)])
def test_c05_t06_receipt_cannot_manufacture_activation_or_superiority(key, value):
    bad = receipt()
    bad[key] = value
    with pytest.raises(ValueError):
        require_review_scope(bad)


@pytest.mark.parametrize("change", ["failure", "error", "skipped", "missing", "duplicate", "collection"])
def test_c05_t06_nonpassing_or_incomplete_test_evidence_rejected(tmp_path, change):
    with pytest.raises(ValueError):
        inspect_tests([junit(tmp_path, change)])


@pytest.mark.parametrize("name", ["src/quantbt/optimization/samplers.py", "rust/quantbt-native/src/lib.rs",
    "quantbt/endpoint.py", "pyproject.toml", "uv.lock", "contracts/new.json"])
def test_c05_t06_spec_gate_accepts_no_production_edits(name):
    with pytest.raises(ValueError, match="protected source"):
        require_no_production_changes([name])
