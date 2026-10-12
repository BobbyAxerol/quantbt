"""Public continuous Mode5 contracts on the existing synthetic account route."""

from dataclasses import asdict, replace
from contextlib import nullcontext
from hashlib import sha256
from types import SimpleNamespace

import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.mode5.continuous_binding import (
    ContinuousMode5Calibration, continuous_calibration_binding, restore_geometry,
)
from quantbt.mode5.continuous_producer import producer_records
from quantbt.mode5.continuous_runtime import (
    ContinuousMode5MetricPolicy, PublicContinuousMode5Runtime, _GeometryBridge,
)
from quantbt.mode5.diagnostics.access import AccessWitness
from quantbt.mode5.dossier.dossier import Dossier
from quantbt.mode5.dossier.evidence import KINDS, Matrix
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.plans import CalibrationPlan
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.geometry.schema import EffectiveGeometry, OrderedConstraint
from quantbt.mode5.integration_contracts import CalibrationWindow, calibration_context
from quantbt.mode5.statistics.tails import FrozenReference
from quantbt.optimization import SamplerConfig
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from quantbt.optimization.space import stable_params_key
from quantbt.optimization.study_schedule import run_ordered_study
from quantbt.optimization.wfo_study import WfoSamplerStudy
from quantbt.endpoint import _walkforward_scoring_config, _WalkForwardEndpointScorer
from quantbt.mode5.runtime import PublicMode5Runtime, Mode5NoSelectionError
from quantbt.walkforward import WalkForwardEngine, WalkForwardFold

from public_fixtures import market, public_setup


def continuous_setup(tmp_path, *, strategy=None, frame=None, ranges=None, trials=6, preload_days=0):
    frame = market(32) if frame is None else frame
    frame = frame.copy()
    frame.index = pd.date_range("2020-12-16", periods=len(frame), freq="h", tz="UTC")
    scored = frame
    if preload_days:
        preload = market(preload_days)
        preload.index = pd.date_range(frame.index[0]-pd.Timedelta(days=preload_days),
            periods=len(preload), freq="h", tz="UTC")
        frame = pd.concat([preload, frame])
    options = dict(frame=frame, ranges=ranges, trials=trials, two_windows=True)
    if strategy is not None:
        options["strategy"] = strategy
    endpoint, frame, ranges, old = public_setup(tmp_path / "v1", **options)
    step = old.binding.data["metrics"]["bar_interval_ns"]
    access = old.access
    witness = AccessWitness("development-1", "synthetic", int(frame.index[0].value),
        int(frame.index[-1].value)+step, access.cutoff_ns)
    windows = tuple(CalibrationWindow(str(year), int(scored.index[scored.index.year == year][0].value),
        int(scored.index[scored.index.year == year][-1].value), witness) for year in sorted(set(scored.index.year)))
    ref = old.reference
    reference = FrozenReference(ref.reference_id, tuple(w.environment_id for w in windows),
        ref.values, ref.weights, ref.channel, ref.revision)
    geometry = EffectiveGeometry.from_ranges(ranges)
    original = old.binding.data
    execution_config = _walkforward_scoring_config(endpoint.config, "pct_equity")
    source, execution = producer_records(execution_config, endpoint.config.strategy_class)
    binding = continuous_calibration_binding(geometry=geometry,
        source=source, execution=execution,
        witness=witness, windows=windows, reference=reference, sampler=SamplerConfig(**original["sampler"]),
        metrics=original["metrics"], selection=original["selection"], batch_size=1)
    context = calibration_context(data=frame, strategy=endpoint.config.strategy_class,
        execution_config=execution_config, param_ranges=ranges, binding=binding)
    d = old.dossier.record.data
    matrices = tuple(Matrix(Record.of(d["matrices"][k])) for k in KINDS)
    dossier = Dossier.create(context=context, matrices=matrices,
        rosters=tuple(Record.of(d["matrices"][k]["roster"]) for k in KINDS),
        inventory=Record.of(old.catalog.require_ref(d["inventory_ref"])), inventory_ref=d["inventory_ref"],
        catalog=old.catalog, axes=d["axes"], radar=d["radar"], batteries=d["batteries"],
        assessments=d["recommendations"]["recipes"], limitations=d["limitations"], compute_bill=d["compute_bill"])
    spec = old.plan.record.data["recipe"]
    spec["domain"]["schema_id"] = context.data["schema"]
    spec["domain"]["effective_geometry_identity"] = geometry.identity
    spec["retention"].update(contract_id="continuous_account_observation_v1", runtime_binding_identity=binding.identity)
    spec["reuse"]["selection_policy"] = asdict(access)
    plan = CalibrationPlan.search(dossier, {**spec, "search_budget": trials}, "synthetic continuous route proof, no economic claim")
    log = GovernanceLog(tmp_path / "continuous-journal")
    log.seal_dossier(dossier, old.catalog)
    log.seal_plan(dossier, plan, old.catalog, researcher="test", reason=plan.record.data["reason"])
    calibration = ContinuousMode5Calibration(dossier, plan, old.catalog, log, binding)
    # The public entry and original account config are unchanged.
    config = replace(endpoint.config, walkforward_config=replace(endpoint.config.walkforward_config,
        mode5_calibration=calibration))
    return QuantBTEndpoint(config), frame, ranges, calibration


