"""Budget failures remain failures; missing scientific work stops cost reports."""

from copy import deepcopy
import json

import pytest

from tools.qms_pre05_analysis import summarize
from tools.qms_pre05_workloads import cells


def payload():
    rows = []
    for i in range(-1, 21):
        for arm in ("reference", "optimized"):
            rows.append(
                dict(
                    arm=arm,
                    repeat=i,
                    warmup=i == -1,
                    wall_seconds=1.0,
                    cpu_seconds=0.9,
                    after=dict(rss_mib=100.0),
                    observer_failures=0,
                    observer_attempts=0,
                    auxiliary_outer_is_evaluations=0,
                    numeric={},
                    semantic_sha256="same",
                )
            )
    return dict(
        cell=cells()[0].identity,
        warm_repeats=21,
        rows=rows,
        semantic_sha256="same",
        profiled=False,
        process_peak_rss_mib=100.0,
    )


def store(tmp_path, value):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(value))
    return path


def test_point_budgets_are_not_relaxed(tmp_path):
    value = payload()
    assert (
        summarize(store(tmp_path, value), cells()[0])["disabled_point_budget"] == "PASS"
    )
    for row in value["rows"]:
        if row["arm"] == "optimized":
            row["wall_seconds"] = 1.04
    result = summarize(store(tmp_path, value), cells()[0])
    assert result["disabled_point_budget"] == "NOT_MET"
    assert result["p50_change_pct"] == pytest.approx(4.0)
    assert result["cold_comparison_certified"] is False


@pytest.mark.parametrize(
    "field,changed",
    [
        ("observer_failures", 1),
        ("observer_attempts", 1),
        ("auxiliary_outer_is_evaluations", 1),
        ("semantic_sha256", "different"),
    ],
)
def test_cost_evidence_rejects_changed_or_missing_scientific_work(
    tmp_path, field, changed
):
    value = deepcopy(payload())
    value["rows"][4][field] = changed
    with pytest.raises(AssertionError):
        summarize(store(tmp_path, value), cells()[0])
