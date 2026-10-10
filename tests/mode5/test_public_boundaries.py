"""M5T-091..100 additional public route and scheduler falsification tests."""
from dataclasses import replace
from functools import partial

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.runtime_governance import RuntimeCancellationV1, RuntimeCanceledError
from quantbt.core.wfo_contracts import strategy_fingerprint
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from quantbt.optimization.study_schedule import run_ordered_study
from quantbt.mode5.dossier.plans import CalibrationPlan
from quantbt.mode5.integration_contracts import Mode5Calibration
from quantbt.wfo_execution import execute_window
from public_fixtures import public_setup, alpha


def test_shared_portable_schema_roundtrip_preserves_conditional_geometry():
    import json
    ranges = dict(period=(6, 24, 1), label=["a", "b"], flag={"kind": "boolean"},
        extra={"kind": "float", "low": .1, "high": 1., "active_if": {"flag": True}}, fixed=2)
    space = NormalizedSearchSpace(ranges)
    assert NormalizedSearchSpace(json.loads(json.dumps(space.portable_ranges()))).identity == space.identity


@pytest.mark.parametrize("route", ["intrabar", "event_driven", "order_commands"])
@pytest.mark.parametrize("backend", ["python", "rust"])
def test_actual_execution_window_public_selection_and_audit(tmp_path, route, backend):
    from examples.wfo_meta_execution import market, make_endpoint, strategy
    frame = market(route, end="2021-02-01")
    financial = QuantBTEndpoint(make_endpoint(route, mode="off", backend=backend).config.wfo_execution_config)
    e, frame, ranges, _ = public_setup(tmp_path, frame=frame, strategy=partial(strategy, route),
        ranges={"window": (3, 9, 2)}, execution_endpoint=financial, target_mode=route, trials=4)
    result = e.backtest(data=frame, param_ranges=ranges)
    m = result.metadata["walk_forward"]["mode5_diagnostics_first"]
    actual = execute_window(financial.config, frame, result.metadata["walk_forward_result"].oos_output)
    for name in ("equity", "positions", "fees", "funding", "margin"):
        np.testing.assert_array_equal(getattr(result, name), getattr(actual, name))
    assert m["selected_audit"][0]["final_equity"] == result.equity.iloc[-1]
    assert len(result.fills) > 0
    assert m["status"] == "SELECTED_REPLAY_VERIFIED"


@pytest.mark.parametrize("sampler", ["tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"])
def test_sampler_only_legacy_mode5_does_not_activate_opt_in(tmp_path, sampler):
    e, frame, ranges, _ = public_setup(tmp_path, sampler_name=sampler)
    e.config = replace(e.config, walkforward_config=replace(e.config.walkforward_config, mode5_calibration=None))
    wf = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]
    assert "mode5_diagnostics_first" not in wf and "meta_selection" not in wf
    assert wf["sampler_studies"][0]["recipe"] == sampler
    assert wf["optimization_mode"] == "mode_5_full_robust"


def test_cma_categorical_reject_and_explicit_fallback(tmp_path):
    ranges = {"period": (6, 24, 1), "label": ["a", "b"]}
    e, frame, _, _ = public_setup(tmp_path / "reject", sampler_name="cmaes", ranges=ranges)
    with pytest.raises(ValueError, match="categorical"):
        e.backtest(data=frame, param_ranges=ranges)
    e, frame, _, _ = public_setup(tmp_path / "fallback", sampler_name="cmaes", ranges=ranges,
        sampler_options={"mixed_space_policy": "explicit_independent"})
    m = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]["mode5_diagnostics_first"]
    assert m["sampler"]["independent_sample_calls"]["label"] == 8


def test_old_objective_score_is_never_imported(tmp_path):
    e, frame, ranges, _ = public_setup(tmp_path)
    cfg = replace(e.config.walkforward_config, sampler_warm_start=({"params": {"period": 6}, "objective": 999},))
    e.config = replace(e.config, walkforward_config=cfg)
    with pytest.raises(ValueError, match="warm-start|old scores"):
        e.backtest(data=frame, param_ranges=ranges)


