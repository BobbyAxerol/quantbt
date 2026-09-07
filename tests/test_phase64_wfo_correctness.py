"""Phase 64 causal WFO contracts, lifecycle, and boundary-account evidence."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    FoldAccountPolicyV1,
    FoldWarmupPolicyV1,
    QuantBTEndpoint,
    WfoIntentContractV1,
    WfoIntentKindV1,
    prepare_calendar_plan_v2,
)
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine, WalkForwardTrialRecord


def _bars(
    start: str = "2020-01-01",
    end: str = "2021-09-30",
    *,
    offset: str | None = None,
) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="1D", tz="UTC")
    if offset is not None:
        index = index + pd.Timedelta(offset)
    phase = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 0.02 * phase + np.sin(phase / 9.0)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.9,
            "low": close - 0.9,
            "close": close,
            "volume": 1_000.0 + phase,
            "funding_rate": np.where((phase.astype(int) % 8) == 0, 0.0001, 0.0),
        },
        index=index,
    )


def _neutral_scorer(data, output, index, fold, params, context, trading_days):
    del data, output, index, fold, params, context, trading_days
    return {
        "sharpe": 1.0,
        "turnover": 10.0,
        "trade_count": 10.0,
        "mean_return": 0.0,
        "volatility": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": 1.0,
    }


def _base_config(**overrides) -> WalkForwardConfig:
    values = {
        "split_mode": "2021-01-01",
        "split_frequency": "quarterly",
        "window_mode": "rolling",
        "train_window": "180D",
        "min_train_bars": 30,
        "min_test_bars": 30,
        "calendar_contract": "exact_v2",
        "scoring_backend": "endpoint",
    }
    values.update(overrides)
    return WalkForwardConfig(**values)


def _side_strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    return pd.Series(float(params.get("side", 1.0)), index=test_index)


def _record(*, trial_id: int, side: int, objective: float) -> WalkForwardTrialRecord:
    return WalkForwardTrialRecord(
        trial_id=trial_id,
        params={"side": side},
        objective=objective,
        mean_is_sharpe=objective,
        mean_oos_sharpe=0.0,
        mean_decay=0.0,
        std_decay=0.0,
        fold_metrics=[],
    )


def test_public_wfo_contract_exports_and_intent_metadata_are_explicit():
    contract = WfoIntentContractV1(
        kind=WfoIntentKindV1.TARGET_UNITS,
        observation_phase="bar_close",
        effective_phase="next_bar_open",
        already_shifted=False,
        route_id="phase64-test-target-units",
        certified=True,
    )
    metadata = contract.metadata()

    assert metadata["kind"] == "target_units"
    assert metadata["effective_phase"] == "next_bar_open"
    assert metadata["certified"] is True
    assert FoldWarmupPolicyV1.PRE_TEST_FROM_TRAIN_TAIL.value == "pre_test_from_train_tail"
    assert FoldAccountPolicyV1.CLOSE_AT_BOUNDARY.value == "close_at_boundary"


def test_calendar_plan_exact_rejects_shift_and_intersection_uses_one_canonical_clock():
    btc = _bars()
    eth_shifted = _bars(offset="1h")

    exact = WalkForwardEngine(
        strategy=_side_strategy,
        scorer=_neutral_scorer,
        config=_base_config(target_mode="portfolio"),
    )
    with pytest.raises(ValueError, match="exact|Exact"):
        exact.run(data={"BTC": btc, "ETH": eth_shifted}, params={"side": 1.0})

    eth = _bars(start="2020-01-03", end="2021-09-28")
    expected = btc.index.intersection(eth.index)
    seen = []

    def portfolio_strategy(data, params, train_index, test_index, fold):
        del params, train_index, fold
        seen.append((data["BTC"].index.copy(), data["ETH"].index.copy()))
        return pd.DataFrame({"BTC": 1.0, "ETH": -1.0}, index=test_index)

    intersection = WalkForwardEngine(
        strategy=portfolio_strategy,
        scorer=_neutral_scorer,
        config=_base_config(calendar_contract="intersection_v2", target_mode="portfolio"),
    )
    result = intersection.run(data={"BTC": btc, "ETH": eth}, params={})

    assert result.folds[0].train_start >= expected[0]
    assert result.metadata["calendar_plan"]["policy"] == "intersection"
    assert result.metadata["calendar_plan"]["bars"] == len(expected)
    assert seen
    assert all(left.equals(expected) and right.equals(expected) for left, right in seen)

    direct = prepare_calendar_plan_v2(
        {"BTC": btc, "ETH": eth},
        calendar_policy="intersection",
        missing_policy="no_observation",
    )
    assert direct.datetime_index.equals(expected)


@pytest.mark.parametrize(
    ("warmup_policy", "warmup_bars", "expected_source"),
    [
        ("none", None, "empty"),
        ("pre_train_only", 4, "pre_train"),
        ("pre_test_from_train_tail", 5, "train_tail"),
        ("explicit_bars", 6, "train_tail"),
    ],
)
def test_fold_v2_records_purge_embargo_and_all_warmup_policies(
    warmup_policy,
    warmup_bars,
    expected_source,
):
    config = _base_config(
        label_horizon_bars=3,
        purge_bars=2,
        embargo_bars=4,
        warmup_policy=warmup_policy,
        warmup_bars=warmup_bars,
    )
    engine = WalkForwardEngine(strategy=_side_strategy, scorer=_neutral_scorer, config=config)
    index = _bars().index
    folds = engine.build_folds(index)

    assert len(folds) >= 2
    first = folds[0]
    assert len(first.label_horizon_index) == 3
    assert len(first.purge_index) == 2
    assert first.train_end < first.purge_index[0] < first.label_horizon_index[0] < first.test_start
    assert len(first.embargo_index) == 4
    assert first.embargo_index[0] > first.test_end
    assert folds[1].test_start > first.embargo_index[-1]
    assert first.cutoff_timestamp == first.test_end
    if expected_source == "empty":
        assert len(first.warmup_index) == 0
    elif expected_source == "pre_train":
        assert len(first.warmup_index) == warmup_bars
        assert first.warmup_index[-1] < first.train_start
    else:
        assert first.warmup_index.equals(first.train_index[-warmup_bars:])


class _LifecycleChild:
    def __init__(self, events):
        self.events = events
        self.seed = None
        self.market_fingerprint = None
        self.closed = False

    def reset(self, *, seed, market_fingerprint, cutoff):
        self.seed = int(seed)
        self.market_fingerprint = str(market_fingerprint)
        self.events.append(("reset", self.seed, str(cutoff)))

    def state_fingerprint(self):
        return f"{self.seed}:{self.market_fingerprint}:{self.closed}"

    def warmup(self, *, data, index, params, fold):
        del data, params, fold
        self.events.append(("warmup", self.seed, len(index)))

    def close(self):
        self.closed = True
        self.events.append(("close", self.seed))

    def __call__(self, data, params, train_index, test_index, fold):
        del data, train_index, fold
        # The output depends on reset state, so a full-tape-derived seed would
        # make this regression fail when later data is appended.
        side = 1.0 if self.seed % 2 else -1.0
        return pd.Series(side * float(params["multiplier"]), index=test_index)


class _LifecycleFactory:
    strategy_version = "phase64-lifecycle-v1"

    def __init__(self):
        self.events = []

    def spawn(self, *, run_id, candidate_id, fold_id):
        self.events.append(("spawn", run_id, candidate_id, fold_id))
        return _LifecycleChild(self.events)


def _lifecycle_config() -> WalkForwardConfig:
    return _base_config(
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optuna_trials=2,
        random_seed=811,
        top_is_fraction=1.0,
        flat_eps=1.0,
        flat_min_samples=1,
        is_subperiods=1,
        candidate_selection_metric="is_only_robust",
        strategy_lifecycle_policy="isolated_v1",
        warmup_policy="pre_test_from_train_tail",
        warmup_bars=3,
    )


def test_causal_lifecycle_seed_and_market_fingerprint_ignore_appended_future_funding():
    short_data = _bars(end="2021-06-30")
    extended_data = _bars(end="2021-09-30")
    future = extended_data.index > short_data.index[-1]
    extended_data.loc[future, "funding_rate"] = 0.987654321

    short_factory = _LifecycleFactory()
    short = WalkForwardEngine(
        strategy=short_factory,
        scorer=_neutral_scorer,
        config=_lifecycle_config(),
    ).run(data=short_data, param_ranges={"multiplier": [1.0]})
    extended_factory = _LifecycleFactory()
    extended = WalkForwardEngine(
        strategy=extended_factory,
        scorer=_neutral_scorer,
        config=_lifecycle_config(),
    ).run(data=extended_data, param_ranges={"multiplier": [1.0]})

    short_prefix_end = short.folds[-1].test_end
    pd.testing.assert_series_equal(
        short.oos_output.loc[:short_prefix_end],
        extended.oos_output.loc[:short_prefix_end],
    )
    assert short.metadata["params_by_fold"] == {
        key: value
        for key, value in extended.metadata["params_by_fold"].items()
        if key < len(short.folds)
    }

    columns = ["candidate_id", "fold_id", "cutoff", "context", "seed", "market_fingerprint"]
    short_lifecycle = short.metadata["strategy_lifecycle_table"]
    extended_lifecycle = extended.metadata["strategy_lifecycle_table"]
    completed_fold_ids = set(range(len(short.folds)))
    short_rows = short_lifecycle.loc[short_lifecycle["fold_id"].isin(completed_fold_ids), columns].sort_values(columns[:4])
    extended_rows = extended_lifecycle.loc[extended_lifecycle["fold_id"].isin(completed_fold_ids), columns].sort_values(columns[:4])
    pd.testing.assert_frame_equal(short_rows.reset_index(drop=True), extended_rows.reset_index(drop=True))
    assert any(event[0] == "close" for event in short_factory.events)
    assert any(event[0] == "warmup" for event in short_factory.events)
    assert short_lifecycle["reset_called"].all()
    assert short_lifecycle["closed"].all()
    assert short_lifecycle["warmup_called"].all()


def test_per_fold_causal_selection_does_not_inspect_that_fold_external_test_labels():
    baseline = _bars(end="2021-06-30")
    baseline["label"] = np.where(np.arange(len(baseline)) % 2 == 0, 1.0, -1.0)
    mutated = baseline.copy()
    first_fold = WalkForwardEngine(
        strategy=_side_strategy,
        scorer=_neutral_scorer,
        config=_lifecycle_config(),
    ).build_folds(baseline.index)[0]
    mutated.loc[first_fold.test_index, "label"] *= -1.0
    observed = []

    def label_strategy(data, params, train_index, test_index, fold):
        observed.append((int(fold.fold_id), data.index[-1], test_index[-1]))
        return data["label"].reindex(test_index).fillna(0.0) * float(params["multiplier"])

    baseline_result = WalkForwardEngine(
        strategy=label_strategy,
        scorer=_neutral_scorer,
        config=_lifecycle_config(),
    ).run(data=baseline, param_ranges={"multiplier": [1.0]})
    mutated_result = WalkForwardEngine(
        strategy=label_strategy,
        scorer=_neutral_scorer,
        config=_lifecycle_config(),
    ).run(data=mutated, param_ranges={"multiplier": [1.0]})

    assert baseline_result.metadata["params_by_fold"][0] == mutated_result.metadata["params_by_fold"][0]
    assert all(visible_end <= requested_end for _, visible_end, requested_end in observed)


def test_isolated_lifecycle_results_are_invariant_to_fold_call_order():
    data = _bars(end="2021-06-30")

    def evaluate(order):
        engine = WalkForwardEngine(
            strategy=_LifecycleFactory(),
            scorer=_neutral_scorer,
            config=_lifecycle_config(),
        )
        folds = engine.build_folds(data.index)
        outputs = {}
        for fold_id in order:
            fold = folds[fold_id]
            outputs[fold_id] = engine._call_strategy_for_indices(
                data=data,
                params={"multiplier": 1.0},
                train_index=fold.train_index,
                test_index=fold.test_index,
                fold=fold,
                context="fold-order-invariance",
            )
        lifecycle = pd.DataFrame(engine._lifecycle_records)
        return outputs, lifecycle

    forward_outputs, forward_lifecycle = evaluate([0, 1])
    reverse_outputs, reverse_lifecycle = evaluate([1, 0])
    for fold_id in (0, 1):
        pd.testing.assert_series_equal(forward_outputs[fold_id], reverse_outputs[fold_id])
    fields = ["fold_id", "candidate_id", "seed", "market_fingerprint", "state_before", "state_after"]
    pd.testing.assert_frame_equal(
        forward_lifecycle[fields].sort_values("fold_id").reset_index(drop=True),
        reverse_lifecycle[fields].sort_values("fold_id").reset_index(drop=True),
    )


def test_lifecycle_spawn_must_return_an_isolated_resettable_instance():
    class BadLifecycle:
        def spawn(self, *, run_id, candidate_id, fold_id):
            del run_id, candidate_id, fold_id
            return self

        def __call__(self, data, params, train_index, test_index, fold):
            del data, params, train_index, fold
            return pd.Series(1.0, index=test_index)

    engine = WalkForwardEngine(
        strategy=BadLifecycle(),
        scorer=_neutral_scorer,
        config=_base_config(),
    )
    with pytest.raises(RuntimeError, match="spawn must return an isolated instance"):
        engine.run(data=_bars(), params={})


def test_callable_instance_is_deepcopy_isolated_and_legacy_contract_is_labeled():
    @dataclass
    class CounterStrategy:
        calls: int = 0

        def __call__(self, data, params, train_index, test_index, fold):
            del data, params, train_index, fold
            self.calls += 1
            return pd.Series(float(self.calls), index=test_index)

    original = CounterStrategy()
    result = WalkForwardEngine(
        strategy=original,
        scorer=_neutral_scorer,
        config=_base_config(),
    ).run(data=_bars(), params={})

    assert original.calls == 0
    assert set(result.oos_output.loc[result.oos_output != 0.0].unique()) == {1.0}
    lifecycle = result.metadata["strategy_lifecycle_table"]
    assert set(lifecycle["lifecycle_kind"]) == {"deepcopy_isolated"}
    assert lifecycle["certified_isolation"].all()
    assert result.metadata["intent_contract"]["route_id"] == "legacy_series_adapter_v1"
    assert result.metadata["intent_contract"]["certified"] is False


def test_class_strategy_is_instantiated_per_wfo_call():
    class ClassStrategy:
        constructions = 0

        def __init__(self):
            type(self).constructions += 1

        def __call__(self, data, params, train_index, test_index, fold):
            del data, params, train_index, fold
            return pd.Series(1.0, index=test_index)

    result = WalkForwardEngine(
        strategy=ClassStrategy,
        scorer=_neutral_scorer,
        config=_base_config(),
    ).run(data=_bars(), params={})
    lifecycle = result.metadata["strategy_lifecycle_table"]
    assert ClassStrategy.constructions == len(lifecycle)
    assert set(lifecycle["lifecycle_kind"]) == {"class_factory"}


def test_explicit_intent_contract_survives_result_and_desired_order_fails_closed():
    explicit = WfoIntentContractV1(
        kind=WfoIntentKindV1.TARGET_POSITION,
        observation_phase="bar_close",
        effective_phase="next_bar_open",
        route_id="phase64-explicit-position",
        certified=True,
    )
    result = WalkForwardEngine(
        strategy=_side_strategy,
        scorer=_neutral_scorer,
        config=_base_config(intent_contract=explicit),
    ).run(data=_bars(), params={"side": 1.0})
    assert result.metadata["intent_contract"] == explicit.metadata()

    desired = WfoIntentContractV1(
        kind=WfoIntentKindV1.DESIRED_ORDER,
        route_id="phase64-order-route",
        certified=True,
    )
    with pytest.raises(NotImplementedError, match="explicit order-tape adapter"):
        WalkForwardEngine(
            strategy=_side_strategy,
            scorer=_neutral_scorer,
            config=_base_config(intent_contract=desired),
        ).run(data=_bars(), params={"side": 1.0})


def test_fold_account_policy_is_auditable_and_unsupported_final_routes_fail_closed():
    data = _bars()
    close_result = WalkForwardEngine(
        strategy=_side_strategy,
        scorer=_neutral_scorer,
        config=_base_config(
            embargo_bars=2,
            fold_account_policy="close_at_boundary",
        ),
    ).run(data=data, params={"side": 1.0})
    plan = close_result.metadata["account_execution_plan"]
    assert plan["execution_mode"] == "single_stitched_run_with_declared_flatten_gaps"
    assert plan["final_accounting_supported"] is True
    assert all(event["gap_bars"] == 2 for event in plan["boundary_events"])
    assert all((close_result.oos_output.loc[fold.embargo_index] == 0.0).all() for fold in close_result.folds[:-1])

    endpoint_kwargs = {
        "strategy_class": _side_strategy,
        "split_mode": "2021-01-01",
        "split_frequency": "quarterly",
        "window_mode": "rolling",
        "train_window": "180D",
        "target_mode": "signal_notional",
        "initial_capital": 20_000.0,
        "alloc_per_trade": 1_000.0,
        "fee_rate": 0.0,
        "use_funding": False,
    }
    for policy, message in (
        ("reset_flat", "independent fold accounts"),
        ("replay_prior_state", "explicit order/fill replay adapter"),
    ):
        endpoint = QuantBTEndpoint.walk_forward(
            **endpoint_kwargs,
            optimization_config={"fold_account_policy": policy},
        )
        with pytest.raises(NotImplementedError, match=message):
            endpoint.backtest(data=data, symbols=["BTC"], params={"side": 1.0})

    close_endpoint = QuantBTEndpoint.walk_forward(
        **endpoint_kwargs,
        optimization_config={"fold_account_policy": "close_at_boundary", "embargo_bars": 2},
    )
    close_account_result = close_endpoint.backtest(data=data, symbols=["BTC"], params={"side": 1.0})
    assert close_account_result.metadata["walk_forward"]["account_execution"] == "single_stitched_run_with_declared_flatten_gaps"

    no_gap_endpoint = QuantBTEndpoint.walk_forward(
        **endpoint_kwargs,
        optimization_config={"fold_account_policy": "close_at_boundary", "embargo_bars": 0},
    )
    with pytest.raises(NotImplementedError, match="requires embargo/gap bars"):
        no_gap_endpoint.backtest(data=data, symbols=["BTC"], params={"side": 1.0})


def test_proxy_native_screening_records_and_enforces_without_changing_selected_candidate():
    data = _bars(end="2021-06-30")

    def native_scorer(data, output, index, fold, params, context, trading_days):
        del data, output, index, fold, context, trading_days
        side = int(params["side"])
        return {
            "sharpe": 1.0 if side == 0 else 2.0,
            "turnover": 1.0,
            "trade_count": 1.0,
            "mean_return": 0.0,
            "volatility": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": 1.0,
        }

    records = [_record(trial_id=0, side=0, objective=2.0), _record(trial_id=1, side=1, objective=1.0)]
    engine = WalkForwardEngine(
        strategy=_side_strategy,
        native_scorer=native_scorer,
        config=_base_config(
            scoring_backend="proxy",
            proxy_validation_mode="record",
            proxy_validation_top_fraction=1.0,
            proxy_min_spearman=0.75,
            proxy_min_top_k_overlap=1.0,
            proxy_max_winner_regret=0.0,
            proxy_max_false_positive_rate=0.0,
        ),
    )
    folds = engine.build_folds(data.index)
    selected = records[0]
    engine._validate_proxy_screening(data=data, folds=folds, records=records, selected=selected)
    audit = engine._proxy_validation_metadata()

    assert audit["status"] == "failed"
    assert audit["selection_mutated"] is False
    assert selected.params == {"side": 0}
    assert audit["selection_scope"] == "is_only"
    assert len(audit["rows"]) == 2

    def passing_native_scorer(data, output, index, fold, params, context, trading_days):
        del data, output, index, fold, context, trading_days
        return {
            "sharpe": 2.0 if int(params["side"]) == 0 else 1.0,
            "turnover": 1.0,
            "trade_count": 1.0,
            "mean_return": 0.0,
            "volatility": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": 1.0,
        }

    passing = WalkForwardEngine(
        strategy=_side_strategy,
        native_scorer=passing_native_scorer,
        config=_base_config(
            scoring_backend="proxy",
            proxy_validation_mode="record",
            proxy_validation_top_fraction=1.0,
            proxy_min_spearman=0.75,
            proxy_min_top_k_overlap=1.0,
            proxy_max_winner_regret=0.0,
            proxy_max_false_positive_rate=0.0,
        ),
    )
    passing._validate_proxy_screening(data=data, folds=folds, records=records, selected=selected)
    assert passing._proxy_validation_metadata()["status"] == "passed"

    enforcing = WalkForwardEngine(
        strategy=_side_strategy,
        native_scorer=native_scorer,
        config=_base_config(
            scoring_backend="proxy",
            proxy_validation_mode="enforce",
            proxy_validation_top_fraction=1.0,
            proxy_min_spearman=0.75,
            proxy_min_top_k_overlap=1.0,
            proxy_max_winner_regret=0.0,
            proxy_max_false_positive_rate=0.0,
        ),
    )
    with pytest.raises(RuntimeError, match="proxy screening contract failed"):
        enforcing._validate_proxy_screening(data=data, folds=folds, records=records, selected=selected)


def test_endpoint_forwards_phase64_metadata_without_changing_carry_route():
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_side_strategy,
        split_mode="2021-01-01",
        split_frequency="single",
        target_mode="signal_notional",
        optimization_config={
            "calendar_contract": "exact_v2",
            "label_horizon_bars": 1,
            "purge_bars": 1,
            "warmup_policy": "pre_test_from_train_tail",
            "warmup_bars": 2,
            "intent_contract": {
                "kind": "target_position",
                "observation_phase": "bar_close",
                "effective_phase": "next_bar_open",
                "route_id": "phase64-endpoint",
                "certified": True,
            },
        },
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=_bars(), symbols=["BTC"], params={"side": 1.0})
    metadata = result.metadata["walk_forward"]

    assert metadata["causality_schedule_v2"] == "retrospective_global_v2"
    assert metadata["calendar_plan"]["policy"] == "exact"
    assert metadata["label_horizon_bars"] == 1
    assert metadata["purge_bars"] == 1
    assert metadata["intent_contract"]["route_id"] == "phase64-endpoint"
    assert metadata["fold_account_policy"] == "carry_position"
