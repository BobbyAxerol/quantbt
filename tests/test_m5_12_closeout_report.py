"""Finance-free rendering of synthetic canonical phase facts, never certificates."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from tools import m5_12_closeout_report as closeout
from tools.m5_12_traceability import REPORT_FIELDS


def _report():
    return dict(
        schema="quantbt.mode5_upgrade.phase_report.v1", phase_id="M5-12",
        status="BLOCKED_SYNTHETIC_FIXTURE", scientific_status="INCONCLUSIVE",
        source_identity=dict(source_commit="a" * 40, scope="synthetic renderer test only"),
        input_artifacts=[dict(kind="wheel", path="fixtures/not-present.whl", sha256="b" * 64, status="NOT_RUN")],
        alpha_scope=["SYNTHETIC"], hypotheses_tested=["renderer preserves supplied fields"],
        requirements=[dict(id="M5T-111", status="NOT_EVALUATED", evidence=[], limits=["no timing study"])],
        reuse_dispositions=[dict(receipt="fixtures/history.json", disposition="HISTORICAL_ONLY")],
        test_runs=[dict(id="synthetic", counts=dict(tests=7, passed=4, failures=1, skipped=2),
                       exit_code=1, log=dict(path="fixtures/not-present.log", sha256="c" * 64))],
        numeric_results=[dict(name="large integer", value=9_007_199_254_740_993, unit="synthetic_count"),
                         dict(name="finite value", value=0.1234567890123456, unit="synthetic_unit", support=None)],
        matrices=[], economic_interpretation=dict(supported=[], not_supported=["no economics tested"],
            inconclusive=["synthetic fixture only"], alternative_explanations=[]),
        proof_capability=dict(positive_controls=["input binding"], null_controls=["wrong hash rejected"],
                              coverage="renderer only", vacuous_checks=["no financial executions"]),
        potential_assessment=dict(evidence=["synthetic control"], bottlenecks=["qualification pending"],
                                  next_falsifiable_actions=["main supplies actual receipts"]),
        performance=dict(status="NOT_MEASURED"), data_roles=["synthetic"],
        blocking_issues=[dict(issue="qualification pending", owner="fixture")], review=dict(status="UNREVIEWED"),
        protected_sources_unchanged=False,
        reproduction=dict(command=["python", "-m", "tools.m5_12_closeout_report"]), next_phase_ready=False,
        traceability=dict(status="PARTIAL", all_120_pass=False, artifact_ref="fixtures/trace.json"),
    )


def _bytes(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def _render(value):
    raw = _bytes(value)
    return closeout.render_closeout(raw, expected_sha256=sha256(raw).hexdigest())


def _recover(markdown):
    result = {}
    for match in re.finditer(r"(?m)^(`{3,})json\n([\s\S]*?)\n\1$", markdown):
        section = json.loads(match[2])
        assert not result.keys() & section.keys()
        result.update(section)
    return result


def test_exact_recorded_numbers_statuses_artifacts_and_limits_are_preserved():
    report = _report()
    rendered = _render(report)
    assert _recover(rendered) == report
    assert "9007199254740993" in rendered
    assert "BLOCKED_SYNTHETIC_FIXTURE" in rendered
    assert "HISTORICAL_ONLY" in rendered and "NOT_EVALUATED" in rendered
    assert "## Proof Capability" in rendered and "## Requirements And Traceability" in rendered
    assert "## Additional Recorded Evidence" in rendered
    assert "all 120 PASS" not in rendered
    # Nonexistent receipt/artifact references are data, never file reads.
    assert "fixtures/not-present.whl" in rendered and "fixtures/not-present.log" in rendered


def _consumers():
    return [
        dict(kind="synthetic-pair", feature_cases=7, execution_cases=3, pct_cases=0,
             integrated_families=2, private_alpha_controls=None, representative_reports=1, status="NONPASS"),
        dict(kind="synthetic-sdist", feature_cases=None, execution_cases=None, pct_cases=9,
             integrated_families=0, private_alpha_controls=None, representative_reports=0, status=None),
    ]


def _consumer_table(rendered):
    return rendered.split("\n## Installed Consumers\n\n", 1)[1].split("\n\n", 1)[0]


def test_readable_summary_uses_recorded_status_and_source_without_inference():
    report = _report()
    rendered = _render(report)
    summary = rendered.split("\n## Recorded Summary\n\n", 1)[1].split("\n\n", 1)[0]
    assert "| Phase Status | BLOCKED\\_SYNTHETIC\\_FIXTURE |" in summary
    assert "| Scientific Status | INCONCLUSIVE |" in summary
    assert "| Next Phase Ready | false |" in summary
    assert "| source\\_identity.source\\_commit | " + "a" * 40 + " |" in summary
    assert _recover(rendered) == report


def test_optional_table_preserves_exact_supplied_counts_nonpass_and_nulls():
    report = _report()
    report["matrices"] = dict(installed_consumers=_consumers())
    rendered = _render(report)
    assert _consumer_table(rendered) == (
        "| Kind | Feature Cases | Execution Cases | Pct-Equity Cases | Integrated Families | "
        "Private Alpha Controls | Representative Reports | Recorded Status |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n"
        "| synthetic-pair | 7 | 3 | 0 | 2 | null | 1 | NONPASS |\n"
        "| synthetic-sdist | null | null | 9 | 0 | null | 0 | null |"
    )
    assert _recover(rendered) == report
    assert "Total" not in _consumer_table(rendered)
    for title, fields in closeout.SECTIONS:
        assert "\n## " + title + "\n\n" + closeout._block({key: report[key] for key in fields}) in rendered


def test_summary_and_consumer_table_escape_pipes_newlines_and_markup():
    report = _report()
    report["status"] = "NONPASS | waiting\nreview"
    report["source_identity"] = dict(source_commit="recorded|commit\r\nnot-certified")
    report["matrices"] = dict(installed_consumers=_consumers())
    row = report["matrices"]["installed_consumers"][0]
    row["kind"] = "synthetic|pair\nnext"
    row["status"] = "[NONPASS](link)|pending\r\n<script>"
    rendered = _render(report)
    table = _consumer_table(rendered)
    assert "synthetic&#124;pair<br>next" in table
    assert "\\[NONPASS\\]\\(link\\)&#124;pending<br>&lt;script&gt;" in table
    assert all(line.count("|") == 9 for line in table.splitlines())
    assert "NONPASS &#124; waiting<br>review" in rendered
    assert "recorded&#124;commit<br>not-certified" in rendered
    assert _recover(rendered) == report


@pytest.mark.parametrize("matrices", [[], None, {}, {"installed_consumers": None}, {"installed_consumers": []}])
def test_missing_optional_consumer_list_does_not_create_counts(matrices):
    report = _report()
    report["matrices"] = matrices
    rendered = _render(report)
    assert "## Installed Consumers" not in rendered
    assert _recover(rendered) == report


def test_consumer_table_missing_column_does_not_silently_fill_zero():
    report = _report()
    report["matrices"] = dict(installed_consumers=_consumers())
    del report["matrices"]["installed_consumers"][0]["pct_cases"]
    with pytest.raises(ValueError, match="every recorded column"):
        _render(report)


@pytest.mark.parametrize("field", REPORT_FIELDS)
def test_every_required_canonical_field_is_validated(field):
    report = _report()
    del report[field]
    with pytest.raises(ValueError, match="missing phase report fields"):
        _render(report)


def test_test_count_only_is_not_a_phase_report():
    with pytest.raises(ValueError, match="missing phase report fields"):
        _render(dict(phase_id="M5-12", status="PASS", tests=120))


@pytest.mark.parametrize("field", ["proof_capability", "potential_assessment", "reproduction"])
def test_empty_required_substantive_sections_fail(field):
    report = _report()
    report[field] = {}
    with pytest.raises(ValueError, match="substantive report section"):
        _render(report)


@pytest.mark.parametrize("change", ["bytes", "numeric_value", "status", "artifact"])
def test_mutated_input_cannot_reuse_original_hash(change):
    report = _report()
    raw = _bytes(report)
    if change == "bytes":
        changed = raw + b"\n"
    else:
        updated = deepcopy(report)
        if change == "numeric_value":
            updated["test_runs"][0]["counts"]["passed"] += 1
        elif change == "status":
            updated["status"] = "COMPLETE"
        else:
            updated["input_artifacts"][0]["sha256"] = "d" * 64
        changed = _bytes(updated)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        closeout.render_closeout(changed, expected_sha256=sha256(raw).hexdigest())


@pytest.mark.parametrize("digest", ["", "0" * 63, "Z" * 64, None])
def test_malformed_hash_fails_before_rendering(digest):
    with pytest.raises(ValueError, match="expected SHA256"):
        closeout.render_closeout(_bytes(_report()), expected_sha256=digest)


def test_wrong_well_formed_hash_fails():
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        closeout.render_closeout(_bytes(_report()), expected_sha256="0" * 64)


def test_input_size_is_bounded_before_parsing(monkeypatch):
    raw = _bytes(_report())
    monkeypatch.setattr(closeout, "MAX_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="bounded canonical phase JSON bytes"):
        closeout.render_closeout(raw, expected_sha256=sha256(raw).hexdigest())


def test_duplicate_fields_fail_even_when_input_hash_matches():
    raw = b'{"phase_id":"M5-12","phase_id":"M5-01"}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        closeout.render_closeout(raw, expected_sha256=sha256(raw).hexdigest())


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity", b"1e10000"])
def test_nonfinite_numbers_are_not_rendered(token):
    report = _report()
    report["invalid_number"] = "FLOAT_TOKEN"
    raw = _bytes(report).replace(b'"FLOAT_TOKEN"', token)
    with pytest.raises(ValueError):
        closeout.render_closeout(raw, expected_sha256=sha256(raw).hexdigest())


def test_other_phase_is_not_relabelled_as_closeout():
    report = _report()
    report["phase_id"] = "M5-11"
    with pytest.raises(ValueError, match="requires phase M5-12"):
        _render(report)


@pytest.mark.parametrize("field", ["status", "scientific_status"])
def test_missing_recorded_status_is_not_inferred(field):
    report = _report()
    report[field] = None
    with pytest.raises(ValueError, match="explicit recorded status"):
        _render(report)


def test_markdown_fence_content_stays_recorded_data():
    report = _report()
    report["review"]["note"] = "```\n# NOT AN ACTUAL PASS\n````\n[link](file:///private)"
    assert _recover(_render(report)) == report


def _arguments(tmp_path):
    source = tmp_path / "report.json"
    source.write_bytes(_bytes(_report()))
    output = tmp_path / "report.md"
    return ["--input", str(source), "--expected-sha256", sha256(source.read_bytes()).hexdigest(),
            "--output", str(output)], source, output


def test_cli_writes_fresh_output_and_never_overwrites(tmp_path):
    args, source, output = _arguments(tmp_path)
    before = source.read_bytes()
    assert closeout.main(args) == 0
    expected = output.read_bytes()
    assert _recover(expected.decode()) == _report()
    with pytest.raises(FileExistsError):
        closeout.main(args)
    assert source.read_bytes() == before and output.read_bytes() == expected


def test_cli_hash_failure_creates_no_output(tmp_path):
    args, source, output = _arguments(tmp_path)
    args[3] = "0" * 64
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        closeout.main(args)
    assert not output.exists() and source.is_file()


@pytest.mark.parametrize("which", ["input", "output"])
def test_cli_rejects_symlinks_without_changing_target(tmp_path, which):
    args, source, output = _arguments(tmp_path)
    target = source if which == "input" else tmp_path / "retained.md"
    if which == "output":
        target.write_bytes(b"retained content\n")
    before = target.read_bytes()
    link = tmp_path / "linked"
    link.symlink_to(target)
    args[1 if which == "input" else 5] = str(link)
    with pytest.raises(ValueError, match="symlink"):
        closeout.main(args)
    assert target.read_bytes() == before and not output.exists()


def test_cli_deterministic_across_fresh_finance_free_processes(tmp_path):
    args, source, first = _arguments(tmp_path)
    probe = (
        "import sys; from tools.m5_12_closeout_report import main; "
        "raise_code = main(); "
        "assert not any(n.split('.')[0] in {'quantbt','_quantbt_native','optuna','numpy','pandas'} "
        "for n in sys.modules); raise SystemExit(raise_code)"
    )
    command = [sys.executable, "-B", "-c", probe]
    root = Path(__file__).resolve().parents[1]
    subprocess.run([*command, *args], cwd=root, check=True, capture_output=True, timeout=30)
    second = tmp_path / "report-second.md"
    args[-1] = str(second)
    subprocess.run([*command, *args], cwd=root, check=True, capture_output=True, timeout=30)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text() == closeout.render_closeout(source.read_bytes(), expected_sha256=args[3])
