"""C05-T05: real public guards and released-account/RNG paths remain unchanged."""

from dataclasses import replace
import json

import numpy as np
import optuna
import pytest

from quantbt import QuantBTEndpoint
from quantbt.optimization import SamplerConfig, build_sampler
from quantbt.walkforward import WalkForwardEngine
from tools import qms01_baseline as baseline
from tools.qms_c01_audit import native_identity, run_trace
from tools.qms03_history import original_engine_run
from tools.qms_c05_gate import source_lock


MIXED = {"filter": {"kind": "boolean"},
         "x": {"kind": "float", "low": 0.1, "high": 1,
               "active_if": {"filter": True}}}


@pytest.mark.parametrize("parent", [False, True])
def test_c05_t05_conditional_sobol_public_guard_precedes_strategy(monkeypatch, parent):
    ranges = {**MIXED, "filter": parent}
    def forbidden(*args, **kwargs):
        pytest.fail("conditional Sobol reached strategy/account")
    monkeypatch.setattr(WalkForwardEngine, "_call_strategy_for_indices", forbidden)
    bt = baseline.endpoint("mode_4_is_only_robust", "per_fold_causal")
    config = replace(bt.config.walkforward_config, sampler_config=SamplerConfig(name="sobol"))
    with pytest.raises(ValueError, match="conditional ranges are unsupported"):
        QuantBTEndpoint(replace(bt.config, walkforward_config=config)).backtest(
            data=baseline.market(), param_ranges=ranges)


@pytest.mark.parametrize("kind", ["categorical", "conditional", "constraint"])
def test_c05_t05_inadmissible_public_centroid_remains_guarded(monkeypatch, kind):
    def forbidden(*args, **kwargs):
        pytest.fail("mixed centroid reached strategy/account")
    monkeypatch.setattr(WalkForwardEngine, "_call_strategy_for_indices", forbidden)
    ranges = {"x": (0.0, 1.0)}
    kwargs = {}
    if kind == "categorical":
        ranges["kind"] = ["a", "b"]
    elif kind == "conditional":
        ranges = MIXED
    else:
        kwargs["parameter_constraints"] = lambda params: (params["x"] - 0.9,)
    bt = baseline.endpoint("mode_4_is_only_robust", "per_fold_causal")
    config = replace(bt.config.walkforward_config, sampler_config=SamplerConfig(name="tpe_legacy"),
                     flat_selector="centroid", **kwargs)
    with pytest.raises(ValueError, match="centroid.*not qualified"):
        QuantBTEndpoint(replace(bt.config, walkforward_config=config)).backtest(
            data=baseline.market(), param_ranges=ranges)


@pytest.mark.parametrize("name", ["conditional_sobol", "sobol_conditional", "finite_support_projection"])
def test_c05_t05_proposed_contract_is_not_a_fifth_recipe(name):
    with pytest.raises(ValueError):
        build_sampler(SamplerConfig(name=name), seed=42, search_space={"x": (0.0, 1.0)}, objective_count=1)


@pytest.mark.parametrize("mode,schedule", baseline.ROUTES)
def test_c05_t05_existing_eight_routes_match_original_medoid_account_and_rng(mode, schedule):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    stored = json.loads(baseline.MANIFEST.read_text())
    expected = next(r for r in stored["lanes"] if (r["mode"], r["schedule"]) == (mode, schedule))
    actual, _result, _engine = baseline.trace_run(mode=mode, schedule=schedule)
    for field in ("pools", "score_tasks", "equity", "positions", "stitched_signal", "report", "account_contract"):
        assert actual[field] == expected[field], field
    base, off = run_trace(mode, schedule), run_trace(mode, schedule, explicit_off=True)
    assert native_identity(base[0]) == native_identity(off[0])
    assert base[3] == off[3]
    np.testing.assert_array_equal(base[1].equity, off[1].equity)
    np.testing.assert_array_equal(base[1].positions, off[1].positions)


def test_c05_t05_numeric_centroid_still_gets_own_real_is_evaluation():
    _data, _endpoint, _scorer, result, capture = original_engine_run(capture=True, centroid=True)
    for pool in capture.pools:
        assert pool.auxiliary_is_evaluations == 1
        anchor = next(p for p in pool.candidates if p.evaluation_id == pool.anchor_evaluation_id)
        assert anchor.native_trial_id == -1
        assert anchor.observation.verification == "original_result"
        assert dict(anchor.effective_params) == result.metadata["params_by_fold"][pool.fold_id]


def test_c05_t06_all_production_sources_and_old_exact_continuation_are_unchanged():
    result = source_lock()
    assert result["changed_production_files"] == [] and result["production_activation"] is False
    assert result["pair"] == ["1.1.2", "0.4.3"]
    assert result["previous_c04_guard"]["financial_samplers_math_unchanged"] is True