def test_exact_effective_geometry_round_trip_inactive_casts_and_ordered_constraint():
    geometry = EffectiveGeometry.from_ranges({"a": (1, 4), "b": (3, 8), "unused": [False, True]},
        inactive=(("unused", "source_ignored"),), casts=(("a", "truncate_integer_v1"),),
        constraints=(OrderedConstraint(("a", "b")),))
    restored = restore_geometry(Record.of(geometry.metadata()).data)
    assert restored == geometry
    assert restored.resolve({"a": 2.9, "b": 4, "unused": False}).params == {"a": 2, "b": 4}
    with pytest.raises(ValueError, match="ORDERED"):
        restored.resolve({"a": 4, "b": 3})
    altered = geometry.metadata() | {"repair": "silently_sort"}
    with pytest.raises(ValueError, match="altered"):
        restore_geometry(altered)


def test_binding_never_relabels_v1_and_requires_continuous_seal(tmp_path):
    endpoint, frame, ranges, calibration = continuous_setup(tmp_path)
    assert calibration.binding.data["schema"] == "quantbt.mode5.public_binding.continuous.v1"
    assert calibration.continuous_contract.account_policy == "CONTINUOUS_PATH_ATTRIBUTION"
    with pytest.raises(ValueError, match="complete versioned"):
        from quantbt.mode5.integration_contracts import Mode5Calibration
        Mode5Calibration(calibration.dossier, calibration.plan, calibration.catalog, calibration.journal, calibration.binding)


def test_public_study_executes_one_account_per_query_and_preserves_views(tmp_path):
    endpoint, frame, ranges, calibration = continuous_setup(tmp_path)
    result = endpoint.backtest(data=frame, param_ranges=ranges)
    metadata = result.metadata["walk_forward"]["mode5_diagnostics_first"]
    assert metadata["environment_account_policy"] == "CONTINUOUS_PATH_ATTRIBUTION"
    assert metadata["annual_account_resets"] == 0
    assert len(metadata["trial_ledger"]) == 6
    for row in metadata["trial_ledger"]:
        if row["state"] != "COMPLETE":
            continue
        first, second = row["observations"]
        assert (first["environment_id"], second["environment_id"]) == ("2020", "2021")
        assert first["baseline_equity"] == 20000.
        assert second["baseline_source"] == "prior_actual_close"
        assert row["candidate_id"] in metadata["raw_whole_sharpe"]
    assert metadata["deployment_authorized"] is False
    retained = result.metadata["walk_forward_result"].mode5_continuous_accounts
    assert retained.metadata() == metadata["continuous_account_retention"]
    assert len(retained.entries) >= sum(r["state"] == "COMPLETE" for r in metadata["trial_ledger"])
    for query_id, account in retained.entries:
        assert metadata["continuous_observations"][query_id]["identity"] == account.identity
        assert account.observations.equity.flags.writeable is False


