"""Q5-T01..08 execute the public endpoint, not a disconnected selector."""

from dataclasses import replace
import json
import os
from pathlib import Path
import random

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.endpoint import _WalkForwardEndpointScorer
from quantbt.walkforward import WalkForwardEngine
from quantbt.optimization.meta_selection.common import MetaRecordError, digest, wire
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory, SealedTaskRevision
from quantbt.optimization.meta_selection.panel import freeze_panel
from quantbt.optimization.meta_selection.records import (
    CandidateForwardRecord,
    CandidateRoleRef,
)
from quantbt.optimization.meta_selection.runtime import PublicMetaRuntime
from tools.qms01_baseline import endpoint as baseline_endpoint, market


optuna.logging.set_verbosity(optuna.logging.WARNING)
RANGES = {"window": (3, 31, 2)}


def public_endpoint(mode=None, *, observer=False, centroid=False, **settings):
    old = baseline_endpoint(retention="none", centroid=centroid)
    c = old.config.walkforward_config
    config = (
        {
            "mode": mode,
            "min_matured_origins": 1,
            "lambda_reg": 1e-5,
            "label_observer": observer,
            **settings,
        }
        if mode
        else None
    )
    c = replace(
        c,
        meta_selection=config,
        metadata={**c.metadata, "use_scalar_trial_scoring": False},
    )
    return QuantBTEndpoint(replace(old.config, walkforward_config=c))


def context(history=None, *, run="qms05-test", clock=None, native_module=None):
    return MetaHistoryContext(
        history or MetaHistory(),
        "qms05-synthetic",
        "SYNTHETIC-USD-linear",
        "1D",
        run,
        clock=clock,
        native_module=native_module,
    )


def run(
    mode=None,
    *,
    history=None,
    data=None,
    observer=False,
    centroid=False,
    clock=None,
    **settings,
):
    bt = public_endpoint(mode, observer=observer, centroid=centroid, **settings)
    ctx = context(history, clock=clock)
    kwargs = {"meta_history": ctx} if mode not in {None, "off"} else {}
    result = bt.backtest(
        data=market() if data is None else data, param_ranges=RANGES, **kwargs
    )
    return bt, result, ctx


def sidecar(result):
    return result.metadata["walk_forward"]["meta_selection"]


def native_digest(result):
    wf = result.metadata["walk_forward"]
    return digest(
        {
            "trials": wf["trial_table"].to_json(orient="split", date_format="iso"),
            "candidates": wf["candidate_table"].to_json(
                orient="split", date_format="iso"
            ),
            "params": {str(k): v for k, v in wf["params_by_fold"].items()},
            "positions": result.positions.to_numpy().tolist(),
            "equity": result.equity.tolist(),
            "returns": result.returns.tolist(),
            "best": wf["best_trial"],
        }
    )


@pytest.fixture(scope="module")
def cold():
    return run("shadow")


