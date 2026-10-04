"""W3 adapter: existing native window execution, shared causal selector/history."""

from .common import wire
from .observer import ResultMetricAdapter, canonical_metric_contract, economics_identity
from .runtime import PublicMetaRuntime, isolated_observer_rng
from .witness import PreparedMetricWitness


class ReactiveMetricBoundary:
    meta_metric_support = True
    meta_route_id = "reactive-native-original-reset-v1"
    meta_account_authority = "existing_native_segmented_reset_flat"

    def __init__(self, runtime):
        self.runtime = runtime
        self.score_config = runtime.endpoint.config
        self.symbols = runtime.symbols
        self._meta_adapter = ResultMetricAdapter(canonical_metric_contract(
            trading_days=runtime.config.scoring_trading_days))
        self._meta_economics_id = economics_identity(self.score_config, symbols=self.symbols)
        self._meta_witness = PreparedMetricWitness(runtime.data, config=self.score_config)
        self.lifecycle = []

    def execute(self, marker, *, include_observation=True):
        from ...endpoint import _attach_endpoint_run_config
        from ...backends.reactive_wfo_workers import _score_row_from_scalar_payload

        owner, task = self.runtime, marker.task
        owner._check_canceled()
        strategy = owner._adapter.build_strategy(params=marker.params, task=task)
        result = owner._prepared_runner.run_window(strategy, start_bar=task.start_bar,
            end_bar=task.end_bar, report_level="minimal",
            _metric_witness_trading_days=owner.config.scoring_trading_days)
        _attach_endpoint_run_config(result, self.score_config)
        index = owner._prepared_runner.idx[task.start_bar:task.end_bar]
        signature = self._meta_witness.market_signature(owner.data, index)
        row = _score_row_from_scalar_payload(result.metadata["reactive_numeric_observability"]["same_pass_score"])
        if include_observation:
            report = result.full_report(trading_days=owner.config.scoring_trading_days, scope="full")
            observation = self._meta_adapter.observe(result, expected_index=index,
                economics_id=self._meta_economics_id, input_signature=signature, report=report,
                execution_config=self.score_config, prepared_witness=self._meta_witness)
            row["meta_observation"] = wire(observation)
        if task.stage == "post_seal_counterfactual_forward":
            self.lifecycle.append(dict(stage=task.stage, fold_id=task.fold_id,
                candidate_id=task.candidate_id, fresh_account=True, fresh_strategy=True))
        return row, result, signature

    def close(self):
        try:
            self._meta_witness.validate_source()
        finally:
            self._meta_witness.close()


class ReactiveMetaRuntime(PublicMetaRuntime):
    def observer_evaluator(self, data, fold, task):
        from ...backends.reactive_wfo_support import ReactiveWfoScoreMarkerV1

        boundary = self.engine.scorer
        lifecycle_start = len(boundary.lifecycle)

        def evaluate(candidate):
            from time import perf_counter

            with isolated_observer_rng(task.resolved_fold_seed + candidate.native_trial_id + 1):
                marker = ReactiveWfoScoreMarkerV1(task=boundary.runtime.make_task(
                    params=candidate.effective_params, fold=fold, evaluation_index=fold.test_index,
                    stage="post_seal_counterfactual_forward"), params=dict(candidate.effective_params))
                started = perf_counter()
                _, result, signature = boundary.execute(marker, include_observation=False)
                boundary.runtime._score_calls += 1
                boundary.runtime._score_bars += marker.task.bars
                boundary.runtime._score_seconds += perf_counter() - started
                return result, signature

        # The observer records each callback/account reset once. No original
        # result or strategy is retained in this lightweight lifecycle view.
        class LifecycleView:
            def __iter__(self):
                return iter(boundary.lifecycle[lifecycle_start:])

        return evaluate, LifecycleView()
