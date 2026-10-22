"""Actual public synthetic endpoint reports; no real-alpha economic authority."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from quantbt import QuantBTEndpoint
from quantbt.mode5 import DecisionReport
from quantbt.mode5.runtime import Mode5NoSelectionError

from public_fixtures import public_setup
from test_continuous_runtime import continuous_setup


@pytest.mark.parametrize("continuous", [False, True])
def test_actual_public_result_is_cold_reportable_without_rng_or_finance(tmp_path, continuous):
    factory = continuous_setup if continuous else public_setup
    endpoint, frame, ranges, calibration = factory(tmp_path / "selected", trials=6)
    result = endpoint.backtest(data=frame, param_ranges=ranges)
    wf = result.metadata["walk_forward"]
    metadata = wf["mode5_diagnostics_first"]
    params = wf["best_trial"]["params"]
    before = deepcopy(metadata)
    rng = deepcopy(np.random.get_state())
    journal = calibration.journal.history()
    report = DecisionReport.read(metadata, selected_params=params)
    private = report.to_dict(private=True)
    assert private["selected_params"] == params
    assert private["summary"]["chosen_candidate"] == metadata["decision"]["chosen_candidate"]
    assert private["summary"]["attempts"] == 6
    assert private["runtime"]["sampler"]["ask_tell_digest"] == metadata["sampler"]["ask_tell_digest"]
    assert ("dependent attribution" in private["summary"]["account_semantics"]) is continuous
    assert report.to_dict()["selected_params"] == "REDACTED"
    assert report.to_markdown() and report.to_markdown(private=True)
    assert DecisionReport.from_json(report.to_json(private=True)) == report
    assert metadata == before
    after = np.random.get_state()
    assert rng[0] == after[0] and np.array_equal(rng[1], after[1]) and rng[2:] == after[2:]
    assert calibration.journal.history() == journal


def test_actual_public_no_selection_has_report_and_no_fake_vector(tmp_path):
    endpoint, frame, ranges, _ = public_setup(tmp_path / "no-selection", trials=4, min_utility=99999.)
    with pytest.raises(Mode5NoSelectionError) as caught:
        endpoint.backtest(data=frame, param_ranges=ranges)
    report = DecisionReport.read(caught.value.mode5_metadata)
    assert report.to_dict(private=True)["summary"]["selection_status"] == "NO_SELECTION"
    assert report.to_dict(private=True)["selected_params"] is None
    assert report.to_dict()["summary"]["gate_excluded_candidates"]
    assert report.to_markdown()


def test_report_does_not_change_separate_seeded_public_study(tmp_path):
    left, frame, ranges, _ = public_setup(tmp_path / "left", trials=5)
    first = left.backtest(data=frame, param_ranges=ranges)
    wf = first.metadata["walk_forward"]
    DecisionReport.read(wf["mode5_diagnostics_first"], selected_params=wf["best_trial"]["params"]).to_dict(private=True)
    right, other, other_ranges, _ = public_setup(tmp_path / "right", trials=5)
    second = right.backtest(data=other, param_ranges=other_ranges)
    a = wf["mode5_diagnostics_first"]
    b = second.metadata["walk_forward"]["mode5_diagnostics_first"]
    assert [r["effective_params"] for r in a["trial_ledger"]] == [r["effective_params"] for r in b["trial_ledger"]]
    assert [(r["state"], r.get("objective"), r.get("reason")) for r in a["trial_ledger"]] == [
        (r["state"], r.get("objective"), r.get("reason")) for r in b["trial_ledger"]]
    assert a["sampler"]["ask_tell_digest"] == b["sampler"]["ask_tell_digest"]


def test_only_report_extension_legacy_call_uses_original_route(tmp_path):
    endpoint, frame, ranges, _ = public_setup(tmp_path / "controls", trials=4)
    config = replace(endpoint.config, walkforward_config=replace(endpoint.config.walkforward_config, mode5_calibration=None))
    legacy = QuantBTEndpoint(config)
    result = legacy.backtest(data=frame, param_ranges=ranges)
    assert "mode5_diagnostics_first" not in result.metadata["walk_forward"]
    assert len(result.equity) > 0


def test_actual_selected_report_rejects_another_dictionary(tmp_path):
    endpoint, frame, ranges, _ = public_setup(tmp_path / "wrong-vector", trials=4)
    result = endpoint.backtest(data=frame, param_ranges=ranges)
    wf = result.metadata["walk_forward"]
    wrong = {**wf["best_trial"]["params"], "period": -999}
    with pytest.raises(ValueError, match="selected actual dictionary"):
        DecisionReport.read(wf["mode5_diagnostics_first"], selected_params=wrong)