def reviewed_history(template, *, positive=True):
    """Declared synthetic policy fixture, not market-performance evidence.

    Generate independent wide historical feature support, then actual Ridge fits
    a prescribed relative-decay target. No model coefficient/selector is patched.
    """
    candidates = []
    shift = pd.Timedelta(days=730)
    params = range(3, 32, 2)
    for i, window in enumerate(params):
        raw_is = (-10, 25, -5, 10, 0, 15, -15, 5, 20, -20, 8, 12, -8, 18, -12)[i]
        activity = (1, 50, 23, 12, 100, 3, 73, 25, 15, 9, 40, 7, 99, 18, 27)[i]
        source = template.candidates[i % len(template.candidates)]
        obs = replace(
            source.observation,
            raw_sharpe=raw_is,
            activity_count=activity,
            window_start=template.is_start - shift,
            window_end=template.is_end - shift,
            input_frontier=template.is_end - shift,
            output_ref=f"reviewed-is-{i}",
            input_signature="reviewed-synthetic-is",
            verification="reviewed_import",
        )
        candidates.append(
            replace(
                source,
                evaluation_id=f"reviewed-eval-{i}",
                candidate_id=f"reviewed-candidate-{i}",
                native_trial_id=i,
                requested_params={"window": window},
                effective_params={"window": window},
                objective=raw_is,
                observation=obs,
                resolved_at=source.resolved_at - shift,
            )
        )
    task = replace(
        template,
        run_id="reviewed-policy-fixture",
        origin=template.origin - shift,
        is_start=template.is_start - shift,
        is_end=template.is_end - shift,
        forward_start=template.forward_start - shift,
        forward_end=template.forward_end - shift,
        data_cutoff=template.data_cutoff - shift,
        search_completed_at=template.search_completed_at - shift,
        anchor_selected_at=template.anchor_selected_at - shift,
        decision_sealed_at=template.decision_sealed_at - shift,
        first_forward_action_at=template.first_forward_action_at - shift,
        candidates=tuple(candidates),
        anchor_candidate_evaluation_id=candidates[7].evaluation_id,
        roles=(
            CandidateRoleRef(
                "native_anchor",
                template.family.anchor_policy_id,
                candidates[7].evaluation_id,
            ),
        ),
    )
    from quantbt.optimization.meta_selection.descriptors import DescriptorSchema

    panel = freeze_panel(
        task, DescriptorSchema(RANGES), sealed_at=task.decision_sealed_at
    )
    available = task.forward_end + pd.Timedelta(hours=1)
    outcomes = []
    for candidate in task.candidates:
        delta = candidate.observation.raw_sharpe - task.anchor.observation.raw_sharpe
        # DeltaForward = DeltaIS-Y; positive Y slope admits lower IS via Q=0.
        delta_forward = (
            delta if positive is None else (0.0 if positive else 2.0 * delta)
        )
        obs = replace(
            candidate.observation,
            raw_sharpe=2.0 + delta_forward,
            window_start=task.forward_start,
            window_end=task.forward_end,
            input_frontier=task.forward_end,
            output_ref=f"reviewed-forward-{candidate.native_trial_id}",
            input_signature="reviewed-synthetic-forward",
        )
        outcomes.append(
            CandidateForwardRecord(
                task.task_id, candidate.evaluation_id, obs, available, 3600
            )
        )
    revision = SealedTaskRevision(
        task, panel, tuple(outcomes), available, verification="reviewed_import"
    )
    history = MetaHistory()
    history.append(revision)
    return history, revision


@pytest.fixture(scope="module")
def trained_history(cold):
    return reviewed_history(sidecar(cold[1])["tasks"][0])[0]


def test_q5_t01_off_is_legacy_and_never_reads_history(monkeypatch):
    _bt, baseline, _ = run()

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled history access")

    monkeypatch.setattr(MetaHistory, "snapshot", forbidden)
    monkeypatch.setattr(PublicMetaRuntime, "__init__", forbidden)
    _bt, explicit, _ = run("off")
    assert native_digest(baseline) == native_digest(explicit)
    assert "meta_selection" not in explicit.metadata["walk_forward"]


@pytest.mark.parametrize("observer", [False, True])
def test_q5_t02_shadow_preserves_actual_account_search_and_rng(
    trained_history, observer
):
    random.seed(81)
    np.random.seed(82)
    _bt, baseline, _ = run()
    states = random.getstate(), np.random.get_state()
    _bt, shadow, _ = run("shadow", history=trained_history, observer=observer)
    assert native_digest(baseline) == native_digest(shadow)
    assert random.getstate() == states[0]
    assert np.array_equal(np.random.get_state()[1], states[1][1])
    records = sidecar(shadow)["records"]
    assert all(r["final_selection_policy"] == "native" for r in records)
    assert all(not r["past_matured_forward_used_for_selection"] for r in records)
    assert any(r["meta_proposal_uses_past_matured_forward"] for r in records)
    assert all(
        r["proposal"].actual_evaluation_id == r["native_selected_evaluation_id"]
        for r in records
    )


def test_q5_t03_active_fitted_switch_reaches_actual_oos_output(trained_history):
    _bt, result, _ = run("active", history=trained_history)
    records = sidecar(result)["records"]
    first = records[0]
    assert first["selected_evaluation_id"] != first["native_selected_evaluation_id"]
    assert first["proposal"].mode == "active"
    assert first["proposal"].actual_evaluation_id == first["selected_evaluation_id"]
    wf = result.metadata["walk_forward"]
    assert wf["params_by_fold"][first["fold_id"]] == first["selected_params"]
    engine_result = result.metadata["walk_forward_result"]
    for fold, record in zip(engine_result.folds, records, strict=True):
        expected = _bt.config.strategy_class(
            market().loc[: fold.test_index[-1]],
            record["selected_params"],
            fold.train_index,
            fold.test_index,
            fold,
        )
        pd.testing.assert_series_equal(
            engine_result.oos_output.loc[fold.test_index], expected, check_names=False
        )
    assert wf["validation_claim"] == "chronological_adaptive_meta_selection"
    assert not wf["oos_used_for_selection"]


