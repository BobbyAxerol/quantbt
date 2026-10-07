"""Real public scalar/W3 policies, off/shadow accounting and causal witnesses."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from examples.wfo_meta_scalar import market, make_scalar_endpoint, PARAM_RANGES
from examples.wfo_reactive_samplers import configuration, execute, RANGES
from quantbt import QuantBTEndpoint
from quantbt.optimization import SamplerConfig
from quantbt.optimization.meta_selection.config import MetaHistoryContext, MetaSelectionConfig
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.representatives import POLICY
from tests.meta_selection.test_c03_schedulers import assert_accounts

SAMPLER = SamplerConfig(name="sobol", sobol_policy="conditional_numeric_latent_v1")


def endpoint(target="pct_equity", mode="off", full=False):
    original = make_scalar_endpoint(target, mode=mode)
    wf = replace(original.config.walkforward_config, is_subperiods=1, flat_selector=POLICY,
        sampler_config=SAMPLER, **(dict(optimization_mode="mode_5_full_robust", optimization_schedule="global",
        candidate_selection_metric="full_plateau_robust") if full else {}))
    return QuantBTEndpoint(replace(original.config, walkforward_config=wf))


def context():
    return MetaHistoryContext(MetaHistory(), "pre04", "synthetic", "1D", "pre04",
        clock=lambda fold, stage, elapsed: fold.train_index[-1]+pd.Timedelta(
            seconds={"search": 10, "fit": 20, "seal": 30}[stage]))


@pytest.mark.parametrize("target", ["signal_notional", "notional", "unit", "pct_equity", "dca_ladder"])
def test_public_scalar_shadow_account_and_own_anchor(target):
    a, b = endpoint(target), endpoint(target, "shadow")
    tape = market(520)
    ra = a.backtest(data=tape, param_ranges=PARAM_RANGES)
    rb = b.backtest(data=tape, param_ranges=PARAM_RANGES, meta_history=context())
    for key in ("equity", "returns", "positions"):
        np.testing.assert_array_equal(getattr(ra, key), getattr(rb, key))
    ma, mb = (r.metadata["walk_forward"] for r in (ra, rb))
    assert ma["params_by_fold"] == mb["params_by_fold"]
    for sa, sb in zip(ma["sampler_studies"], mb["sampler_studies"], strict=True):
        assert sa["rows"] == sb["rows"]
        assert sa["latent_stream"] == sb["latent_stream"]
    anchor = ma["best_trial"]
    own = anchor["fold_metrics"][0]["meta_observation"]
    selected = anchor["selection_metadata"]
    assert selected["representative_observation"] == own
    assert selected["auxiliary_is_evaluations"] == 0
    assert selected["outer_oos_used_for_selection"] is False


def test_future_data_cannot_change_earlier_selected_anchor_or_qmc():
    a, b = endpoint(), endpoint()
    tape = market(520)
    changed = tape.copy()
    changed.loc[changed.index >= "2021-04-01", ["open", "high", "low", "close"]] *= 2
    ra = a.backtest(data=tape, param_ranges=PARAM_RANGES).metadata["walk_forward"]
    rb = b.backtest(data=changed, param_ranges=PARAM_RANGES).metadata["walk_forward"]
    assert ra["params_by_fold"][0] == rb["params_by_fold"][0]
    assert ra["sampler_studies"][0]["rows"] == rb["sampler_studies"][0]["rows"]
    assert ra["sampler_studies"][0]["latent_stream"] == rb["sampler_studies"][0]["latent_stream"]


def test_mode5_full_is_projection():
    result = endpoint(full=True).backtest(data=market(520), param_ranges=PARAM_RANGES)
    wf = result.metadata["walk_forward"]
    assert wf["n_folds"] == 1
    selected = wf["best_trial"]["selection_metadata"]
    assert selected["representative_policy"] == "qms-feasible-support-projection-v1"
    assert selected["representative_observation"] == wf["best_trial"]["fold_metrics"][0]["meta_observation"]
    assert selected["auxiliary_is_evaluations"] == 0


def w3_config(representative=False, shadow=False):
    c = configuration("sobol", schedule="per_fold_causal", trials=8)
    return replace(c, sampler_config=SAMPLER, flat_selector=POLICY if representative else "medoid",
        meta_selection=MetaSelectionConfig(mode="shadow", label_observer=True, min_matured_origins=12,
            native_batch_policy="auto") if shadow else None)


@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
def test_w3_new_policy_sequential_and_actual_batch(scheduler):
    ranges = {**RANGES, "enabled": [True, False],
        "extra": {"kind": "integer", "low": 1, "high": 3, "active_if": {"enabled": [True]}}}
    c = w3_config()
    if scheduler == "throughput_batch_v1":
        c = replace(c, optimization_schedule="global")
    a = execute(config=c, scheduler=scheduler, ranges=ranges)
    b = execute(config=c, scheduler=scheduler, ranges=ranges)
    assert_accounts(a, b)
    for sa, sb in zip(a.metadata["sampler_studies"], b.metadata["sampler_studies"], strict=True):
        assert sa["rows"] == sb["rows"]
        assert sa["latent_stream"] == sb["latent_stream"]
        assert sa["latent_stream"]["next_qmc_index"] == 7


def test_w3_projection_process_shadow_and_original_accounting():
    cfg = w3_config(representative=True)
    ranges = {**RANGES, "enabled": [True, False],
        "extra": {"kind": "integer", "low": 1, "high": 3, "active_if": {"enabled": [True]}}}
    baseline = execute(config=cfg, ranges=ranges)
    process = execute(config=cfg, worker="process", ranges=ranges)
    shadow = execute(config=w3_config(representative=True, shadow=True), ranges=ranges, meta_history=context())
    assert_accounts(baseline, process)
    assert_accounts(baseline, shadow)
    for a, b in zip(baseline.metadata["sampler_studies"], process.metadata["sampler_studies"], strict=True):
        assert a["rows"] == b["rows"]
        assert a["latent_stream"] == b["latent_stream"]


def test_batch_projection_rejects_before_any_strategy(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("unsupported representative reached strategy")
    # Preparation may precede policy validation; financial strategy must not.
    from examples.wfo_reactive_samplers import Prepared
    monkeypatch.setattr(Prepared, "build_strategy", fail)
    monkeypatch.setattr(Prepared, "build_candidate_batch", fail)
    with pytest.raises(ValueError, match="original sequential IS witnesses"):
        execute(config=w3_config(representative=True), scheduler="throughput_batch_v1")


@pytest.mark.parametrize("mode,schedule", [
    ("mode_1_decay", "global"), ("mode_1_decay", "per_fold_decay"),
    ("mode_1_decay", "per_fold_causal"), ("mode_2_sbb", "global"),
    ("mode_3_flat_minima", "global"), ("mode_4_is_only_robust", "global"),
    ("mode_4_is_only_robust", "per_fold_causal"), ("mode_5_full_robust", "global")])
def test_conditional_sampler_shared_eight_mode_schedule_routes(mode, schedule):
    from tools.qms01_baseline import endpoint as old_endpoint, market as old_market
    old = old_endpoint(mode, schedule)
    c = replace(old.config.walkforward_config, sampler_config=SAMPLER)
    bt = QuantBTEndpoint(replace(old.config, walkforward_config=c))
    ranges = {"window": (3, 31, 2), "on": [True, False],
        "extra": {"kind": "float", "low": .001, "high": 1., "log": True,
                  "active_if": {"on": [True]}}}
    result = bt.backtest(data=old_market(), param_ranges=ranges)
    studies = result.metadata["walk_forward"]["sampler_studies"]
    assert studies
    for s in studies:
        assert s["attempts"] == 6
        assert s["latent_stream"]["next_qmc_index"] == 5
        assert s["latent_stream"]["dimensions"] == ["window", "extra"]


@pytest.mark.parametrize("target", ["signal_notional", "notional", "unit", "pct_equity"])
def test_new_policies_prepared_rust_and_original_witness_parity(target):
    from tests.meta_selection.pre_e06_02_support import account_equal
    original = endpoint(target)
    config = original.config
    wf = replace(config.walkforward_config, metadata={**config.walkforward_config.metadata,
                                                    "native_prepared_wfo": "require"})
    prepared = QuantBTEndpoint(replace(config, walkforward_config=wf, target_runtime="rust"))
    a = original.backtest(data=market(520), param_ranges=PARAM_RANGES)
    b = prepared.backtest(data=market(520), param_ranges=PARAM_RANGES)
    if target == "pct_equity":
        # Legacy schema has no cost columns; do not manufacture those fields.
        for field in ("equity", "returns", "positions"):
            np.testing.assert_array_equal(getattr(a, field), getattr(b, field))
        assert not hasattr(a, "fees") and hasattr(b, "fees")
    else:
        account_equal(a, b)
    x, y = (r.metadata["walk_forward"] for r in (a, b))
    assert x["params_by_fold"] == y["params_by_fold"]
    for sx, sy in zip(x["sampler_studies"], y["sampler_studies"], strict=True):
        assert [r["effective_params"] for r in sx["rows"]] == [r["effective_params"] for r in sy["rows"]]
        assert sx["latent_stream"] == sy["latent_stream"]
    observation = y["best_trial"]["selection_metadata"]["representative_observation"]
    assert observation["verification"] == "original_native_score"


@pytest.mark.parametrize("mode,schedule,metric", [("mode_5_full_robust", "global", "full_plateau_robust"),
    ("mode_4_is_only_robust", "global", "is_only_robust")])
def test_w3_projection_cannot_inherit_scalar_full_sample_admission(mode, schedule, metric, monkeypatch):
    from examples.wfo_reactive_samplers import Prepared
    def fail(*args, **kwargs):
        pytest.fail("unadmitted projection reached financial strategy")
    monkeypatch.setattr(Prepared, "build_strategy", fail)
    cfg = replace(w3_config(representative=True), optimization_mode=mode,
                  optimization_schedule=schedule, candidate_selection_metric=metric, sampler_config=None)
    with pytest.raises(ValueError, match="Mode 4/per_fold_causal"):
        execute(config=cfg)
