"""Meta consumes original intrabar/callback/command account outcomes."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..common import MetaRecordError, digest
from ..observer import market_signature
from .base import DomainAdapter
from .contracts import DomainCompatibility, DomainEvaluationOutput, EvaluationStage
from .registry import capability


class ExecutionDomainAdapter(DomainAdapter):
    def __init__(self, runtime):
        super().__init__(runtime)
        row = capability(runtime.engine.config.target_mode, require_active=True)
        self.domain, self.input_kind = row.domain, row.input_kind
        self.execution_contract = SimpleNamespace(legacy_family=False)

    def compatibility(self):
        from ....endpoint import _jsonable
        from .portfolio_contract import funding_policy
        s, c = self.runtime.engine.scorer, self.runtime.engine.config
        execution = s.score_config
        universe = tuple(s.symbols or execution.symbols or [self.runtime.context.instrument_id])
        return DomainCompatibility(self.domain, self.input_kind,
            universe, c.calendar_contract,
            digest({"contract_size": _jsonable(execution.contract_size), "asset_type": execution.asset_type}),
            digest(funding_policy(execution, universe)), s._meta_economics_id,
            s._meta_adapter.contract.metric_id,
            digest({"route": c.target_mode, "metadata": _jsonable(execution.metadata)}),
            "reset_flat", c.fold_account_policy, "original-execution-window-v1")

    @property
    def metadata(self):
        return {**super().metadata, "legacy_family_identity_preserved": False,
            "metric_authority": "original_execution_account_full_report",
            "empirical_promotion": False, "economic_evidence": "SYNTHETIC_CONFORMANCE_ONLY"}

    def validate_payload(self, payload, index):
        from ....wfo_execution import WfoExecutionWindow
        if not isinstance(payload, WfoExecutionWindow) or payload.route != self.runtime.engine.config.target_mode:
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: typed execution window required")
        payload.slice(index)

    def validate_market(self, data, index, folds):
        route = self.runtime.engine.config.target_mode
        symbols = tuple(self.runtime.engine.scorer.score_config.symbols or ())
        if isinstance(data, dict):
            if set(data) != set(symbols) or route in {"intrabar", "event_driven"}:
                raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: explicit universe / single callback tape required")
        elif len(symbols) != 1:
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: one DataFrame cannot stand for multiple instruments")
        frames = tuple(data.values()) if isinstance(data, dict) else (data,)
        if len(folds) > self.runtime.config.max_folds:
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: fold capacity exceeded")
        for frame in frames:
            if (not isinstance(frame, pd.DataFrame) or not frame.index.equals(index)
                    or frame.index.tz is None or not {"open", "high", "low", "close"}.issubset(frame)):
                raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: exact authoritative OHLC calendar required")
            values = frame[["open", "high", "low", "close"]].to_numpy(float)
            if not np.isfinite(values).all() or (values <= 0).any():
                raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: invalid OHLC")
            if (np.any(values[:, 1] < np.maximum(values[:, 0], values[:, 3]))
                    or np.any(values[:, 2] > np.minimum(values[:, 0], values[:, 3]))):
                raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: invalid OHLC envelope")
        self.bind_market(data, index)
        self.market_binding = replace(self.market_binding, compatibility=self.compatibility())
        self.stats["market_validations"] += 1

    def observer_evaluator(self, data, fold, task):
        from ....walkforward import WalkForwardEngine
        from ....wfo_execution import execute_window
        from ..runtime import isolated_observer_rng
        owner = self.runtime
        auxiliary = WalkForwardEngine(owner.engine.strategy,
            replace(owner.engine.config, meta_selection=None), scorer=owner.engine.scorer)
        auxiliary._prepared_context = owner.engine._prepared_context
        auxiliary._strategy_market_fingerprints = {}
        auxiliary._lifecycle_records, auxiliary._lifecycle_records_dropped = [], 0
        scorer = owner.engine.scorer

        def evaluate(candidate):
            with isolated_observer_rng(task.resolved_fold_seed + candidate.native_trial_id + 1):
                output = auxiliary._call_strategy(data, dict(candidate.effective_params), fold).slice(fold.test_index)
                prefix = ({s: f.loc[:fold.test_end] for s, f in data.items()}
                          if isinstance(data, dict) else data.loc[:fold.test_end])
                witness = scorer._meta_witness
                signature = (witness.market_signature(prefix, fold.test_index) if witness is not None
                             else market_signature(prefix, fold.test_index, config=scorer.score_config))
                binding = self.bind_input(payload=output, index=fold.test_index,
                    params=candidate.effective_params, stage=EvaluationStage.POST_SEAL_FORWARD,
                    input_signature=signature, information_as_of=task.data_cutoff,
                    decision_sealed_at=task.decision_sealed_at)
                result = self.evaluate(binding, lambda b: execute_window(scorer.score_config,
                    prefix, b.payload, symbols=scorer.symbols))
                return DomainEvaluationOutput(binding, result)
        return evaluate, auxiliary._lifecycle_records