def test_q5_t04_lower_is_full_pool_winner_not_overwritten(trained_history):
    _bt, result, _ = run("active", history=trained_history)
    r = sidecar(result)["records"][0]
    predictions = {p["evaluation_id"]: p for p in r["proposal"].predictions}
    assert (
        predictions[r["selected_evaluation_id"]]["raw_is"] < r["native_raw_is_sharpe"]
    )
    assert r["eligible_is_pool_size"] == len(predictions)
    assert (
        r["eligible_is_pool_size"]
        > len(result.metadata["walk_forward"]["candidate_table"]) / 2
    )
    assert r["past_matured_forward_used_for_selection"]


@pytest.mark.parametrize(
    "mode,schedule,target",
    [
        ("mode_1_decay", "per_fold_decay", "signal_notional"),
        ("mode_4_is_only_robust", "global", "signal_notional"),
        ("mode_5_full_robust", "global", "signal_notional"),
        ("mode_2_sbb", "global", "signal_notional"),
        ("mode_4_is_only_robust", "per_fold_causal", "portfolio"),
    ],
)
def test_q5_t05_unsupported_preflight_before_search(
    monkeypatch, mode, schedule, target
):
    calls = []
    monkeypatch.setattr(optuna, "create_study", lambda *a, **k: calls.append("study"))
    with pytest.raises(ValueError, match="META_(METHODOLOGY|ROUTE)_UNSUPPORTED"):
        QuantBTEndpoint.walk_forward(
            strategy_class=lambda **k: calls.append("strategy"),
            optimization_mode=mode,
            optimization_schedule=schedule,
            target_mode=target,
            optuna_trials=6,
            optimization_config={"meta_selection": {"mode": "active"}},
        )
    assert not calls


def test_q5_t05_cold_flags_and_no_fabricated_fit(cold):
    for r in sidecar(cold[1])["records"]:
        assert r["final_selection_policy"] == "native"
        assert r["fit_completed_at"] is None
        assert not r["past_matured_forward_used_for_selection"]
        assert not r["meta_proposal_uses_past_matured_forward"]


def test_q5_t05_active_same_anchor_still_uses_history(cold):
    history, _ = reviewed_history(sidecar(cold[1])["tasks"][0], positive=None)
    _bt, result, _ = run("active", history=history)
    r = sidecar(result)["records"][0]
    assert r["selected_evaluation_id"] == r["native_selected_evaluation_id"]
    assert r["final_selection_reason"] == "META_MODEL_PROPOSAL"
    assert r["past_matured_forward_used_for_selection"]
    assert r["meta_proposal_uses_past_matured_forward"]


