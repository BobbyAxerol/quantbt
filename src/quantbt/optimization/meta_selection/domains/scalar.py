"""Scalar-only assumptions live here; the legacy endpoint owns all execution."""

from dataclasses import replace

import pandas as pd

from ..common import MetaRecordError, utc
from ..observer import market_signature
from .base import DomainAdapter
from .contracts import DomainEvaluationOutput, EvaluationStage, InputKind


class ScalarDomainAdapter(DomainAdapter):
    domain = "scalar"
    input_kind = InputKind.SCALAR_TARGET

    def validate_payload(self, payload, index):
        if not isinstance(payload, pd.Series) or not payload.index.equals(index):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: exact scalar target Series required")

    def validate_market(self, data, index, folds):
        self._check()
        if not isinstance(data, pd.DataFrame) or len(folds) > self.runtime.config.max_folds:
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: bounded single DataFrame tape required")
        if (not isinstance(index, pd.DatetimeIndex) or len(index) == 0 or not index.is_unique
                or not index.is_monotonic_increasing or not data.index.equals(index)):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: exact unique calendar required")
        utc(index[0])
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
