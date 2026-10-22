"""Qualification requires real work and preserved source, not status strings."""

from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from tools import qms_e06_closure as gate


@pytest.mark.parametrize("marker", ("skipped", "failure", "error"))
def test_e06_required_test_cannot_be_waived(tmp_path, marker):
    tree = ET.Element("testsuite")
    case = ET.SubElement(tree, "testcase", classname="e06", name="required")
    ET.SubElement(case, marker, message="not qualified")
    path = tmp_path / "result.xml"
    ET.ElementTree(tree).write(path)
    with pytest.raises(ValueError):
        gate.passed_cases(path)


def matrix():
    row = dict(account_rebuild_exact=True, applied_params=True, observer_failures=0,
        models=1, minimum_origins=12, raw_pairs_checked=2)
    rows = [dict(row, mode=m, witness=w, semantic_sha256=m)
            for m in gate.MODES for w in (False, True) for _ in range(gate.REPEATS)]
    return dict(installed=False, cells=len(rows), rows=rows), dict(expected_cells={m: m for m in gate.MODES})


def test_e06_complete_matrix():
    value, registered = matrix()
    assert gate.validate_matrix(value, registered, installed=False) == 18


@pytest.mark.parametrize("mutation", ("cold", "logical", "missing", "rebuild", "observer", "params"))
def test_e06_matrix_cannot_self_attest(mutation):
    value, registered = matrix()
    altered = deepcopy(value)
    row = next(r for r in altered["rows"] if r["mode"] == "active")
    if mutation == "cold":
        row["minimum_origins"] = 11
    elif mutation == "logical":
        row["semantic_sha256"] = "different"
    elif mutation == "missing":
        altered["rows"].pop()
    elif mutation == "rebuild":
        row["account_rebuild_exact"] = False
    elif mutation == "params":
        row["applied_params"] = False
    else:
        row["observer_failures"] = 1
    with pytest.raises(ValueError):
        gate.validate_matrix(altered, registered, installed=False)


@pytest.mark.parametrize("path", ("..", "source", ".maturin", "wheel-consumer/cache"))
def test_e06_cleanup_rejects_unreviewed_root(path):
    with pytest.raises(ValueError):
        gate.scratch(path)
