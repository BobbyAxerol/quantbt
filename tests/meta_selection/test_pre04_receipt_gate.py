"""A failed archived fixture is resolved only by its own actual passing rerun."""

import xml.etree.ElementTree as ET

import pytest

from tools.qms_pre04_qualification import Q6, reconcile


def fixture():
    regression = {}
    current = {}
    for i in range(590):
        key = (Q6 if i < 46 else "other", "case-"+str(i))
        c = ET.Element("testcase")
        if i < 12:
            ET.SubElement(c, "failure")
        regression[key] = c
        if i < 46:
            current[key] = ET.Element("testcase")
    return regression, current


def test_gate_requires_all_exact_rerun_identities():
    assert len(reconcile(*fixture())) == 590


@pytest.mark.parametrize("violation", ["missing", "unrelated", "skipped", "failure"])
def test_gate_rejects_incomplete_or_invalid_failure_disposition(violation):
    initial, current = fixture()
    if violation == "missing":
        current.pop(next(iter(current)))
    elif violation == "unrelated":
        ET.SubElement(initial[("other", "case-100")], "failure")
    else:
        ET.SubElement(next(iter(current.values())), violation)
    with pytest.raises(ValueError):
        reconcile(initial, current)