def test_public_no_selection_retains_actual_account_buffers_after_cleanup(tmp_path, monkeypatch):
    endpoint, frame, ranges, _ = continuous_setup(tmp_path)
    original = PublicContinuousMode5Runtime._decision
    def reject_final(self, candidates, locals, *, point_objective=False):
        if not point_objective:
            raise Mode5NoSelectionError("registered test failure after actual query observations")
        return original(self, candidates, locals, point_objective=point_objective)
    monkeypatch.setattr(PublicContinuousMode5Runtime, "_decision", reject_final)
    with pytest.raises(Mode5NoSelectionError) as caught:
        endpoint.backtest(data=frame, param_ranges=ranges)
    retained = caught.value.mode5_continuous_accounts
    assert retained.entries
    assert all(not e.observations.equity.flags.writeable for _, e in retained.entries)


def test_public_preload_is_strategy_history_not_scored_account(tmp_path):
    import numpy as np
    endpoint, frame, ranges, calibration = continuous_setup(tmp_path, preload_days=31)
    before = frame.copy(deep=True)
    result = endpoint.backtest(data=frame, param_ranges=ranges)
    wf = result.metadata["walk_forward_result"]
    scope = wf.metadata["mode5_diagnostics_first"]["account_scope"]
    scored = frame.loc[frame.index >= pd.Timestamp(calibration.continuous_contract.start_ns, tz="UTC")]
    assert scope["preload_bars"] == 31*24
    assert scope["scored_bars"] == len(scored)
    assert scope["preload_account_execution"] is False
    assert wf.metadata["prepared_wfo_context"]["bars"] == len(frame)
    assert wf.oos_output.index.equals(scored.index)
    assert wf.folds[0].train_index.equals(scored.index)
    assert result.equity.index.equals(scored.index)
    pd.testing.assert_frame_equal(frame, before)
    selected = [a for _, a in wf.mode5_continuous_accounts.entries
        if a.request.role == "formal_search" and a.request.point.params == wf.params]
    assert selected
    for account in selected:
        assert account.request.warmup_start_ns == int(frame.index[0].value)
        np.testing.assert_array_equal(account.observations.times_ns, scored.index.asi8)
        np.testing.assert_array_equal(account.observations.equity, result.equity.to_numpy())
    signal = endpoint.config.strategy_class(frame, wf.params, scored.index, scored.index, wf.folds[0])
    direct = QuantBTEndpoint.pct_equity(initial_capital=20000., fee=.0005, slippage=.0001,
        alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["ETHUSDT"])
    expected = direct.backtest(data=scored, signal=signal)
    np.testing.assert_array_equal(result.equity.to_numpy(), expected.equity.to_numpy())


def test_public_preload_cannot_be_silently_dropped(tmp_path):
    endpoint, frame, ranges, calibration = continuous_setup(tmp_path, preload_days=31)
    scored = frame.loc[frame.index >= pd.Timestamp(calibration.continuous_contract.start_ns, tz="UTC")]
    with pytest.raises(PermissionError, match="preload is not optional"):
        endpoint.backtest(data=scored, param_ranges=ranges)


def test_future_suffix_never_enters_calibration_request(tmp_path):
    endpoint, frame, ranges, calibration = continuous_setup(tmp_path)
    future = pd.concat([frame, frame.iloc[-1:].set_axis(pd.DatetimeIndex([frame.index[-1]+pd.Timedelta(hours=1)]))])
    with pytest.raises(PermissionError, match="prefix"):
        calibration.continuous_contract.request(future, {"period": 8})
    assert calibration.continuous_contract.request(frame, {"period": 8}).data_identity == \
        calibration.continuous_contract.request(future.iloc[:-1], {"period": 8}).data_identity


