"""CI failure summaries expose retained public test errors without relaxing gates."""

from pathlib import Path
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def diagnostic_step():
    workflow = yaml.load((ROOT / ".github/workflows/qms-candidate.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["installed-candidate"]["steps"]
    step = next(row for row in steps if row.get("name") == "Annotate qualification failures from retained JUnit")
    assert step["if"] == "failure()"
    assert steps.index(step) < len(steps) - 1
    assert steps[-1]["if"] == "always()"
    return step


def run_diagnostics(directory):
    environment = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    return subprocess.run(["bash", "-c", diagnostic_step()["run"]], cwd=directory,
                          env=environment, capture_output=True, text=True)


@pytest.mark.parametrize("tag", ["failure", "error"])
def test_retained_junit_errors_are_escaped_and_annotated(tmp_path, tag):
    directory = tmp_path / ".maturin/qms08"
    directory.mkdir(parents=True)
    root = ET.Element("testsuites")
    case = ET.SubElement(ET.SubElement(root, "testsuite"), "testcase", classname="public.tests", name="test_gate")
    ET.SubElement(case, tag).text = "Mismatch 10%\nexpected value\n" + "x" * 7000
    ET.SubElement(root, "testcase", classname="public.tests", name="test_passed")
    path = directory / "release-gaps.xml"
    ET.ElementTree(root).write(path)
    original = path.read_bytes()
    result = run_diagnostics(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("::error::public.tests::test_gate%0AMismatch 10%25%0Aexpected value%0A")
    assert result.stdout.count("::error::") == 1
    assert "test_passed" not in result.stdout and len(result.stdout) < 6100
    assert path.read_bytes() == original


def test_missing_junit_does_not_invent_diagnostics(tmp_path):
    result = run_diagnostics(tmp_path)
    assert result.returncode == 0 and result.stdout == ""


def test_invalid_junit_is_not_reported_as_success(tmp_path):
    directory = tmp_path / ".maturin/qms08"
    directory.mkdir(parents=True)
    path = directory / "release-gaps.xml"
    path.write_text("not XML")
    result = run_diagnostics(tmp_path)
    assert result.returncode != 0 and "ParseError" in result.stderr
    assert path.read_text() == "not XML"
