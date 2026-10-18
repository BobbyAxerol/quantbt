"""Public report/phase consistency only; private alpha evidence stays private."""
import ast
import json
from pathlib import Path

from tools.check_docs_links import validate_links

ROOT = Path(__file__).resolve().parents[1]


def test_m509_public_summary_is_scoped_and_reconciled():
    d = json.loads((ROOT / "docs/mode5/evidence/m5-09.json").read_text())
    assert d["status"] == "COMPLETE_LOCAL_DOSSIER_GOVERNANCE"
    assert d["alpha_count"] == 5 and d["matrix_count"] == 30
    assert sum(d["matrix_records"].values()) == 1659
    assert (d["reconciled_short_cells"], d["reconciled_historical_requests"],
            d["reconciled_sampler_trials"], d["reconciled_formula_decisions"]) == (193, 53, 64, 40)
    assert d["plan_counts"] == {"DEFER_CALIBRATION": 5} and d["sealed_search_budget"] == 0
    assert d["related_tests_passed"] == 1230 and d["focused_governance_tests"] == 52
    assert d["failed_tests"] == d["skipped_tests"] == 0
    assert d["maximum_retained_accounting_diff"] == d["new_financial_executions"] == d["new_sampler_trials"] == 0
    for key in ("automatic_routing_qualified", "economic_confirmation", "private_code_exported",
                "installed_artifact_certificate", "next_phase_authorized", "build_ci_push_or_publish_authorized"):
        assert d[key] is False
    assert "/root/" not in json.dumps(d)
    assert len(d["private_report_sha256"]) == 64


def test_m509_current_plan_status_and_historical_receipts_are_distinct():
    text = (ROOT / "upgrade/implement.md").read_text()
    phase = text.split('### Phase M5-09 -', 1)[1].split('<a id="mode5-m5-10">', 1)[0]
    assert "COMPLETE_LOCAL_DOSSIER_GOVERNANCE" in phase
    assert "DEFER_CALIBRATION" in phase and "zero" in phase
    assert "M509.01..06" in phase and "M5T-081..090" in phase
    top = text.split('## Current Mode 5 Diagnostics-First Upgrade -', 1)[1].split('\n## ', 1)[0]
    assert "M4-ML-09" in top and "M5-11.7" in top
    next_phase = text.split('### Phase M5-10 -', 1)[1].split('### Phase M5-11 -', 1)[0]
    assert "COMPLETE_LOCAL_PUBLIC_OPT_IN" in next_phase
    package_phase = text.split('### Phase M5-12 -', 1)[1].split('\n### ', 1)[0]
    assert "NOT_STARTED" in package_phase and "package gates remain NOT_RUN" in package_phase
    # The historical M5-09 receipt is not rewritten as later approval/progress.
    old = json.loads((ROOT / "docs/mode5/evidence/m5-09.json").read_text())
    assert old["next_phase_authorized"] is False


def test_m509_contract_report_and_cleanup_links_and_limits():
    paths = [ROOT / p for p in ("docs/mode5/DOSSIER_GOVERNANCE_V1.md",
        "docs/mode5/M5_09_DOSSIER_REPORT.md", "docs/maintenance/M5_09_CLEANUP.md", "upgrade/implement.md")]
    assert not validate_links(ROOT / "docs", check_anchors=True, files=paths)
    report = paths[1].read_text()
    for term in ("1,230", "NO_CLEAR_WINNER", "DEFER_CALIBRATION", "182.35", "2.415", "2.236",
                 "not", "not six independent", "M5-10", "M5-11", "Failures are retained"):
        assert term in report
    contract = " ".join(paths[0].read_text().split())
    for term in ("RAW_ONLY", "no", "null", "chronology", "selection rights", "immutable", "reuse"):
        assert term.lower() in contract.lower()


def test_m509_tools_are_research_metadata_not_a_financial_engine():
    for path in (ROOT / "tools/mode5_dossier").glob("*.py"):
        tree = ast.parse(path.read_text())
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & {"backtest", "simulate", "create_study", "optimize", "request", "read_csv"}
        assert "upgrade/alphas" not in path.read_text()