def test_unbound_policy_rejects_query_before_metric_observation(tmp_path):
    _, frame, _, calibration = continuous_setup(tmp_path)
    policy = ContinuousMode5MetricPolicy(calibration)
    with pytest.raises(RuntimeError, match="qualified original producer"):
        with policy.evaluation(frame, {"period": 8}, stage="mode5.search"):
            policy.score(None, frame.index)
    assert policy.request is None
    assert policy.evaluations == 0


def test_producer_binding_rejects_actual_config_contradiction(tmp_path):
    endpoint, frame, _, calibration = continuous_setup(tmp_path)
    scorer = _WalkForwardEndpointScorer(endpoint.config, "pct_equity",
        wf_config=endpoint.config.walkforward_config, market_data=frame)
    policy = ContinuousMode5MetricPolicy(calibration)
    scorer.mode5_metric_policy = policy
    policy.bind_producer(scorer, endpoint.config.strategy_class)
    assert policy._producer is scorer
    assert policy._producer_execution == calibration.continuous_contract.execution
    scorer.score_config = replace(scorer.score_config, slippage=.003)
    with pytest.raises(ValueError, match="actual producer"):
        policy.bind_producer(scorer, endpoint.config.strategy_class)


def test_policy_refuses_self_certified_scorer(tmp_path):
    endpoint, _, _, calibration = continuous_setup(tmp_path)
    policy = ContinuousMode5MetricPolicy(calibration)
    scorer = SimpleNamespace(score_config=_walkforward_scoring_config(endpoint.config, "pct_equity"),
        mode5_metric_policy=policy)
    with pytest.raises(TypeError, match="original public endpoint scorer"):
        policy.bind_producer(scorer, endpoint.config.strategy_class)
    assert policy._producer is policy._producer_execution is None


def test_runtime_initialization_binds_genuine_original_producer(tmp_path):
    endpoint, frame, ranges, calibration = continuous_setup(tmp_path)
    scorer = _WalkForwardEndpointScorer(endpoint.config, "pct_equity",
        wf_config=endpoint.config.walkforward_config, market_data=frame)
    scorer.mode5_metric_policy = ContinuousMode5MetricPolicy(calibration)
    engine = WalkForwardEngine(strategy=endpoint.config.strategy_class,
        config=endpoint.config.walkforward_config, scorer=scorer)
    runtime = PublicContinuousMode5Runtime(engine, calibration, frame, frame.index, ranges)
    assert runtime.policy._producer is scorer
    assert runtime.policy._producer_execution == calibration.continuous_contract.execution
    runtime.close()
    assert scorer.mode5_metric_policy._producer is None


def test_original_scorer_reuses_whole_metrics_once_and_keeps_native_count_units(tmp_path):
    endpoint, frame, _, calibration = continuous_setup(tmp_path)
    scorer = _WalkForwardEndpointScorer(endpoint.config, "pct_equity",
        wf_config=endpoint.config.walkforward_config, market_data=frame)
    policy = ContinuousMode5MetricPolicy(calibration)
    scorer.mode5_metric_policy = policy
    policy.bind_producer(scorer, endpoint.config.strategy_class)
    index = frame.index
    fold = WalkForwardFold(0, index[0], index[-1], index[0], index[-1], index, index)
    params = {"period": 8}
    signal = endpoint.config.strategy_class(frame, params, index, index, fold)
    with policy.evaluation(frame, params, stage="mode5.search"):
        scored = scorer(data=frame, output=signal, index=index, fold=fold, params=params,
            context="mode5.search", trading_days=365)
    assert policy.evaluations == 1
    assert policy.request is None
    evaluation = scored["mode5_continuous_evaluation"]
    assert evaluation.raw_whole_sharpe == scored["mode5_observation"]["raw_sharpe"]
    assert evaluation.execution.financial_execution_count == 1
    assert evaluation.execution.internal_execution_counts is None
    assert "not_internal_native" in evaluation.to_metadata()["execution_count_unit"]