@pytest.mark.parametrize(
    "settings",
    [
        {"use_scalar_trial_scoring": True},
        {"strategy_lifecycle_policy": "legacy_reuse_v1"},
        {"scoring_backend": "proxy"},
    ],
)
def test_q5_t05_incompatible_execution_fails_without_optimizer(settings, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("optimizer started before preflight")

    monkeypatch.setattr(optuna, "create_study", forbidden)
    config = {
        "meta_selection": {"mode": "active"},
        "use_scalar_trial_scoring": False,
        **settings,
    }
    with pytest.raises(ValueError, match="META_ROUTE_UNSUPPORTED"):
        QuantBTEndpoint.walk_forward(
            strategy_class=lambda **kwargs: None,
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_causal",
            optuna_trials=6,
            optimization_config=config,
        )


def test_q5_t05_missing_history_and_fixed_params_fail_before_evaluation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("financial/search evaluation before history preflight")

    monkeypatch.setattr(WalkForwardEngine, "optimize_params", forbidden)
    monkeypatch.setattr(_WalkForwardEndpointScorer, "__call__", forbidden)
    bt = public_endpoint("active")
    with pytest.raises(ValueError, match="META_HISTORY_INCOMPATIBLE"):
        bt.backtest(data=market(), param_ranges=RANGES)
    with pytest.raises(ValueError, match="META_METHODOLOGY_UNSUPPORTED"):
        bt.backtest(data=market(), params={"window": 9}, meta_history=context())


@pytest.mark.parametrize(
    "config",
    [
        {"mode": "active", "typo": True},
        {"mode": "active", "q_hat_floor": 0.2},
        {"mode": "invalid"},
        {"mode": "active", "label_observer": "yes"},
    ],
)
def test_q5_t05_strict_config_rejects_invalid_policy(config):
    from quantbt.optimization.meta_selection.config import normalize_meta_config

    with pytest.raises(MetaRecordError):
        normalize_meta_config(config)


def test_q5_t06_future_market_mutation_keeps_earlier_actual_decision(trained_history):
    _bt, original, _ = run("active", history=trained_history)
    future = market()
    future.loc[future.index >= "2021-01-01", ["open", "high", "low", "close"]] *= 3
    _bt, mutated, _ = run("active", history=trained_history, data=future)
    a, b = sidecar(original)["records"][0], sidecar(mutated)["records"][0]
    assert a["selected_params"] == b["selected_params"]
    assert a["proposal"].predictions == b["proposal"].predictions
    assert a["training_snapshot_id"] == b["training_snapshot_id"]
    assert (
        original.metadata["walk_forward"]["trial_table"].iloc[0]["objective"]
        == mutated.metadata["walk_forward"]["trial_table"].iloc[0]["objective"]
    )


def test_q5_t06_snapshot_frozen_before_delayed_search(cold):
    template = sidecar(cold[1])["tasks"][0]
    history, revision = reviewed_history(template)
    cutoff = template.data_cutoff + pd.Timedelta(hours=23, minutes=45)
    # This otherwise-compatible label/revision arrives after the input cutoff.
    late = replace(
        revision,
        outcomes=tuple(
            replace(o, label_available_at=cutoff + pd.Timedelta(minutes=5))
            for o in revision.outcomes
        ),
        revision_available_at=cutoff + pd.Timedelta(minutes=5),
    )
    history = MetaHistory()

    def clock(fold, stage, elapsed):
        if stage == "search" and fold.fold_id == 0:
            history.append(late)
        minutes = {"search": 8, "fit": 8.5, "seal": 9}[stage]
        return fold.train_index[-1] + pd.Timedelta(minutes=minutes)

    data = market()
    index = data.index.to_list()
    index[index.index(template.data_cutoff)] = cutoff
    data.index = pd.DatetimeIndex(index)
    _bt, result, _ = run("active", history=history, clock=clock, data=data)
    first = sidecar(result)["records"][0]
    assert first["matured_origins"] == 0
    assert not first["training_revision_ids"]
    assert pd.Timestamp(first["search_completed_at"]) == cutoff + pd.Timedelta(
        minutes=8
    )
    assert pd.Timestamp(first["decision_sealed_at"]) == cutoff + pd.Timedelta(minutes=9)
    assert pd.Timestamp(first["effective_at"]) > pd.Timestamp(
        first["decision_sealed_at"]
    )
    assert pd.Timestamp(first["effective_at"]) == cutoff + pd.Timedelta(minutes=15)


def test_q5_t06_unavailable_forward_mutation_is_closed(cold):
    template = sidecar(cold[1])["tasks"][0]
    original, revision = reviewed_history(template)
    available = template.data_cutoff + pd.Timedelta(minutes=5)
    history = MetaHistory()
    altered = replace(
        revision,
        outcomes=tuple(
            replace(
                o,
                label_available_at=available,
                observation=replace(o.observation, raw_sharpe=1e6),
            )
            for o in revision.outcomes
        ),
        revision_available_at=available,
    )
    history.append(altered)
    _bt, result, _ = run("active", history=history)
    earlier = sidecar(result)["records"][0]
    assert earlier["matured_origins"] == 0
    assert (
        earlier["selected_params"]
        == sidecar(cold[1])["records"][0]["native_selected_params"]
    )


def test_q5_t06_readiness_does_not_backdate_or_shift():
    with pytest.raises(MetaRecordError, match="META_CLOCK_UNSUPPORTED"):
        run("active", clock=lambda fold, stage, elapsed: fold.test_index[0])


def test_q5_t07_observer_publication_only_reaches_later_folds():
    frame = market()
    extra = pd.date_range(frame.index[0], periods=850, freq="1D", tz="UTC")
    t = np.arange(len(extra))
    close = 100 + 0.025 * t + 3 * np.sin(t / 13) + np.cos(t / 5)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000 + t,
        },
        index=extra,
    )
    bt, result, ctx = run("active", data=frame, observer=True)
    records = sidecar(result)["records"]
    assert [r["matured_origins"] for r in records[:3]] == [0, 0, 1]
    assert sidecar(result)["observer_failures"] == 0
    for i, r in enumerate(records):
        assert r["observer_reset_accounts"]
        assert r["observer_evaluations"] == len(r["panel_members"])
        assert all(
            pd.Timestamp(previous["observer_label_available_at"])
            < pd.Timestamp(r["information_as_of"])
            for previous in records[:i]
            if previous["observer_revision_id"] in r["training_revision_ids"]
        )
    assert (
        ctx.history.snapshot(
            family_id=records[0]["family_id"],
            authorized_corpora=(ctx.corpus_id,),
            outcome_origins=ctx.outcome_origins,
            research_exposures=ctx.research_exposures,
            information_as_of=extra[-1] + pd.Timedelta(days=1),
        ).origin_count
        >= 3
    )


