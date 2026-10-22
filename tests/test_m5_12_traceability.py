"""Cold requirement mapping and fail-closed evidence readers; no finance/imports."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

from tools import m5_12_traceability as trace


ROOT = Path(__file__).resolve().parents[1]


def _guide(count=120):
    header = "# Phụ lục B — 120 mandatory acceptance requirements\n"
    return header + "\n".join(
        f"| `M5T-{i:03d}` | unit/math | scenario {i} | assertion {i} |"
        for i in range(1, count + 1)) + "\n# Phụ lục C\n"


def _run(tmp_path, *, name="test_m5t_001_control[private-value]", child="", counts="", exit_code=0):
    directory = tmp_path / trace.PRIVATE / "m5-01/attempt-04"
    directory.mkdir(parents=True)
    xml = directory / "tests.xml"
    xml.write_text(f'<testsuites><testsuite tests="1" {counts}><testcase classname="tests.synthetic" '
                   f'name="{name}">{child}</testcase></testsuite></testsuites>')
    command = directory / "check-01.json"
    command.write_text(json.dumps(dict(command=["python", "-m", "pytest", "--junitxml=" + str(xml)],
                                      exit_code=exit_code)))
    phase = replace(trace.PHASES[0], xml_sha256=sha256(xml.read_bytes()).hexdigest(),
                    command_sha256=sha256(command.read_bytes()).hexdigest())
    return phase, xml, command


def _canonical_report():
    report = dict.fromkeys(trace.REPORT_FIELDS)
    report.update(schema="quantbt.mode5_upgrade.phase_report.v1", phase_id="M5-12",
        status="IN_PROGRESS", scientific_status="NOT_EVALUABLE",
        hypotheses_tested=[], requirements=[], test_runs=[], blocking_issues=[],
        proof_capability=dict(positive_controls="NOT_RUN", null_controls="NOT_RUN",
                              coverage="registered only", vacuous_checks=[]),
        potential_assessment=dict(evidence=[], bottlenecks=["qualification pending"],
                                  next_falsifiable_actions=["run main bounded gate"]),
        reproduction=dict(command=["python", "-m", "tools.m5_12_traceability"]))
    return report


def test_each_requirement_is_parsed_once_and_keeps_its_assertion_not_a_test_count():
    rows = trace.guide_requirements(_guide())
    assert len(rows) == 120 and len({row["id"] for row in rows}) == 120
    assert rows[0]["required_assertion"] == "assertion 1"
    assert rows[-1]["phase"] == "M5-12"
    assert {r["phase"] for r in rows} == {f"M5-{i:02d}" for i in range(1, 13)}


@pytest.mark.parametrize("text", ["", _guide(119), _guide(121),
    _guide().replace("`M5T-002`", "`M5T-001`")])
def test_missing_duplicate_or_extra_guide_requirement_fails_closed(text):
    with pytest.raises(ValueError):
        trace.guide_requirements(text)


def test_pinned_run_has_real_assertion_and_never_exports_parameter_suffix(tmp_path):
    phase, _, _ = _run(tmp_path)
    run = trace._read_run(tmp_path, phase)
    row = trace.requirement_evidence(trace.guide_requirements(_guide())[0], run, [])
    assert row["evidence_state"] == "HISTORICAL_ASSERTIONS_RECORDED"
    assert row["assertions"] == ["tests.synthetic::test_m5t_001_control"]
    assert row["executed_parameter_cases"] == 1
    assert "private-value" not in json.dumps(row)
    assert row["current_installed_qualification"] == "NOT_INFERRED_FROM_HISTORICAL_RECEIPTS"


@pytest.mark.parametrize("child,counts,code", [
    ('<failure message="retained failure"/>', "", 0),
    ("<error/>", "", 0), ("<skipped/>", "", 0),
    ("", 'errors="1"', 0), ("", 'failures="1"', 0),
    ("", "", 1), ("", "", False),
])
def test_skipped_failed_or_bad_command_cannot_become_recorded_assertion(tmp_path, child, counts, code):
    phase, _, _ = _run(tmp_path, child=child, counts=counts, exit_code=code)
    row = trace.requirement_evidence(trace.guide_requirements(_guide())[0], trace._read_run(tmp_path, phase), [])
    assert row["evidence_state"] == "INSUFFICIENT_RECORDED_ASSERTIONS"


def test_count_only_and_unrelated_test_names_never_satisfy_requirement(tmp_path):
    phase, _, _ = _run(tmp_path, name="test_unrelated_pass")
    row = trace.requirement_evidence(trace.guide_requirements(_guide())[0], trace._read_run(tmp_path, phase), [])
    assert not row["assertions"]
    assert row["evidence_state"] == "INSUFFICIENT_RECORDED_ASSERTIONS"


@pytest.mark.parametrize("which", ["xml", "command"])
def test_immutable_receipt_mutation_is_not_a_new_pass(tmp_path, which):
    phase, xml, command = _run(tmp_path)
    path = xml if which == "xml" else command
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="immutable receipt changed"):
        trace._read_run(tmp_path, phase)


def test_missing_private_evidence_reports_gap_not_installed_pass(tmp_path):
    run = trace._read_run(tmp_path, trace.PHASES[0])
    assert run["xml"]["status"] == "MISSING"
    row = trace.requirement_evidence(trace.guide_requirements(_guide())[0], run, [])
    assert row["evidence_state"] == "INSUFFICIENT_RECORDED_ASSERTIONS"


@pytest.mark.parametrize("path", ["../receipt.json", "/tmp/receipt.json", "a\\receipt.json"])
def test_reader_rejects_path_escape(tmp_path, path):
    with pytest.raises(ValueError, match="repository-relative"):
        trace._bytes(tmp_path, path)


def test_reader_rejects_links_and_byte_budget_without_following_private_trees(tmp_path, monkeypatch):
    target = tmp_path / "receipt.json"
    target.write_text('{"safe":true}')
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        trace._bytes(tmp_path, "link.json")
    monkeypatch.setattr(trace, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="bounded reader"):
        trace._bytes(tmp_path, "receipt.json")


def test_mid_read_mutation_is_detected(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text("{}")
    reference = trace._ref(tmp_path, "receipt.json")
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="changed during readback"):
        trace._checked_bytes(tmp_path, reference)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]'])
def test_ambiguous_or_nonfinite_json_is_not_evidence(raw):
    with pytest.raises(ValueError):
        trace._json(raw)


def test_entity_declarations_are_not_expanded(tmp_path):
    phase, xml, _ = _run(tmp_path)
    xml.write_text('<!DOCTYPE testsuites [<!ENTITY x "secret">]><testsuites/>')
    phase = replace(phase, xml_sha256=sha256(xml.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="DTD/entity"):
        trace._read_run(tmp_path, phase)


def test_new_report_schema_requires_proof_potential_and_reproduction_not_just_counts():
    with pytest.raises(ValueError, match="missing phase report fields"):
        trace.validate_phase_report(dict(phase_id="M5-12", tests=120, status="PASS"))
    trace.validate_phase_report(_canonical_report())


@pytest.mark.parametrize("field,value", [
    ("proof_capability", {}), ("proof_capability", {"tests": 120}),
    ("potential_assessment", {"tests": 120}), ("reproduction", {}),
    ("reproduction", {"command": []}), ("test_runs", 120),
    ("phase_id", "M5-13"), ("schema", "just-a-pass"),
])
def test_new_canonical_report_rejects_incomplete_sections(field, value):
    report = _canonical_report()
    report[field] = value
    with pytest.raises(ValueError):
        trace.validate_phase_report(report)


def test_actual_retained_register_maps_all_ids_and_keeps_pending_qualification_separate():
    # Read-only: no test collection/import of QuantBT or private alpha modules.
    before = set(sys.modules)
    result = trace.build_inventory(ROOT)
    assert len(result["requirements"]) == 120 and len(result["phases"]) == 12
    assert [r["id"] for r in result["requirements"]] == [f"M5T-{i:03d}" for i in range(1, 121)]
    assert not result["package_qualified"] and not result["all_120_pass"]
    assert not result["publication_authorized"]
    assert result["phases"][-1]["recorded_status"] == "MAIN_REPORT_NOT_SUPPLIED"
    assert all(row["evidence_state"] == "MAIN_CURRENT_QUALIFICATION_REQUIRED"
               for row in result["requirements"][110:])
    assert all(row["assertions"] or row["number"] == 77 for row in result["requirements"][:110])
    assert result["requirements"][76]["evidence_state"] == "RETAINED_REANALYSIS_NOT_NEW_EXECUTION"
    legacy = result["requirements"][90]["legacy_mode_regression"]
    assert legacy["evidence_state"] == "HISTORICAL_ASSERTIONS_RECORDED"
    assert any("mode_1_decay" in name for name in legacy["assertions"])
    assert any("mode_2_sbb" in name for name in legacy["assertions"])
    assert any("flat_minima" in name for name in legacy["assertions"])
    assert result["requirements"][102]["approved_research_limit"]["disposition"] == "DEFERRED_APPROVED"
    assert not any(name == "quantbt" or name.startswith("quantbt.") for name in set(sys.modules) - before)
    assert all(not item["economic_default_promotion"] for item in result["coverage_inventory"])
    assert len(result["product_gates"]) == 10


def test_guide_and_seals_are_unchanged_by_read_only_inventory():
    names = (trace.GUIDE, *(trace.PUBLIC + p.seal for p in trace.PHASES))
    before = {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    trace.build_inventory(ROOT)
    assert before == {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def test_reference_to_missing_current_reports_cannot_fabricate_installed_qualification():
    result = trace.build_inventory(ROOT, current_reports=(
        "docs/mode5/__m512_missing_traceability_control__.md",
        "docs/mode5/__m512_missing_traceability_control__.json"))
    final = result["phases"][-1]
    assert final["markdown"]["status"] == "MISSING"
    assert final["json"]["status"] == "MISSING"
    assert not final["current_installed_certificate"]
    assert not result["package_qualified"]
    assert all(row["evidence_state"] == "MAIN_CURRENT_QUALIFICATION_REQUIRED"
               for row in result["requirements"][110:])