def test_incumbent_is_evaluated_and_final_guard_is_applied(tmp_path):
    ranges = {"period": (6, 24, 1)}
    warm = ({"params": {"period": 10}, "available_at": "2022-01-01T00:00:00Z",
        "space_identity": NormalizedSearchSpace(ranges).identity, "strategy_identity": strategy_fingerprint(alpha)},)
    e, frame, _, _ = public_setup(tmp_path, ranges=ranges, incumbent={"period": 10}, warm_start=warm)
    m = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]["mode5_diagnostics_first"]
    assert m["trial_ledger"][0]["effective_params"] == {"period": 10}
    assert m["decision"]["incumbent_guard"] in {"CHALLENGER_ACCEPTED", "INCUMBENT_RETAINED_BY_DECLARED_MARGIN"}


def test_defer_plan_cannot_authorize_runtime(tmp_path):
    _, _, _, c = public_setup(tmp_path)
    with pytest.raises(PermissionError, match="DEFER"):
        Mode5Calibration(c.dossier, CalibrationPlan.defer(c.dossier, "no authorized search"), c.catalog, c.journal, c.binding)


def test_missing_seal_prevents_execution(tmp_path):
    from quantbt.mode5.dossier.governance import GovernanceLog
    e, frame, ranges, c = public_setup(tmp_path)
    c = replace(c, journal=GovernanceLog(tmp_path / "unsealed"))
    e.config = replace(e.config, walkforward_config=replace(e.config.walkforward_config, mode5_calibration=c))
    with pytest.raises(PermissionError, match="seal|chronology"):
        e.backtest(data=frame, param_ranges=ranges)


@pytest.mark.parametrize("termination", ["cancel", "failed", "pruned"])
def test_ordered_scheduler_all_asked_trials_terminal(termination):
    token = RuntimeCancellationV1()
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=731))
    def evaluate(trial, params):
        if termination == "cancel":
            token.cancel()
        elif termination == "failed":
            raise RuntimeError("registered failure")
        else:
            raise optuna.TrialPruned("registered support failure")
        return params
    if termination == "pruned":
        run_ordered_study(study, budget=3, batch_size=3, suggest=lambda t: 1., evaluate=evaluate)
        assert all(t.state == optuna.trial.TrialState.PRUNED and t.value is None for t in study.trials)
    else:
        with pytest.raises(RuntimeCanceledError if termination == "cancel" else RuntimeError):
            run_ordered_study(study, budget=3, batch_size=3, suggest=lambda t: 1., evaluate=evaluate, cancellation=token)
        assert len(study.trials) == 3 and all(t.state.is_finished() for t in study.trials)
        assert study.trials[-1].value is None


def test_public_failed_batch_retains_unevaluated_asks_and_releases_context(tmp_path):
    def broken(data, params, train_index, test_index, fold):
        raise RuntimeError("registered alpha error")
    e, frame, ranges, _ = public_setup(tmp_path, strategy=broken, batch_size=3)
    with pytest.raises(RuntimeError) as caught:
        e.backtest(data=frame, param_ranges=ranges)
    rows = caught.value.mode5_metadata["trial_ledger"]
    assert len(rows) == 3 and all(r["state"] == "FAILED" for r in rows)
    assert all(r.get("objective") is None for r in rows)


def test_unsupported_worker_fails_before_strategy(tmp_path):
    e, frame, ranges, _ = public_setup(tmp_path)
    cfg = e.config.walkforward_config
    e.config = replace(e.config, walkforward_config=replace(cfg, metadata={**cfg.metadata, "mode5_workers": 2}))
    with pytest.raises(NotImplementedError, match="one worker"):
        e.backtest(data=frame, param_ranges=ranges)


def test_prepared_and_fresh_public_work_preserve_candidate_scores(tmp_path):
    outputs = []
    for name, prepared in (("prepared", True), ("fresh", False)):
        e, frame, ranges, _ = public_setup(tmp_path / name, prepared=prepared)
        m = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]["mode5_diagnostics_first"]
        outputs.append([(r["effective_params"], r["state"], r.get("objective")) for r in m["trial_ledger"]])
        assert e.engine._mode5_runtime is None
    assert outputs[0] == outputs[1]
