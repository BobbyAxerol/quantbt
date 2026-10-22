"""Publish-safe M5-10 handoff arithmetic and scope, without private evidence."""
from pathlib import Path
import json
from statistics import median

import pytest


ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "docs/mode5/evidence/m5-10.json"


def evidence():
    return json.loads(SUMMARY.read_text())


def test_current_public_gate_does_not_claim_release_or_economics():
    row = evidence()
    assert row["status"] == "COMPLETE_LOCAL_PUBLIC_OPT_IN"
    assert not row["publication"] and not row["deployment_authorized"]
    assert not row["independent_economics_claim"]
    assert row["deferred_real_plans_unchanged"]
    assert row["requirements"] == [f"M5T-{n:03d}" for n in range(91, 101)]
    assert row["source"]["distinct_cases"] < sum(
        p["passed"] for p in row["source"]["overlapping_panels"]
    )
    assert all(p["failed"] == p["skipped"] == 0 for p in row["source"]["overlapping_panels"])
    assert row["next"]["M5-11"] == row["next"]["M5-12"] == "NOT_STARTED"


def test_benchmark_numbers_and_work_units_reconcile():
    row = evidence()["benchmark"]
    assert row["matched_outputs"] and row["threads"] == 1
    warm = row["fully_warm"]
    off, on = median(warm["off_seconds"]), median(warm["on_seconds"])
    assert 100 * (1 - on / off) == pytest.approx(warm["median_time_reduction_percent"])
    assert not warm["meaningful_speedup_claim"] and not warm["rss_reduction_claim"]
    assert max(warm["on_rss_mib"]) > max(warm["off_rss_mib"])
    assert row["cache_start"]["reporting_kernel_warm"] is False
    assert warm["reporting_kernel_warm"] is True
    bill = row["billing"]
    assert bill["effective_candidates"] == bill["query_attempts"] == 16
    assert bill["original_account_observations"] == bill["effective_candidates"] + 1
    assert bill["final_account_execution_separate"] and bill["includes_selected_audit"]
    assert bill["heavy_trial_reports"] == 0
    assert bill["equity_daily_components_retained"] and not bill["native_scalar_score_eligible"]


def test_artifact_and_private_controls_have_honest_scope():
    row = evidence()
    installed = row["installed"]
    assert installed["source_exact"] and installed["privacy_allowlist"]
    assert installed["canonical_python_modules"] == 308
    assert not installed["checkout_import_fallback"]
    assert len(installed["consumers"]) == 2
    assert all(p["passed"] == 50 and p["failed"] == p["skipped"] == 0
               for p in installed["consumers"])
    assert all(len(digest) == 64 for digest in installed["sha256"].values())
    repair = installed["native_artifact_repair"]
    assert not repair["rust_source_changed"]
    assert repair["new_installed_capability_verified"]
    controls = row["actual_alpha_controls"]
    assert controls["source_wheel_sdist_exact"]
    assert controls["maximum_accounting_difference"] == 0
    assert controls["coordinates_per_alpha"] == 1
    assert len(controls["aliases"]) == 5
    assert controls["aliases"][0]["accepted_fills"] is None
    payload = SUMMARY.read_text()
    for forbidden in ("/root/", "alphas_storage", "frozen_params", "selected_params"):
        assert forbidden not in payload


def test_cleanup_and_current_plan_are_not_stale():
    row = evidence()["cleanup"]
    assert row["deleted"] == [".maturin/mode5-m510/attempt-01"]
    assert row["active_scratch_references"] == row["inspection_errors"] == 0
    assert row["protected_verified"] == evidence()["source"]["protected_hashes"]
    assert row["observed_free_change_bytes"] == 405250048
    assert row["consumers_require_fresh_reinstall"]
    plan = (ROOT / "upgrade/implement.md").read_text()
    phase = plan.split('<a id="mode5-m5-10"></a>', 1)[1].split('<a id="mode5-m5-11"></a>', 1)[0]
    assert "**Status:** COMPLETE_LOCAL_PUBLIC_OPT_IN / TECHNICALLY_VALID" in phase
    assert "**Actual Exit Receipt" in phase
    assert "M5_10_PUBLIC_RUNTIME_REPORT.md" in plan.split("## Historical Post-Simulation", 1)[0]
