"""W3 adapter: existing native window execution, shared causal selector/history."""

from .observer import canonical_metric_contract, economics_identity
from .reactive_transport import ReactiveDetachedMetricAdapter
from .runtime import PublicMetaRuntime
from .witness import PreparedMetricWitness


class ReactiveMetricBoundary:
    meta_metric_support = True
    meta_route_id = "reactive-native-original-reset-v1"
    meta_account_authority = "existing_native_segmented_reset_flat"

    def __init__(self, runtime):
        self.runtime = runtime
        self.score_config = runtime.endpoint.config
        self.symbols = runtime.symbols
        self._meta_adapter = ReactiveDetachedMetricAdapter(canonical_metric_contract(
            trading_days=runtime.config.scoring_trading_days))
        self._meta_economics_id = economics_identity(self.score_config, symbols=self.symbols)
        self._meta_witness = PreparedMetricWitness(runtime.data, config=self.score_config)
        self.lifecycle = []
        self._executor = None
        self._verified_calls = 0
        self._packet_bytes = 0
        self._max_packet_bytes = 0

    def executor(self):
        from .reactive_execution import OriginalReactiveWitnessExecutor

        if self._executor is None:
            owner = self.runtime
            self._executor = OriginalReactiveWitnessExecutor(adapter=owner._adapter,
                prepared_runner=owner._prepared_runner, data=owner.data,
                trading_days=owner.config.scoring_trading_days,
                max_wall_time_ms=owner.runtime_config.runtime_budget.max_wall_time_ms,
                witness=self._meta_witness)
        return self._executor

    def cancel_active(self):
        if self._executor is not None:
            self._executor.cancel_active()

    def execute(self, marker, *, include_observation=True, observer_seed=None):
        owner, task = self.runtime, marker.task
        owner._check_canceled()
        executor = self.executor()
        binding = executor.binding(marker, observer_seed=observer_seed)
        if owner.runtime_config.worker_mode == "process":
            from ...backends.reactive_wfo_workers import ReactiveWfoWorkerError
            from .common import MetaRecordError

            try:
                packet = owner._ensure_process_worker().score(marker,
                    canceled=lambda: owner._cancel.canceled, witness_binding=binding)
            except ReactiveWfoWorkerError as exc:
                raise MetaRecordError("REACTIVE_WITNESS_TRANSPORT_ABORTED: " + str(exc)) from exc
        else:
            packet, _fingerprint = executor.execute(marker, observer_seed=observer_seed)
        owner._check_canceled()
        index = owner._prepared_runner.idx[task.start_bar:task.end_bar]
        packet.validate(binding=binding, index=index, initial_capital=self.score_config.account.initial_capital)
        import json

        size = len(json.dumps(packet.to_payload(), sort_keys=True).encode())
        self._verified_calls += 1
        self._packet_bytes += size
        self._max_packet_bytes = max(self._max_packet_bytes, size)
        row = packet.row()
        if not include_observation:
            row.pop("meta_observation")
        if task.stage == "post_seal_counterfactual_forward":
            self.lifecycle.append(dict(stage=task.stage, fold_id=task.fold_id,
                candidate_id=task.candidate_id, fresh_account=True, fresh_strategy=True))
        return row, packet, binding.market_id

    def metadata(self):
        return dict(schema="quantbt-reactive-witness-transport-v1",
            worker_mode=self.runtime.runtime_config.worker_mode, verified_calls=self._verified_calls,
            packet_bytes_total=self._packet_bytes, max_packet_bytes=self._max_packet_bytes,
            packet_bytes_encoding="json_utf8_not_pipe_envelope",
            market_ipc_bytes_per_task=0, financial_replays=0,
            retained_result_paths=0, original_window_paths_temporarily_retained=True,
            cooperative_native_deadline=self.runtime.runtime_config.runtime_budget.max_wall_time_ms,
            batch_public_meta_activation=False, continuous_carry=False, multi_symbol=False)

    def close(self):
        try:
            if self._executor is not None:
                self._executor.close()
            self._meta_witness.validate_source()
        finally:
            self._meta_witness.close()


class ReactiveMetaRuntime(PublicMetaRuntime):
    def finalize(self, result):
        super().finalize(result)
        result.metadata["meta_selection"]["witness_transport"] = self.engine.scorer.metadata()
