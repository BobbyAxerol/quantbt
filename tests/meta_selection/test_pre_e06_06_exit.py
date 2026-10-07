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
    result = gate.privacy()
    assert result["private_alpha_access"] is False and result["publication"] is False
