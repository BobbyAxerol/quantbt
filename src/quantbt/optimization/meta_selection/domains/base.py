"""Thin lifecycle/telemetry boundary; financial and prepared owners stay external."""

from ..common import MetaRecordError, digest, wire
from .contracts import DomainCompatibility, EvaluationBinding, EvaluationEvidence, MarketBinding


class DomainAdapter:
    def __init__(self, runtime):
        self.runtime = runtime
        self.closed = self.canceled = self.executing = False
        self.market_binding = None
        self._retained_telemetry = None
        self.stats = dict(input_bindings=0, financial_delegate_calls=0,
                          original_observations=0, market_validations=0)

    def _check(self):
        from ....core.runtime_governance import RuntimeCanceledError

        if self.closed:
            raise MetaRecordError("META_DOMAIN_ADAPTER_CLOSED")
        if self.canceled:
            raise RuntimeCanceledError("meta domain adapter canceled")

    def bind_input(self, *, payload, index, params, stage, input_signature,
                   information_as_of, decision_sealed_at=None):
        self._check()
        self.validate_payload(payload, index)
        binding = EvaluationBinding(self.domain, self.input_kind, stage, index, params,
            payload, input_signature, information_as_of, decision_sealed_at)
        self.stats["input_bindings"] += 1
        return binding

    def _validate_binding(self, binding):
        self._check()
        if (not isinstance(binding, EvaluationBinding) or binding.domain != self.domain
                or binding.input_kind != self.input_kind):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH")
        self.validate_payload(binding.payload, binding.index)

    def evaluate(self, binding, execute):
        self._validate_binding(binding)
        if self.executing or not callable(execute):
            raise MetaRecordError("META_DOMAIN_EVALUATOR_INVALID")
        self.executing = True
        self.stats["financial_delegate_calls"] += 1
        try:
            result = execute(binding)
            self._check()
            return result
        finally:
            self.executing = False

    def observe(self, binding, result, *, metric_adapter, economics_id, prepared_witness=None):
        self._validate_binding(binding)
        observation = metric_adapter.observe(result, expected_index=binding.index,
            economics_id=economics_id, input_signature=binding.input_signature,
            prepared_witness=prepared_witness)
        self.stats["original_observations"] += 1
        return EvaluationEvidence(binding, observation, result)

    @property
    def metadata(self):
        return dict(schema="qms-domain-adapter-telemetry-v1", domain=self.domain,
            input_kind=self.input_kind.value, **self.stats, financial_replays=0,
            adapter_market_array_copies=0, adapter_owned_market_bytes=0,
            adapter_pyo3_calls=0, financial_ffi_calls="EXISTING_OWNER_TELEMETRY",
            callback_scope="financial_delegate_only_not_per_bar",
            market_binding=wire(self.market_binding) if self.market_binding else None,
            legacy_family_identity_preserved=True, closed=self.closed, canceled=self.canceled)

    def bind_market(self, data, index):
        """Use the existing run witness, once; never re-pack market arrays."""
        from ..observer import market_signature
        from ..witness import PreparedMetricWitness

        owner = self.runtime
        scorer, config = owner.engine.scorer, owner.engine.config
        witness = getattr(scorer, "_meta_witness", None)
        prepared = getattr(owner.engine, "_prepared_context", None)
        source = (witness.market_signature(data, index) if witness is not None else
            market_signature(data, index, config=scorer.score_config))
        if prepared is not None:
            source = digest({"prepared": prepared.signature, "witness": source})
        execution = scorer.score_config
        compatibility = DomainCompatibility(self.domain, self.input_kind,
            tuple(scorer.symbols or [owner.context.instrument_id]), config.calendar_contract,
            digest({"instrument": owner.context.instrument_id, "asset": execution.asset_type,
                    "contract_size": execution.contract_size}),
            digest({"use_funding": execution.use_funding,
                    "source": "aligned_series" if hasattr(execution.funding_rate, "index") else execution.funding_rate}),
            scorer._meta_economics_id, scorer._meta_adapter.contract.metric_id,
            digest(config.intent_contract.metadata()), "reset_flat", config.fold_account_policy,
            "original-reactive-window-v1" if self.domain == "reactive" else "original-result-or-same-pass-v1")
        self.market_binding = MarketBinding(owner.context.run_id, source,
            digest(PreparedMetricWitness.calendar_key(index)), scorer._meta_economics_id,
            source, compatibility)
        # Exact source binds funding/constraints as well as OHLCV; the nominal
        # funding policy alone is intentionally not an evaluation-reuse key.

    def finalize(self, result):
        self._retained_telemetry = self.metadata
        result.metadata["meta_selection"]["domain_adapter"] = self._retained_telemetry

    def reset(self):
        if self.closed or self.executing:
            raise MetaRecordError("META_DOMAIN_RESET_INVALID")
        self.canceled = False
        self.market_binding = None
        self.stats = dict.fromkeys(self.stats, 0)

    def cancel(self):
        self._check()
        self.canceled = True

    def clear(self):
        if self.executing:
            raise MetaRecordError("META_DOMAIN_CLEAR_DURING_EXECUTION")
        self.runtime = None
        self.closed = True
        if self._retained_telemetry is not None:
            self._retained_telemetry.update(self.metadata)
            self._retained_telemetry = None
