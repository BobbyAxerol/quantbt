import json
from pathlib import Path

import pytest

from tools import qms_pre05_qualification as gate
from tools.qms_pre05_profile_matrix import registered_profile_cells


@pytest.fixture
def artifact_tree(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    cost = json.loads(
        (
            root / "benchmarks/optimization/meta_selection/qms_pre_e06_05_cost.json"
        ).read_text()
    )
    lane = tmp_path / ".maturin/qms08/pre-e06-05"
    lane.mkdir(parents=True)
    output = (
        tmp_path / "benchmarks/optimization/meta_selection/qms_pre_e06_05_cost.json"
    )
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(cost))
    output.with_suffix(".md").write_text("Synthetic artifact-inventory fixture.\n")
    registration = dict(
        entry=gate.ENTRY,
        warm_repeats=21,
        numeric_threads=1,
        disabled_budget=dict(owner_approved=True, p50_pct=3, p95_pct=5),
        cells=[dict(id=r["cell"]) for r in cost["rows"]],
    )
    (lane / "registration.json").write_text(json.dumps(registration))
    profiles = []
    for cell in registered_profile_cells(cost):
        for arm in ("reference", "optimized"):
            path = lane / "profiles" / f"isolated-{arm}-{cell.identity}.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text("{}")
            path.with_suffix(".pstats").write_bytes(b"inventory fixture")
            profiles.append(str(path.relative_to(tmp_path)))
    (lane / "isolated-profiles.json").write_text(json.dumps(profiles))
    (lane / "profile-summary.json").write_text("{}")
    history = lane / "history/domain-pct_equity.json"
    history.parent.mkdir()
    history.write_text("[]")
    block = dict(
        run_context="isolated",
        warm_pairs=21,
        calls_per_arm_sample=50,
        financial_calls=0,
        exact_portable_parity=True,
        full_wfo_speed_claim=False,
        history_sha256=gate.file_hash(history),
    )
    (lane / "portable-block-cost-isolated.json").write_text(json.dumps(block))
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    return lane, cost


def test_primary_artifacts_all_bound(artifact_tree):
    lane, cost = artifact_tree
    hashes = gate.artifact_inventory(lane, cost)
    assert len(hashes) == 67
    assert all(len(value) == 64 for value in hashes.values())


@pytest.mark.parametrize("mutation", ("cost", "registration", "profiles", "block"))
def test_changed_or_incomplete_primary_artifacts_rejected(artifact_tree, mutation):
    lane, cost = artifact_tree
    if mutation == "cost":
        cost["rows"][0]["p50_change_pct"] = 999
    elif mutation == "registration":
        path = lane / "registration.json"
        value = json.loads(path.read_text())
        value["warm_repeats"] = 3
        path.write_text(json.dumps(value))
    elif mutation == "profiles":
        path = lane / "isolated-profiles.json"
        value = json.loads(path.read_text())
        value[-1] = value[0]
        path.write_text(json.dumps(value))
    else:
        path = lane / "portable-block-cost-isolated.json"
        value = json.loads(path.read_text())
        value["financial_calls"] = 1
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        gate.artifact_inventory(lane, cost)
