"""C01 locks source-grounded information roles; proposals cannot enable routes."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.endpoint import _WalkForwardEndpointScorer
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine
from quantbt.optimization.meta_selection.config import validate_meta_route
from tools import qms01_baseline as baseline
from tools.qms_c01_audit import ENTRY, SCHEMA, native_identity, route_receipt, run_trace, verify_receipt
from tools.qms_c01_contracts import CASES, review_case


@pytest.fixture(scope="module")
def traces():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    return {(case.mode, case.schedule): (
        run_trace(case.mode, case.schedule),
        run_trace(case.mode, case.schedule, explicit_off=True),
    ) for case in CASES}


@pytest.fixture(scope="module")
def receipt(traces):
    lanes = []
    for case in CASES:
        base, off = traces[(case.mode, case.schedule)]
        lanes.append(route_receipt(base[0], base[1], base[2],
            off_exact=native_identity(base[0]) == native_identity(off[0]),
            rng_exact=base[3] == off[3]))
    return {"schema": SCHEMA, "activation": False, "protected_source_diff": [],
            "lanes": lanes, "metadata_discrepancies": [
                r["contract"]["mode"] for r in lanes if r["metadata_discrepancy"]]}


def test_c01_t01_inventory_covers_native_routes_without_activating_proposals(receipt):
    assert [(c.mode, c.schedule) for c in CASES] == list(baseline.ROUTES)
    assert sum(c.meta_status == "SUPPORTED_EXISTING" for c in CASES) == 1
    assert verify_receipt(receipt) is receipt
    with pytest.raises(ValueError, match="no native route"):
        review_case("mode_3_flat_minima", "per_fold_causal")


@pytest.mark.parametrize("mode,schedule", baseline.ROUTES)
def test_c01_t02_actual_omitted_and_off_account_pool_and_rng_exact(traces, mode, schedule):
    base, off = traces[(mode, schedule)]
    assert native_identity(base[0]) == native_identity(off[0])
    np.testing.assert_array_equal(base[1].positions, off[1].positions)
    np.testing.assert_array_equal(base[1].equity, off[1].equity)
    np.testing.assert_array_equal(base[1].returns, off[1].returns)
    assert base[3] == off[3]
    assert base[2]._meta_runtime is off[2]._meta_runtime is None
    for pool in base[0]["pools"]:
        assert len(pool["all_trials"]) == baseline.BUDGET["trials_per_study"]
        assert len(pool["eligible_ids"]) >= len(pool["filtered_candidate_ids"])


def test_c01_t03_nested_validation_is_inside_outer_is(traces):
    payload, result, _engine, _rng = traces[("mode_1_decay", "per_fold_causal")][0]
    outer = result.metadata["walk_forward"]["fold_selection_table"]
    for study in payload["studies"]:
        outer_end = pd.Timestamp(outer.loc[outer.study_id == study["study_id"], "train_end"].iloc[0])
        assert len(study["selected"]["fold_metrics"]) >= 2
        assert max(pd.Timestamp(f["test_end"]) for f in study["selected"]["fold_metrics"]) <= outer_end
    assert result.metadata["walk_forward"]["oos_used_for_selection"] is False
    assert all(not r["outer_oos_used_for_selection"] for r in outer.to_dict("records"))


def test_c01_t03_outer_oos_mutation_keeps_first_nested_pool_and_anchor(traces):
    original = traces[("mode_1_decay", "per_fold_causal")][0][0]
    data = baseline.market()
    mask = data.index >= pd.Timestamp("2021-01-01", tz="UTC")
    factor = 1.0 + 0.3 * np.sin(np.arange(mask.sum()) / 3)
    data.loc[mask, ["open", "high", "low", "close"]] *= factor[:, None]
    changed = run_trace("mode_1_decay", "per_fold_causal", data=data)[0]
    assert original["pools"][0] == changed["pools"][0]
    assert original["studies"][0]["selected"] == changed["studies"][0]["selected"]


@pytest.mark.parametrize("case", [c for c in CASES if c.meta_status != "SUPPORTED_EXISTING"])
@pytest.mark.parametrize("meta_mode", ["shadow", "active"])
def test_c01_t04_reviewed_but_unapproved_meta_still_fails_before_finance(monkeypatch, case, meta_mode):
    bt = baseline.endpoint(case.mode, case.schedule)
    config = replace(bt.config.walkforward_config, meta_selection={"mode": meta_mode})

    def forbidden(*args, **kwargs):
        raise AssertionError("unapproved route reached optimizer/scorer")

    monkeypatch.setattr(WalkForwardEngine, "optimize_params", forbidden)
    monkeypatch.setattr(_WalkForwardEndpointScorer, "__call__", forbidden)
    with pytest.raises(ValueError, match="META_METHODOLOGY_UNSUPPORTED"):
        validate_meta_route(config)
    # Mode 2's proxy has an independent route guard; keep its original failure.
    with pytest.raises((ValueError, NotImplementedError), match="META_|meta|endpoint"):
        QuantBTEndpoint(replace(bt.config, walkforward_config=config)).backtest(
            data=baseline.market(), param_ranges={"window": (3, 31, 2)})


@pytest.mark.parametrize("mode,schedule", baseline.ROUTES)
def test_c01_t05_actual_study_count_and_account_parameter_contract(traces, mode, schedule):
    payload, result, _engine, _rng = traces[(mode, schedule)][0]
    wf = result.metadata["walk_forward"]
    assert len(payload["studies"]) == (1 if schedule == "global" else 2)
    if schedule == "global":
        assert wf["params_semantics"] == "single_global_parameter_set"
        assert wf["chronological_validation_claim"] == "not_causal_multi_fold_global_calibration"
    else:
        assert wf["params_semantics"] == "last_completed_fold_selected_params"
    if mode == "mode_5_full_robust":
        fold = payload["studies"][0]["selected"]["fold_metrics"][0]
        assert fold["train_start"] == fold["test_start"]
        assert fold["train_end"] == fold["test_end"]
        assert wf["validation_claim"] == "none_full_sample_calibration"


def test_c01_t05_sbb_real_oos_rerank_is_not_hidden_by_legacy_flag(traces, receipt):
    payload, _result, engine, _rng = traces[("mode_2_sbb", "global")][0]
    finalists = payload["studies"][0]["compact_candidates"]
    selected = payload["studies"][0]["selected"]
    assert engine.config.candidate_selection_metric == "robust_decay"
    assert selected["objective"] == max(r["objective"] for r in finalists)
    assert selected["selection_metadata"]["stage"] == "oos_candidate_selection"
    assert all("oos_sharpe_raw" in f for r in finalists for f in r["fold_metrics"])
    audit = next(r for r in receipt["lanes"] if r["contract"]["mode"] == "mode_2_sbb")
    assert audit["actual_current_outer_OOS_ranking"] is True
    assert audit["metadata_discrepancy"] == (audit["legacy_metadata_OOS_ranking"] is not True)


def test_c01_t05_sbb_last_forward_mutation_keeps_is_pool_but_changes_rerank(traces):
    original = traces[("mode_2_sbb", "global")][0][0]
    data = baseline.market()
    mask = data.index >= pd.Timestamp("2021-04-01", tz="UTC")
    factor = 1.0 + 0.2 * np.sin(np.arange(mask.sum()) / 2.0)
    data.loc[mask, ["open", "high", "low", "close"]] *= factor[:, None]
    changed = run_trace("mode_2_sbb", "global", data=data)[0]
    assert original["pools"] == changed["pools"]
    assert original["studies"][0]["compact_candidates"] != changed["studies"][0]["compact_candidates"]


def test_c01_t05_global_mode4_later_train_changes_shared_is_pool(traces):
    original = traces[("mode_4_is_only_robust", "global")][0][0]
    windows = original["studies"][0]["selected"]["fold_metrics"]
    assert pd.Timestamp(windows[1]["train_end"]) > pd.Timestamp(windows[0]["test_start"])
    data = baseline.market()
    mask = (data.index >= pd.Timestamp("2021-01-01", tz="UTC")) & (
        data.index <= pd.Timestamp("2021-03-31", tz="UTC"))
    factor = 1.0 + 0.3 * np.sin(np.arange(mask.sum()) / 3.0)
    data.loc[mask, ["open", "high", "low", "close"]] *= factor[:, None]
    changed = run_trace("mode_4_is_only_robust", "global", data=data)[0]
    assert original["pools"] != changed["pools"]
    original_trials = original["pools"][0]["all_trials"]
    changed_trials = changed["pools"][0]["all_trials"]
    for before, after in zip(original_trials, changed_trials, strict=True):
        assert before["params"] == after["params"]
        if not before["pruned"]:
            assert before["fold_metrics"][0] == after["fold_metrics"][0]


def test_c01_t07_native_decay_formula_uses_declared_penalized_metrics(traces):
    for case in CASES:
        payload, _result, engine, _rng = traces[(case.mode, case.schedule)][0]
        for study in payload["studies"]:
            selected = study["selected"]
            if selected["selection_metadata"].get("stage") != "oos_candidate_selection":
                continue
            folds = selected["fold_metrics"]
            decay = np.array([f["is_sharpe"] - f["oos_sharpe"] for f in folds])
            std = float(np.std(decay, ddof=1)) if len(decay) > 1 else 0.0
            config = engine.config
            lam = config.decay_lambda if config.candidate_decay_lambda is None else config.candidate_decay_lambda
            gam = config.decay_gamma if config.candidate_decay_gamma is None else config.candidate_decay_gamma
            expected = np.mean([f["oos_sharpe"] for f in folds]) - lam * std - gam * max(0.0, np.mean(decay))
            assert selected["objective"] == pytest.approx(expected, abs=1e-12)


def test_c01_t07_sbb_objective_stays_synthetic_not_real_forward(traces):
    payload, _result, engine, _rng = traces[("mode_2_sbb", "global")][0]
    config = engine.config
    for record in payload["pools"][0]["all_trials"]:
        if record["pruned"]:
            continue
        rows = record["fold_metrics"]
        means = np.array([f["synthetic_oos_sharpe"] for f in rows])
        decay = np.array([f["is_sharpe"] for f in rows]) - means
        expected = means.mean() - config.sbb_decay_lambda * max(0.0, decay.mean()) - config.sbb_std_penalty * np.mean([f["synthetic_oos_std"] for f in rows])
        assert record["objective"] == pytest.approx(expected, abs=1e-12)
        assert all("oos_sharpe_raw" not in f for f in rows)


@pytest.mark.parametrize("mutation", ["activation", "source", "route", "account", "rng", "hide_discrepancy"])
def test_c01_t08_verifier_cannot_turn_review_into_activation(receipt, mutation):
    bad = deepcopy(receipt)
    if mutation == "activation":
        bad["activation"] = True
    elif mutation == "source":
        bad["protected_source_diff"] = ["src/quantbt/walkforward.py"]
    elif mutation == "route":
        bad["lanes"][0]["contract"]["meta_status"] = "SUPPORTED_EXISTING"
    elif mutation == "hide_discrepancy":
        bad["metadata_discrepancies"] = ["made-up"]
    else:
        bad["lanes"][0]["explicit_off_exact" if mutation == "account" else "rng_exact"] = False
    with pytest.raises(ValueError):
        verify_receipt(bad)


def test_c01_t08_protected_financial_guide_and_native_sources_unchanged():
    assert baseline.git("diff", "--name-only", ENTRY, "--", "src", "rust",
                        "pyproject.toml", "uv.lock", baseline.GUIDE) == b""


@pytest.mark.parametrize("mode,schedule", [(c.mode, "per_fold_causal") for c in CASES
    if c.schedule == "global" and c.mode in {"mode_2_sbb", "mode_3_flat_minima", "mode_5_full_robust"}])
def test_c01_t04_does_not_invent_new_native_schedules(mode, schedule):
    with pytest.raises(NotImplementedError):
        WalkForwardConfig(optimization_mode=mode, optimization_schedule=schedule)
