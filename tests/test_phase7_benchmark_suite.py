from __future__ import annotations

import json

from quantbt.benchmarks.run_phase7 import PROFILES, _markdown_report, _skipped


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
    with open("benchmarks/phase7_thresholds.json", "r", encoding="utf-8") as fh:
        thresholds = json.load(fh)

    assert thresholds["native_vectorized"]["standard_max_seconds_per_million_bar_symbols"] > 0
    assert thresholds["native_event"]["standard_max_seconds_per_100k_orders"] > 0