@pytest.mark.parametrize("centroid", [False, True])
def test_q5_t08_lineage_raw_ledgers_and_continuous_account(
    cold, trained_history, centroid
):
    history = trained_history if not centroid else None
    bt, result, _ = run("active", history=history, centroid=centroid)
    wf = result.metadata["walk_forward"]
    records = sidecar(result)["records"]
    assert wf["params"] == records[-1]["selected_params"]
    for r in records:
        assert wf["params_by_fold"][r["fold_id"]] == r["selected_params"]
        assert r["proposal"].actual_evaluation_id == r["selected_evaluation_id"]
        row = wf["fold_selection_table"].set_index("fold_id").loc[r["fold_id"]]
        assert row["selected_evaluation_id"] == r["selected_evaluation_id"]
        assert (
            bool(row["past_matured_forward_used_for_selection"])
            == r["past_matured_forward_used_for_selection"]
        )
        if r["past_matured_forward_used_for_selection"]:
            assert (
                row["causality_claim"]
                == "current_outer_oos_excluded_past_forward_adaptive"
            )
        assert r["native_selected_evaluation_id"] in {
            c.evaluation_id for c in sidecar(result)["tasks"][r["fold_id"]].candidates
        }
    plain = QuantBTEndpoint(bt.engine.scorer.score_config)
    # Final stitched account is authoritative, not concatenated reset equities.
    final = plain.backtest(
        data=market(), signal=result.metadata["walk_forward_result"].oos_output
    )
    pd.testing.assert_series_equal(final.equity, result.equity)
    assert (
        sidecar(result)["account_authority"]
        == "existing_continuous_stitched_target_account"
    )
    assert not any(k in wf["trial_table"].columns for k in ("yhat", "qhat"))
    last = records[-1]
    assert (
        wf["best_trial"]["selection_metadata"]["selected_evaluation_id"]
        == last["selected_evaluation_id"]
    )
    assert (
        wf["best_trial"]["selection_metadata"][
            "past_matured_forward_used_for_selection"
        ]
        == last["past_matured_forward_used_for_selection"]
    )
    json.dumps(wire(records[0]["proposal"]), allow_nan=False)


def test_q5_t08_active_decision_portable_restore(trained_history):
    from quantbt.optimization.meta_selection.artifacts import (
        dumps_decision,
        loads_decision,
    )

    _bt, result, _ = run("active", history=trained_history)
    d = sidecar(result)["records"][0]["proposal"]
    restored = loads_decision(
        dumps_decision(d),
        expected_decision_id=d.decision_id,
        available_as_of=d.ready_at,
    )
    assert restored.decision_id == d.decision_id
    assert restored.actual_evaluation_id == d.proposed_evaluation_id
    assert restored.mode == "active"