def _controller(evaluation):
    """Controller-only fixture; the independent reducer supplies actual marks."""
    from quantbt.mode5.continuous import DAY_NS

    index = pd.to_datetime(evaluation.observations.times_ns, utc=True)
    frame = pd.DataFrame({"close": 100.}, index=index)
    fold = WalkForwardFold(0, index[0], index[-1], index[0], index[-1], index, index)
    geometry = EffectiveGeometry.from_ranges({"period": (2, 20, 1)})
    original = SimpleNamespace(space=NormalizedSearchSpace({"period": (2, 20, 1)}), strategy_identity="controller")
    runtime = object.__new__(PublicContinuousMode5Runtime)
    runtime.index, runtime.data, runtime.study = index, frame, None
    runtime.scope = SimpleNamespace(scored_index=index, require_full_index=lambda actual: None)
    runtime.rows, runtime.candidates, runtime.locals, runtime.params, runtime.observations = [], {}, {}, {}, {}
    runtime.whole_observations, runtime.continuous_observations, runtime.account_observations = {}, {}, {}
    runtime.metadata, runtime.evaluation_seconds = {}, 0.
    runtime.calibration = SimpleNamespace(
        continuous_contract=SimpleNamespace(geometry=geometry),
        windows=tuple(SimpleNamespace(environment_id=v.data["environment_id"]) for v in evaluation.annual_views),
        binding=Record.of(dict(continuous=dict(quality_floor_comparison="greater_or_equal_v1"),
            metrics=dict(min_utility=-10., bar_interval_ns=DAY_NS//24))))
    runtime.policy = SimpleNamespace(evaluation=lambda *args, **kwargs: nullcontext(), request=None,
        _producer=object(), _producer_execution=Record.of(dict(qualified_fixture=True)))
    runtime.engine = SimpleNamespace(_sampler_bridges={0: original},
        _prepared_data_through=lambda data, end, **kwargs: data,
        _call_strategy=lambda data, params, active_fold: pd.Series(0., index=active_fold.test_index),
        _score_strategy_outputs_with_scope=lambda *args, **kwargs: [dict(
            mode5_continuous_observation=evaluation.to_metadata(), mode5_continuous_evaluation=evaluation)])
    return runtime, fold


def _account(marks=(105., 100., 110., 120., 126., 114., 130., 138.)):
    from test_continuous_provider import fixture, observe
    return observe(fixture(marks=marks, start="2020-12-28"))


def _parent(runtime, trial_id, params):
    row = dict(trial_id=trial_id, candidate_id=digest(params), effective_params=params,
        requested_params=params, state="RUNNING", evaluation_ref=None)
    runtime.rows.append(row)
    return row


@pytest.mark.parametrize("stage", ["mode5.search", "mode5.local_probe"])
def test_bankrupt_annual_contract_prunes_parent_without_losing_account(stage):
    account = _account((100., 0., 0., 0., 0., 0., 0., 0.))
    runtime, fold = _controller(account)
    params = {"period": 4}
    parent_params = params if stage == "mode5.search" else {"period": 5}
    parent = _parent(runtime, 0, parent_params)
    if stage == "mode5.local_probe":
        parent["observations"] = tuple(v.data for v in _account().annual_views)
    with pytest.raises(optuna.TrialPruned, match="UNAVAILABLE_ANNUAL_METRIC_CONTRACT"):
        runtime._observe_point(params, [fold], 0, stage=stage)
    assert parent["state"] == "PRUNED"
    assert parent["scientific_reason"]["candidate_id"] == digest(params)
    assert parent["scientific_reason"]["stage"] == stage
    assert next(iter(runtime.account_observations.values())) is account
    assert runtime.whole_observations[digest(params)] == account.whole.data
    annual = runtime.observations[digest(params)][1]
    assert annual["metric_contract"] is None
    assert annual["raw_sharpe"] is None
    runtime._reconcile_ledger()
    if stage == "mode5.search":
        assert parent["raw_whole_sharpe"] is None
        assert parent["annual_mean_raw_sharpe"] is None
    else:
        assert parent["local_probe_observations"][0]["observations"][1] == annual
    assert runtime.metadata["continuous_observations"]


def test_pruned_scientific_query_does_not_abort_next_ordered_trial():
    bad, good = _account((100., 0., 0., 0., 0., 0., 0., 0.)), _account()
    runtime, fold = _controller(bad)
    current = [bad]
    runtime.engine._score_strategy_outputs_with_scope = lambda *args, **kwargs: [dict(
        mode5_continuous_observation=current[0].to_metadata(), mode5_continuous_evaluation=current[0])]
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=731))
    study.enqueue_trial({"period": 4})
    study.enqueue_trial({"period": 5})

    def evaluate(trial, params):
        parent = _parent(runtime, trial.number, params)
        current[0] = bad if trial.number == 0 else good
        runtime._observe_point(params, [fold], trial.number, stage="mode5.search")
        parent["state"] = "COMPLETE"
        return 1.  # Controller test score only; not a financial/objective oracle.

    run_ordered_study(study, budget=2, batch_size=1,
        suggest=lambda trial: {"period": trial.suggest_int("period", 4, 5)}, evaluate=evaluate)
    assert [t.state.name for t in study.trials] == ["PRUNED", "COMPLETE"]
    assert [r["state"] for r in runtime.rows] == ["PRUNED", "COMPLETE"]
    assert len(runtime.account_observations) == 2


@pytest.mark.parametrize("failure", ["no_selection", "unexpected"])
def test_failure_finally_retains_whole_and_annual_sharpe_separately(monkeypatch, failure):
    account = _account()
    runtime, fold = _controller(account)
    params = {"period": 4}
    parent = _parent(runtime, 0, params)
    original_bridge = runtime.engine._sampler_bridges[0]

    def fail(self, *args, **kwargs):
        observations = self._observe_point(params, [fold], 0, stage="mode5.search")
        parent["raw_sharpe"] = sum(v["raw_sharpe"] for v in observations)/len(observations)
        if failure == "no_selection":
            parent["state"] = "COMPLETE"
            raise Mode5NoSelectionError("NO_SUPPORTED_CONFIGURATION")
        raise ValueError("unexpected selection failure")

    monkeypatch.setattr(PublicMode5Runtime, "optimize", fail)
    with pytest.raises((Mode5NoSelectionError, ValueError)):
        runtime.optimize(runtime.data, [fold], {"period": (2, 20, 1)})
    assert parent["raw_sharpe"] == account.raw_whole_sharpe
    assert parent["annual_mean_raw_sharpe"] != parent["raw_whole_sharpe"]
    assert parent["state"] != "RUNNING"
    assert runtime.metadata["raw_whole_sharpe"][digest(params)] == account.raw_whole_sharpe
    assert runtime.metadata["whole_observations"][digest(params)] == account.whole.data
    assert runtime.engine._sampler_bridges[0] is original_bridge


def _sampler(geometry, *, sobol=False, seed=731):
    ranges = {s.name: ({"kind": "boolean", "choices": list(s.choices)} if s.choices else
        {"kind": s.kind, "low": s.low, "high": s.high, "step": s.step}) for s in geometry.specs}
    config = (SamplerConfig("sobol", sobol_policy="conditional_numeric_latent_v1") if sobol
        else SamplerConfig("tpe_legacy"))
    bridge = WfoSamplerStudy(config, ranges, seed=seed, budget=4,
        cutoff=pd.Timestamp("2021-01-01", tz="UTC"), strategy_identity="public-controller", stage="is_search")
    bridge.sampler()
    return bridge


@pytest.mark.parametrize("sobol", [False, True])
def test_geometry_bridge_preserves_proposal_rng_and_uses_shared_effective_id(sobol):
    geometry = EffectiveGeometry.from_ranges({"period": (2, 6, 1), "unused": [False, True]},
        inactive=(("unused", "original_alpha_ignores_axis"),))
    reference, original = _sampler(geometry, sobol=sobol), _sampler(geometry, sobol=sobol)
    bridge = _GeometryBridge(original, geometry)
    control = optuna.create_study(sampler=reference.observed)
    study = optuna.create_study(sampler=original.observed)
    for _ in range(4):
        a, b = control.ask(), study.ask()
        requested, proposal = reference.suggest(a)
        actual_requested, actual = bridge.suggest(b)
        assert actual_requested == requested
        assert b.params == a.params
        assert actual == {"period": proposal["period"]}
        assert b.user_attrs["qms_proposal_candidate_id"] == a.user_attrs["qms_candidate_id"]
        assert b.user_attrs["qms_proposal_effective"] == proposal
        assert b.user_attrs.get("qms_latent") == a.user_attrs.get("qms_latent")
        assert b.user_attrs.get("qms_proposal_latent") == a.user_attrs.get("qms_latent")
        expected = sha256(stable_params_key(dict(strategy=original.strategy_identity,
            space=original.space.identity, effective=actual)).encode()).hexdigest()
        assert b.user_attrs["qms_candidate_id"] == expected
        assert b.user_attrs["qms_effective_active_mask"] == {"period": True, "unused": False}
        control.tell(a, .25)
        study.tell(b, .25)
    metadata = bridge.metadata(study)
    assert metadata["ask_tell_digest"] == reference.metadata(control)["ask_tell_digest"]
    assert metadata["rng_draws_added_by_geometry"] == 0
    assert metadata["unique_effective_candidates"] == len({t.user_attrs["qms_candidate_id"] for t in study.trials})
    assert all(r["effective_active_mask"]["unused"] is False for r in metadata["rows"])


def test_rejected_geometry_retains_proposal_not_an_actual_candidate():
    geometry = EffectiveGeometry.from_ranges({"a": (1, 4, 1), "b": (1, 4, 1)},
        constraints=(OrderedConstraint(("a", "b")),))
    original = _sampler(geometry)
    bridge = _GeometryBridge(original, geometry)
    trial = optuna.trial.FixedTrial({"a": 4, "b": 1})
    with pytest.raises(optuna.TrialPruned, match="EFFECTIVE_GEOMETRY_REJECTED"):
        bridge.suggest(trial)
    assert trial.user_attrs["qms_proposal_effective"] == {"a": 4, "b": 1}
    assert trial.user_attrs["qms_proposal_candidate_id"]
    assert trial.user_attrs["qms_candidate_id"] is None
    assert trial.user_attrs["qms_effective_active_mask"] is None


def test_close_releases_retained_accounts_requests_and_producer_references():
    account = _account()
    runtime, fold = _controller(account)
    _parent(runtime, 0, {"period": 4})
    runtime._observe_point({"period": 4}, [fold], 0, stage="mode5.search")
    policy = runtime.policy
    retained = runtime.detach_account_retention()
    policy.request = object()
    runtime.close()
    runtime.close()
    assert runtime.engine is runtime.data is runtime.index is runtime.study is runtime.policy is None
    assert runtime.whole_observations == runtime.continuous_observations == runtime.account_observations == {}
    assert policy.request is policy._producer is policy._producer_execution is None
    assert account.observations.equity.flags.writeable is False
    assert retained.entries[0][1] is account


def test_detached_retention_copy_and_pickle_preserve_immutable_snapshots():
    from copy import deepcopy
    import pickle
    from quantbt.mode5.continuous_retention import ContinuousAccountRetention
    retained = ContinuousAccountRetention(((digest("query"), _account()),))
    for clone in (deepcopy(retained), pickle.loads(pickle.dumps(retained))):
        assert clone.metadata() == retained.metadata()
        with pytest.raises(ValueError):
            clone.entries[0][1].observations.equity[-1] = 0.
    with pytest.raises(ValueError, match="unique"):
        ContinuousAccountRetention(retained.entries * 2)

