"""Run the self-contained example without test-fixture or private-alpha imports."""
from pathlib import Path
import json
import runpy

import pytest


def test_synthetic_demo_measures_before_seal_search_and_actual_report(tmp_path):
    example = runpy.run_path(str(Path(__file__).resolve().parents[2] / "examples/mode5_synthetic_decision.py"))
    root = tmp_path / "demo"
    report = example["run_demo"](root)
    data = report.to_dict(private=True)
    assert data["summary"]["attempts"] == 6
    assert data["runtime"]["status"] == "SELECTED_REPLAY_VERIFIED"
    assert data["selected_params"]["period"] in range(6, 25)
    assert data["runtime"]["deployment_authorized"] is False
    assert report.to_dict()["selected_params"] == "REDACTED"
    inputs = json.loads((root / "diagnostic-inputs.json").read_text())
    assert len(inputs["panel"]) == 8
    assert all(row["observation"]["daily_count"] == 32 for row in inputs["panel"])
    assert all(row["observation"]["finance"]["equity"] for row in inputs["panel"])
    assert inputs["matrices"]["recipe_split_seed"]["status"] == "NOT_RUN"
    with pytest.raises(FileExistsError):
        example["run_demo"](root)