def test_q5_t02_centroid_auxiliary_is_rng_isolated(monkeypatch):
    original = WalkForwardEngine.evaluate_params_is

    def noisy_auxiliary(self, *args, **kwargs):
        if kwargs.get("trial_id") == -1:
            random.random()
            np.random.random()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(WalkForwardEngine, "evaluate_params_is", noisy_auxiliary)
    _bt, baseline, _ = run(centroid=True)
    states = random.getstate(), np.random.get_state()
    _bt, shadow, _ = run("shadow", centroid=True, observer=True)
    assert native_digest(baseline) == native_digest(shadow)
    assert random.getstate() == states[0]
    assert np.array_equal(np.random.get_state()[1], states[1][1])
    assert sum(r["auxiliary_is_evaluations"] for r in sidecar(shadow)["records"]) > 0


def test_q5_t05_require_native_capability_fails_before_search(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("search/evaluation started despite missing QMS capability")

    monkeypatch.setattr(WalkForwardEngine, "optimize_params", forbidden)
    with pytest.raises(MetaRecordError, match="META_NATIVE_UNAVAILABLE_OR_UNQUALIFIED"):
        from types import SimpleNamespace
        bt = public_endpoint("active", native_batch_policy="require")
        bt.backtest(data=market(), param_ranges=RANGES,
                    meta_history=context(native_module=SimpleNamespace()))


def test_q5_t05_fixed_config_override_does_not_ignore_meta():
    base = public_endpoint()
    with pytest.raises(ValueError, match="META_ROUTE_UNSUPPORTED"):
        QuantBTEndpoint.walk_forward(
            strategy_class=base.config.strategy_class,
            walkforward_config=replace(
                base.config.walkforward_config,
                metadata={"use_scalar_trial_scoring": True},
            ),
            optimization_config={"meta_selection": {"mode": "active"}},
        )


def test_q5_t07_no_variance_is_not_a_zero_training_label():
    base = public_endpoint("active", observer=True)

    def flat(data, params, train_index, test_index, fold):
        return pd.Series(0.0, index=test_index)

    bt = QuantBTEndpoint(replace(base.config, strategy_class=flat))
    ctx = context()
    result = bt.backtest(data=market(), param_ranges=RANGES, meta_history=ctx)
    for r in sidecar(result)["records"]:
        assert r["final_selection_reason"] == "META_NOT_APPLICABLE_METRIC"
        assert not r["past_matured_forward_used_for_selection"]
    snap = ctx.history.snapshot(
        family_id=sidecar(result)["records"][0]["family_id"],
        authorized_corpora=(ctx.corpus_id,),
        outcome_origins=ctx.outcome_origins,
        research_exposures=ctx.research_exposures,
        information_as_of=market().index[-1] + pd.Timedelta(days=1),
    )
    assert snap.origin_count == 0
    assert not snap.training_rows


def test_q5_t08_pct_equity_fees_funding_and_boundary_authority():
    old = public_endpoint("shadow", observer=True)
    cfg = replace(old.config.walkforward_config, target_mode="pct_equity")
    bt = QuantBTEndpoint(
        replace(
            old.config,
            walkforward_config=cfg,
            walkforward_target_mode="pct_equity",
            sizing="pct_equity",
            alloc_per_trade=0.5,
            fee_rate=old.config.fee / 2.0,
            use_funding=True,
            funding_rate=0.0001,
            slippage=0.0001,
        )
    )
    ctx = context()
    result = bt.backtest(data=market(), param_ranges=RANGES, meta_history=ctx)
    bare = QuantBTEndpoint.pct_equity(
        initial_capital=20000,
        leverage=3,
        alloc_per_trade=0.5,
        fee_rate=old.config.fee / 2.0,
        use_funding=True,
        funding_rate=0.0001,
        slippage=0.0001,
    )
    expected = bare.backtest(
        data=market(), signal=result.metadata["walk_forward_result"].oos_output
    )
    pd.testing.assert_series_equal(result.equity, expected.equity)
    assert sidecar(result)["observer_failures"] == 0


def test_q5_t08_public_active_native_numeric_candidate(trained_history):
    path = os.environ.get("QMS04_NATIVE_EXTENSION")
    if path is None:
        # Ordinary consumers still exercise the explicit missing/require gate.
        # Actual certification commands supply a real extension, no fake module.
        with pytest.raises(
            MetaRecordError, match="META_NATIVE_UNAVAILABLE_OR_UNQUALIFIED"
        ):
            run("active", history=trained_history, native_batch_policy="require")
        return
    from tools.build_qms04_candidate import load_candidate

    native = load_candidate(Path(path))
    bt = public_endpoint("active", native_batch_policy="require")
    result = bt.backtest(
        data=market(),
        param_ranges=RANGES,
        meta_history=context(trained_history, native_module=native),
    )
    for r in sidecar(result)["records"]:
        assert r["numeric_backend"]["selected_backend_by_block"]["gram_solve"] == "rust"
        assert r["proposal"].numeric["complete_reference_decision_verified"]
        assert r["proposal"].numeric["current_forward_inputs"] is False


def test_q5_t06_strategy_frontier_is_closed_until_actual_seal(monkeypatch):
    original = WalkForwardEngine._call_strategy_for_indices
    entries = []

    def checked(self, data, params, train_index, test_index, fold, **kwargs):
        runtime = getattr(self, "_meta_runtime", None)
        if runtime is not None:
            forward = test_index[-1] > fold.train_index[-1]
            if forward:
                assert runtime.records[-1]["fold_id"] == fold.fold_id
                assert runtime.records[-1]["selected_params"] == params
                assert (
                    pd.Timestamp(runtime.records[-1]["decision_sealed_at"])
                    < test_index[0]
                )
            else:
                assert test_index[-1] <= fold.train_index[-1]
            entries.append((int(fold.fold_id), bool(forward)))
        return original(self, data, params, train_index, test_index, fold, **kwargs)

    monkeypatch.setattr(WalkForwardEngine, "_call_strategy_for_indices", checked)
    run("active", observer=True)
    for fold in {f for f, _ in entries}:
        flags = [forward for f, forward in entries if f == fold]
        assert flags[-1] is True
        assert flags.count(True) == 1
        assert any(not flag for flag in flags)


def test_q5_t05_compatibility_tracks_constraints_and_search_policy(cold):
    bt = cold[0]
    cfg, scorer = bt.config.walkforward_config, bt.engine.scorer
    schema = bt.engine._meta_runtime.schema
    ctx = context()

    def family(c):
        return PublicMetaRuntime.compatibility_family(
            WalkForwardEngine(bt.config.strategy_class, c, scorer=scorer), ctx, schema
        )

    base = family(cfg)
    for change in (
        {"random_seed": cfg.random_seed + 1},
        {"optuna_early_stopping": 2},
        {"parameter_constraints": lambda p: (p["window"] - 15,)},
        {"result_constraints": lambda p, result: (0.0,)},
    ):
        assert family(replace(cfg, **change)).family_id != base.family_id


def test_q5_t02_shared_conditional_sampler_remains_independent():
    ranges = {
        **RANGES,
        "filter": {"kind": "boolean"},
        "length": {
            "kind": "integer",
            "low": 2,
            "high": 8,
            "step": 2,
            "active_if": {"filter": True},
        },
    }

    def sample(mode):
        old = public_endpoint(mode, observer=bool(mode))
        cfg = replace(
            old.config.walkforward_config,
            sampler_config={"name": "tpe_multivariate_group"},
            optuna_trials=12,
        )
        bt = QuantBTEndpoint(replace(old.config, walkforward_config=cfg))
        kwargs = {"meta_history": context()} if mode else {}
        return bt.backtest(data=market(), param_ranges=ranges, **kwargs)

    baseline, shadow = sample(None), sample("shadow")
    assert native_digest(baseline) == native_digest(shadow)
    for task in sidecar(shadow)["tasks"]:
        for c in task.candidates:
            assert ("length" in c.effective_params) == c.effective_params["filter"]


def test_q5_t08_runnable_public_example_and_result_consumer():
    from examples.wfo_meta_selection import run_demo

    endpoint, result, _ = run_demo("shadow", min_origins=1)
    report = result.full_report(trading_days=365)
    assert report["final_equity"] == result.equity.iloc[-1]
    assert len(sidecar(result)["records"]) == len(
        endpoint.engine.build_folds(result.equity.index)
    )
    assert sidecar(result)["observer_attempts"] > 0
    assert sidecar(result)["observer_failures"] == 0
