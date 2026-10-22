"""Scalar-only assumptions live here; the legacy endpoint owns all execution."""

from dataclasses import replace

import pandas as pd

from ..common import MetaRecordError, digest, utc
from ..observer import market_signature
from .base import DomainAdapter
from .contracts import DomainCompatibility, DomainEvaluationOutput, EvaluationStage, InputKind
from .scalar_contract import scalar_execution_contract, validate_scalar_payload


class ScalarDomainAdapter(DomainAdapter):
    domain = "scalar"
    input_kind = InputKind.SCALAR_TARGET

    def __init__(self, runtime):
        super().__init__(runtime)
        self.execution_contract = scalar_execution_contract(runtime.engine.scorer.config, runtime.engine.config)
        if runtime.engine.scorer.symbols and len(runtime.engine.scorer.symbols) != 1:
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: scalar meta requires one symbol")

    @property
    def metadata(self):
        from dataclasses import asdict
        return {**super().metadata, "scalar_execution": asdict(self.execution_contract),
                "legacy_family_identity_preserved": self.execution_contract.legacy_family,
                "empirical_promotion": False, "economic_evidence": "CELL_OWNER_REVIEW_REQUIRED"}

    def compatibility(self):
        owner = self.runtime
        scorer, config = owner.engine.scorer, owner.engine.config
        execution = scorer.score_config
        return DomainCompatibility("scalar", self.input_kind,
            tuple(scorer.symbols or [owner.context.instrument_id]), config.calendar_contract,
            digest({"instrument": owner.context.instrument_id, "asset": execution.asset_type,
                    "contract_size": execution.contract_size}),
            digest({"use_funding": execution.use_funding,
                    "source": "aligned_series" if hasattr(execution.funding_rate, "index") else execution.funding_rate}),
            scorer._meta_economics_id, scorer._meta_adapter.contract.metric_id,
            self.execution_contract.scorer_contract, "reset_flat", config.fold_account_policy,
            "original-result-or-same-pass-v1")

    def bind_market(self, data, index):
        super().bind_market(data, index)
        if not self.execution_contract.legacy_family:
            self.market_binding = replace(self.market_binding, compatibility=self.compatibility())

    def validate_payload(self, payload, index):
        validate_scalar_payload(payload, index, self.execution_contract.route)

    def validate_market(self, data, index, folds):
        self._check()
        if not isinstance(data, pd.DataFrame) or len(folds) > self.runtime.config.max_folds:
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: bounded single DataFrame tape required")
        if (not isinstance(index, pd.DatetimeIndex) or len(index) == 0 or not index.is_unique
                or not index.is_monotonic_increasing or not data.index.equals(index)):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: exact unique calendar required")
        utc(index[0])
        if self.domain == "scalar" and self.execution_contract.route == "dca_ladder":
            import numpy as np
            if not {"high", "low", "close"}.issubset(data.columns):
                raise MetaRecordError("META_ROUTE_UNSUPPORTED: ladder requires actual high/low/close")
            high, low, close = (data[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
            if (not all(np.isfinite(x).all() for x in (high, low, close)) or
                    (low <= 0).any() or (high < close).any() or (low > close).any()):
                raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: invalid ladder high/low/close")
        if any(len(f.train_index) < 2 or len(f.test_index) < 2 for f in folds):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: finite diagnostic windows require >=2 bars")
        self.stats["market_validations"] += 1
        self.bind_market(data, index)

    def observer_evaluator(self, data, fold, task):
        from ....endpoint import QuantBTEndpoint
        from ....walkforward import WalkForwardEngine
        from ..runtime import isolated_observer_rng

        owner = self.runtime
        cfg = replace(owner.engine.config, meta_selection=None)
        auxiliary = WalkForwardEngine(owner.engine.strategy, cfg, scorer=owner.engine.scorer)
        auxiliary._prepared_context = owner.engine._prepared_context
        auxiliary._strategy_market_fingerprints = {}
        auxiliary._lifecycle_records, auxiliary._lifecycle_records_dropped = [], 0
        witness = getattr(owner.engine.scorer, "_meta_witness", None)

        def evaluate(candidate):
            self._check()
            with isolated_observer_rng(task.resolved_fold_seed + candidate.native_trial_id + 1):
                output = auxiliary._call_strategy(data, dict(candidate.effective_params), fold)
                self.validate_payload(output, fold.test_index)
                prefix = data.loc[:fold.test_index[-1]]
                diagnostic = QuantBTEndpoint(owner.engine.scorer.score_config)
                signature = (witness.market_signature(prefix, fold.test_index)
                    if witness is not None else market_signature(prefix, fold.test_index,
                        config=owner.engine.scorer.score_config))
                binding = self.bind_input(payload=output, index=fold.test_index,
                    params=candidate.effective_params, stage=EvaluationStage.POST_SEAL_FORWARD,
                    input_signature=signature, information_as_of=task.data_cutoff,
                    decision_sealed_at=task.decision_sealed_at)
                result = self.evaluate(binding, lambda b: diagnostic.backtest(
                    data=prefix.loc[fold.test_index], signal=b.payload,
                    symbols=owner.engine.scorer.symbols))
                return DomainEvaluationOutput(binding, result)

        return evaluate, auxiliary._lifecycle_records
