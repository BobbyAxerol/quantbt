"""Cold probe input-schema regressions; public metadata, no financial execution."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "native_probe_metric_counts_public_fixture",
    Path(__file__).with_name("test_native_batteries.py"),
)
fixture_owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_owner)
b = fixture_owner.b
Record = fixture_owner.Record

BAR_METRICS = ("net_return", "drawdown", "economic_utility")
DAILY_METRICS = ("sharpe", "daily_loss_es")
OBSERVATION_COUNTS = {
    "whole_path": (26280, 1095),
    "2021": (8760, 365),
    "2022": (8760, 365),
    "2023": (8760, 365),
}


@pytest.fixture
def admitted(tmp_path):
    f = fixture_owner.Fixture(tmp_path)
    f.freeze()
    envelope = f.envelope()
    # Shape only public fixture metadata like the admitted hourly-account views.
    for cell in envelope["rows"]:
        value = cell["value"]
        bars, days = OBSERVATION_COUNTS[cell["environment_id"]]
        assert (value["actual_bar_count"], value["calendar_days"]) == (bars, days)
        for metric in value["metrics"]:
            if metric["metric_id"] in {"mode5.panel." + name for name in BAR_METRICS}:
                metric["sample_count"] = bars
        for metric in value["raw_account_metrics"]["metrics"]:
            if metric["metric_id"] in {
                "reporting.account.total_return", "reporting.drawdown.max_depth",
            }:
                metric["sample_count"] = bars
    return f, envelope


def test_load_accepts_exact_bar_and_daily_counts_without_rewriting_views(admitted):
    f, envelope = admitted
    original = deepcopy(envelope)
    sealed = Record.of(original).data
    probe_ref = f.put("mixed-unit-probes", envelope)
    catalog = f.catalog()
    *_, probes = b._load(catalog, dict(
        plan=f.plan_ref, preferences=f.preferences_ref, probe_views=probe_ref,
    ))

    assert set(probes) == {
        (cell["execution_index"], cell["environment_id"]) for cell in original["rows"]
    }
    assert {cell["role"] for cell in original["rows"]} == set(b.ROLES)
    for cell in original["rows"]:
        value, source_ref = probes[cell["execution_index"], cell["environment_id"]]
        assert value == Record.of(cell["value"]).data
        assert catalog.require_ref(source_ref) == Record.of(cell).data
        bars, days = OBSERVATION_COUNTS[cell["environment_id"]]
        metrics = {metric["metric_id"]: metric for metric in value["metrics"]}
        for name in BAR_METRICS:
            assert metrics["mode5.panel." + name]["sample_count"] == bars
            assert metrics["mode5.panel." + name]["unit"] == "decimal_return"
        for name in DAILY_METRICS:
            assert metrics["mode5.panel." + name]["sample_count"] == days
            assert metrics["mode5.panel." + name]["unit"] == (
                "ratio" if name == "sharpe" else "decimal_return"
            )
    assert catalog.require_ref(probe_ref) == sealed
    assert envelope == original


def test_shared_reduction_preserves_source_metric_counts_and_separate_roles(admitted):
    f, envelope = admitted
    original = deepcopy(envelope)
    reduction = f.reduce(envelope)
    catalog = f.catalog()
    observed = [
        row for row in reduction.rows.data["values"]["center_neighbor_environment"]
        if row["operation"] == "probe" and row["status"] == "OBSERVED"
    ]

    assert len(observed) == len(original["rows"])
    seen = set()
    for row in observed:
        projection = row["value"]
        source = catalog.require_ref(projection["original_view_ref"])
        assert projection["metrics"] == source["metrics"]
        assert projection["provenance"] == source["provenance"]
        seen.add((source["provenance"]["data_role"], source["environment_id"]))
    assert seen == {(role, env) for role in b.ROLES for env in OBSERVATION_COUNTS}
    probe_ref = reduction.report.data["input_refs"]["probe_views"]
    assert catalog.require_ref(probe_ref) == Record.of(original).data
    assert envelope == original
    assert reduction.report.data["preferences"] == fixture_owner.PREFERENCES
    assert reduction.report.data["financial_executions"] == 0
    assert not reduction.report.data["phase_complete"]
    assert not reduction.report.data["recipe_approval"]


@pytest.mark.parametrize("role", b.ROLES)
@pytest.mark.parametrize("env", OBSERVATION_COUNTS)
@pytest.mark.parametrize("name", DAILY_METRICS)
def test_daily_metric_cannot_claim_hourly_observation_count(admitted, role, env, name):
    f, envelope = admitted
    cell = next(cell for cell in envelope["rows"]
                if cell["role"] == role and cell["environment_id"] == env)
    metric = next(metric for metric in cell["value"]["metrics"]
                  if metric["metric_id"] == "mode5.panel." + name)
    metric["sample_count"] = OBSERVATION_COUNTS[env][0]
    probe_ref = f.put("daily-as-hourly-probes", envelope)

    # The failure must identify this metric, not an unrelated valid bar metric.
    with pytest.raises(ValueError, match=rf"{name}.*observation.*differ"):
        b._load(f.catalog(), dict(
            plan=f.plan_ref, preferences=f.preferences_ref, probe_views=probe_ref,
        ))


@pytest.mark.parametrize("role", b.ROLES)
@pytest.mark.parametrize("env", OBSERVATION_COUNTS)
@pytest.mark.parametrize("name", BAR_METRICS)
def test_hourly_metric_cannot_claim_daily_observation_count(admitted, role, env, name):
    f, envelope = admitted
    cell = next(cell for cell in envelope["rows"]
                if cell["role"] == role and cell["environment_id"] == env)
    metric = next(metric for metric in cell["value"]["metrics"]
                  if metric["metric_id"] == "mode5.panel." + name)
    metric["sample_count"] = OBSERVATION_COUNTS[env][1]
    probe_ref = f.put("hourly-as-daily-probes", envelope)

    with pytest.raises(ValueError, match=rf"{name}.*observation.*differ"):
        b._load(f.catalog(), dict(
            plan=f.plan_ref, preferences=f.preferences_ref, probe_views=probe_ref,
        ))
