import json
from pathlib import Path

from quantbt import (
    CertificationLevel,
    alpha_report_markdown,
    build_alpha_certification_report,
    certify_result_metadata,
    classify_alpha_source,
    scan_alpha_directory,
)
from quantbt.benchmarks.run_phase31_intrabar import make_markdown, run_benchmark
from tools.audit_alpha_execution_contracts import main as audit_main


def test_phase31d_classifies_execution_sensitive_sources():
    close = classify_alpha_source("native = QuantBTEndpoint.pct_equity(); signal = df['pos_weight']")
    assert close.required_engine == "close_target_v2"
    assert close.current_backend == "legacy_pct_equity"
    assert close.certification_level == int(CertificationLevel.LEGACY)

    intrabar = classify_alpha_source("df['exit_price'] = df['low']; slpercent = 2.0; tppercent = 3.0")
    assert intrabar.required_engine == "intrabar_bracket_v1"
    assert intrabar.uses_stop
    assert intrabar.uses_take_profit
    assert intrabar.uses_custom_exit_price

    replay = classify_alpha_source("fills_df = compact_fill[['bar_index', 'sequence', 'qty', 'price']]")
    assert replay.required_engine == "fill_replay_v1"
    assert replay.certification_level == int(CertificationLevel.ACCOUNTING_REPLAY)

    grid = classify_alpha_source("hedge_type='dca_ladder'; safety_order = 1; grid = True")
    assert grid.required_engine == "event_lifecycle_v2"
    assert grid.uses_grid_or_dca


def test_phase31d_certifies_result_metadata_levels():
    assert certify_result_metadata({"engine_id": "fill_replay_v1"})["certification_level"] == 1
    assert certify_result_metadata({"engine_id": "intrabar_bracket_v1"})["certification_level"] == 2
    assert certify_result_metadata({"engine_id": "intrabar_bracket_v1", "cross_backend_parity_passed": True})["certification_level"] == 3
    assert certify_result_metadata({"backend": "nautilus"})["certification_level"] == 4
    assert certify_result_metadata({"engine_id": "close_target_v2", "certification_status": "uncertified_intrabar_columns_on_close_target"})["certification_level"] == 0


def test_phase31d_scanner_and_report_markdown(tmp_path: Path):
    (tmp_path / "alpha_close.py").write_text("signal_notional = True\npos_weight = 1", encoding="utf-8")
    (tmp_path / "alpha_intrabar.py").write_text("exit_price = df['low']\ntrailing_stop = 0.01", encoding="utf-8")
    (tmp_path / "skip.bin").write_bytes(b"ignored")

    items = scan_alpha_directory(tmp_path)
    report = build_alpha_certification_report(items)
    markdown = alpha_report_markdown(report)

    assert report["total"] == 2
    assert report["by_required_engine"]["close_target_v2"] == 1
    assert report["by_required_engine"]["intrabar_bracket_v1"] == 1
    assert "alpha_intrabar" in markdown


def test_phase31d_audit_cli_writes_artifacts(tmp_path: Path):
    source_dir = tmp_path / "alphas"
    source_dir.mkdir()
    (source_dir / "alpha.py").write_text("fill_replay(fills_df)", encoding="utf-8")
    json_out = tmp_path / "report.json"
    md_out = tmp_path / "report.md"

    rc = audit_main([str(source_dir), "--json-out", str(json_out), "--md-out", str(md_out)])

    assert rc == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["total"] == 1
    assert payload["items"][0]["required_engine"] == "fill_replay_v1"
    assert "Alpha Execution Certification Report" in md_out.read_text(encoding="utf-8")


def test_phase31d_benchmark_smoke_is_parity_safe():
    report = run_benchmark(rows=512, repeats=1, seed=31)
    routes = {row["route"]: row for row in report["records"]}

    assert routes["intrabar_bracket_v1_audit"]["parity"] == "pass"
    assert routes["intrabar_bracket_v1_minimal"]["runtime_seconds"] > 0.0
    assert routes["fill_replay_v1_kernel"]["fills_or_orders"] == routes["intrabar_bracket_v1_audit"]["fills_or_orders"]
    assert report["summary"]["intrabar_minimal_speedup_vs_reference"] > 0.0
    assert "Phase 31 Intrabar Benchmark" in make_markdown(report)
