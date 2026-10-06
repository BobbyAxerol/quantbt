"""Constructed XML validates the gate, not financial/economic behavior."""

import json
import xml.etree.ElementTree as ET

import pytest

from tools.qms_pre03_qualification import CUTOFFS, ROUTES, SINGLE, TRIPLE, matrix_gate


def fixture():
    root = ET.Element("testsuite")
    for route in ROUTES:
        for name in SINGLE:
            c = ET.SubElement(root, "testcase", name=f"test_pre03_{name}[{route}]")
            if name == "matured_actual_fit_rank_and_applied_params":
                rows = [dict(route=route, cutoff=cutoff, matured_origins=12, training_rows=24,
                    predictions=3, model_status="META_MODEL_PROPOSAL", changed_from_anchor=route == ROUTES[0])
                    for cutoff in CUTOFFS]
                ET.SubElement(ET.SubElement(c, "properties"), "property", name="pre02_matured", value=json.dumps(rows))
        for name in TRIPLE:
            for i in range(3):
                c = ET.SubElement(root, "testcase", name=f"test_pre03_{name}[{route}-cutoff{i}]")
                if name == "matured_scalar_prepared_reference" and route == "dca_ladder":
                    ET.SubElement(c, "skipped")
    return root


def test_pre03_gate_excludes_only_declared_ladder_scalar_na():
    r = matrix_gate(fixture())
    assert r["required_pass"] == 132 and r["not_applicable"] == 3
    assert r["mature_decisions"] == 15


@pytest.mark.parametrize("violation", ("missing", "duplicate", "failure", "skip", "maturity", "cold", "cutoff", "switch"))
def test_pre03_gate_rejects_incomplete_vacuous_or_failed_receipt(violation):
    root = fixture()
    first = root.find("testcase")
    if violation == "missing":
        root.remove(first)
    elif violation == "duplicate":
        root.append(first)
    elif violation in {"failure", "skip"}:
        ET.SubElement(first, "failure" if violation == "failure" else "skipped")
    else:
        for prop in root.iter("property"):
            rows = json.loads(prop.get("value"))
            for row in rows:
                key, val = {"maturity": ("matured_origins", 9), "cold": ("model_status", "COLD_START"),
                    "cutoff": ("cutoff", "2025-01-01"), "switch": ("changed_from_anchor", False)}[violation]
                row[key] = val
            prop.set("value", json.dumps(rows))
    with pytest.raises(ValueError):
        matrix_gate(root)
