"""Original-result witness execution on the prepared W3 financial runtime."""

from contextlib import nullcontext

from ...core.runtime_governance import RuntimeBudgetError, RuntimeCanceledError
from .observer import ResultMetricAdapter, canonical_metric_contract, economics_identity
from .reactive_transport import DetachedReactiveWitnessV1, ReactiveWitnessBindingV1
from .runtime import isolated_observer_rng
from .witness import PreparedMetricWitness


class OriginalReactiveWitnessExecutor:
    """Run/reduce once; retain no account/result paths after returning a packet.

    The process worker inherits this owner through fork/COW. Neither market nor
    strategy/model/history state is serialized in an individual request.
    """

    def __init__(self, *, adapter, prepared_runner, data, trading_days, max_wall_time_ms=None,
                 witness=None):
        self.adapter = adapter
        self.prepared_runner = prepared_runner
        self.data = data
        self.config = prepared_runner.endpoint.config
        self.trading_days = int(trading_days)
        self.max_wall_time_ms = max_wall_time_ms
        self.metric_adapter = ResultMetricAdapter(canonical_metric_contract(trading_days=trading_days))
        self.economics_id = economics_identity(self.config, symbols=prepared_runner.symbols)
        self.witness = witness or PreparedMetricWitness(data, config=self.config)
        self.active_runner = None
        self.runs = 0
        self.closed = False

    def binding(self, marker, *, observer_seed=None):
        index = self.prepared_runner.idx[marker.task.start_bar:marker.task.end_bar]
        return ReactiveWitnessBindingV1.prepare(marker, index=index, witness=self.witness,
            data=self.data, economics_id=self.economics_id,
            metric_id=self.metric_adapter.contract.metric_id, observer_seed=observer_seed)

    def attach(self, runner):
        """Private native safe-point control, never a second accounting loop."""
        self.active_runner = runner
        runner.set_deadline_ms(self.max_wall_time_ms)

    def detach(self):
        self.active_runner = None

    def cancel_active(self):
        if self.active_runner is not None:
            self.active_runner.request_cancel()

    def execute(self, marker, *, observer_seed=None):
        from ...endpoint import _attach_endpoint_run_config
        from ...backends.reactive_wfo_workers import _score_row_from_scalar_payload

        if self.closed:
            raise RuntimeError("original reactive witness executor is closed")
        task = marker.task
        binding = self.binding(marker, observer_seed=observer_seed)
        rng = isolated_observer_rng(observer_seed) if observer_seed is not None else nullcontext()
        try:
            with rng:
                strategy = self.adapter.build_strategy(params=marker.params, task=task)
                result = self.prepared_runner.run_window(strategy, start_bar=task.start_bar,
                    end_bar=task.end_bar, report_level="minimal",
                    _metric_witness_trading_days=self.trading_days, _metric_witness_control=self)
        except Exception as exc:
            if "reactive native execution canceled at a certified bar boundary" in str(exc):
                raise RuntimeCanceledError("reactive witness canceled at native bar boundary") from exc
            if "reactive native execution deadline exceeded at a certified bar boundary" in str(exc):
                raise RuntimeBudgetError("MAX_WALL_TIME", "reactive witness native deadline exceeded") from exc
            raise
        _attach_endpoint_run_config(result, self.config)
        index = self.prepared_runner.idx[task.start_bar:task.end_bar]
        row = _score_row_from_scalar_payload(result.metadata["reactive_numeric_observability"]["same_pass_score"])
        observation = self.metric_adapter.observe(result, expected_index=index,
            economics_id=self.economics_id, input_signature=binding.market_id,
            execution_config=self.config, prepared_witness=self.witness)
        packet = DetachedReactiveWitnessV1.prepare(binding, row, observation)
        packet.validate(binding=binding, index=index, initial_capital=self.config.account.initial_capital)
        fingerprint = getattr(strategy, "quantbt_state_fingerprint", None)
        self.runs += 1
        return packet, fingerprint() if callable(fingerprint) else None

    def close(self):
        if self.closed:
            return
        try:
            self.witness.validate_source()
        finally:
            self.witness.close()
            self.active_runner = None
            self.closed = True

    def metadata(self):
        return dict(schema="quantbt-reactive-original-witness-executor-v1", session_runs=self.runs,
            closed=self.closed, active_native_score=self.active_runner is not None,
            max_wall_time_ms=self.max_wall_time_ms, retained_result_paths=0,
            financial_replays=0, witness=self.witness.metadata)
