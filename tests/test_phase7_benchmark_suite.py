from __future__ import annotations

import json
from pathlib import Path

from quantbt.benchmarks.run_phase7 import PROFILES, _markdown_report, _skipped
from quantbt.benchmarks.profile_phase7 import BackendProfile, ProfileStage, markdown_report


def test_phase7_profiles_cover_required_dimensions():
    assert {"smoke", "standard", "large"} <= set(PROFILES)
    assert PROFILES["standard"].bars > PROFILES["smoke"].bars
    assert PROFILES["standard"].symbols > PROFILES["smoke"].symbols
    assert PROFILES["standard"].order_count > PROFILES["smoke"].order_count


def test_phase7_markdown_report_includes_backend_status():
    profile = PROFILES["smoke"]
    record = _skipped("nautilus", profile, "optional")

    report = _markdown_report([record], profile)

    assert "Phase 7 Benchmark Results" in report
    assert "nautilus" in report
    assert "skipped" in report


def test_phase7_threshold_file_is_valid_json():
    package_root = Path(__file__).resolve().parents[1]
    with open(package_root / "benchmarks" / "phase7_thresholds.json", "r", encoding="utf-8") as fh:
        thresholds = json.load(fh)

    assert thresholds["native_vectorized"]["standard_max_seconds_per_million_bar_symbols"] > 0
    assert thresholds["native_event"]["standard_max_seconds_per_100k_orders"] > 0
    assert thresholds["native_event_prepared"]["standard_max_seconds_per_100k_orders"] > 0
    assert thresholds["portfolio_legacy"]["standard_max_seconds_per_million_bar_symbols"] > 0
    assert thresholds["native_portfolio"]["standard_max_seconds_per_million_bar_symbols"] > 0


def test_phase7_profile_markdown_includes_stage_breakdown():
    stage = ProfileStage(
        backend="native_event",
        profile="smoke",
        stage="order_array_construction",
        seconds=0.1,
        percent_of_profile=75.0,
        repeats=1,
        notes="sort orders",
    )
    report = markdown_report(
        [
            BackendProfile(
                backend="native_event",
                profile="smoke",
                bars=100,
                symbols=2,
                orders=10,
                total_seconds=0.1,
                stages=[stage],
            )
        ]
    )

    assert "Phase 7 Profiling Results" in report
    assert "order_array_construction" in report
    assert "Cython/C++" in report
