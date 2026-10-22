"""Fail-closed receipt validation; constructed XML is never financial evidence."""

import json
import xml.etree.ElementTree as ET

import pytest

from tools.qms_pre02_qualification import CUTOFFS, PREPARED, ROUTES, SINGLE, TRIPLE, matrix_gate


def fixture():
    root = ET.Element("testsuite")
    for route in ROUTES:
        for name in SINGLE:
            case = ET.SubElement(root, "testcase", name=f"test_pre02_{name}[{route}]")
            if name == "matured_actual_fit_rank_and_applied_params":
                rows = [dict(route=route, cutoff=cutoff, matured_origins=12, training_rows=24,
                    predictions=3, model_status="META_MODEL_PROPOSAL", changed_from_anchor=route == ROUTES[0])
                    for cutoff in CUTOFFS]
                ET.SubElement(ET.SubElement(case, "properties"), "property", name="pre02_matured",
                              value=json.dumps(rows))
        for name in TRIPLE:
            for i in range(3):
                case = ET.SubElement(root, "testcase", name=f"test_pre02_{name}[{route}-cutoff{i}]")
                if name == "matured_scalar_prepared_reference" and route not in PREPARED:
                    ET.SubElement(case, "skipped")
    return root


def test_pre02_gate_counts_only_required_public_cells_not_scalar_na():
    result = matrix_gate(fixture())
    assert result["required_pass"] == 311 and result["scalar_scorer_not_applicable"] == 27
    assert result["mature_decisions"] == 39


@pytest.mark.parametrize("violation", ("missing", "duplicate", "failure", "skip", "maturity", "cold", "cutoff", "switch"))
def test_pre02_gate_rejects_vacuous_incomplete_or_failed_public_receipts(violation):
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
                if violation == "maturity":
                    row["matured_origins"] = 9
                elif violation == "cold":
                    row["model_status"] = "COLD_START"
                elif violation == "cutoff":
                    row["cutoff"] = "2025-01-01"
                else:
                    row["changed_from_anchor"] = False
            prop.set("value", json.dumps(rows))
    with pytest.raises(ValueError):
        matrix_gate(root)
