"""Meta observes the original shared account; it never reconstructs economics."""

from dataclasses import asdict, replace

from ..common import MetaRecordError, digest
from ..observer import market_signature
from ..witness import PreparedMetricWitness
from .base import DomainAdapter
from .contracts import DomainCompatibility, DomainEvaluationOutput, EvaluationStage, InputKind, MarketBinding
from .portfolio_contract import (funding_policy, portfolio_execution_contract,
                                 validate_portfolio_market, validate_portfolio_payload)


class PortfolioDomainAdapter(DomainAdapter):
    domain = "portfolio"
    input_kind = InputKind.POSITION_MATRIX

    def __init__(self, runtime):
        super().__init__(runtime)
        scorer = runtime.engine.scorer
        self.execution_contract = portfolio_execution_contract(scorer.config,
            runtime.engine.config, symbols=scorer.symbols, require_universe=True)

    @property
    def metadata(self):
        return {**super().metadata, "portfolio_execution": asdict(self.execution_contract),
                "legacy_family_identity_preserved": False, "empirical_promotion": False,
                "economic_evidence": "REAL_PORTFOLIO_ALPHA_OWNER_REVIEW_PENDING",
                "metric_authority": "original_aggregate_shared_account_full_report",
                "symbol_average_metrics": False}

    def compatibility(self):
        scorer, cfg = self.runtime.engine.scorer, self.runtime.engine.config
        c = self.execution_contract
        return DomainCompatibility(self.domain, self.input_kind, c.universe, cfg.calendar_contract,
            c.semantic_id, digest(funding_policy(scorer.score_config, c.universe)),
            scorer._meta_economics_id, scorer._meta_adapter.contract.metric_id, c.timing,
            c.diagnostic_account, c.final_account, "original-shared-account-result-v1")

    def validate_payload(self, payload, index):
        validate_portfolio_payload(payload, index, self.execution_contract.universe)

    def validate_market(self, data, index, folds):
        self._check()
        if len(folds) > self.runtime.config.max_folds or any(
                len(f.train_index) < 2 or len(f.test_index) < 2 for f in folds):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: bounded portfolio diagnostic windows required")
        validate_portfolio_market(data, index, self.execution_contract.universe)
        self.stats["market_validations"] += 1
        self.bind_market(data, index)

    def bind_market(self, data, index):
        scorer = self.runtime.engine.scorer
        witness = getattr(scorer, "_meta_witness", None)
        source = (witness.market_signature(data, index) if witness is not None else
                  market_signature(data, index, config=scorer.score_config))
        prepared = getattr(self.runtime.engine, "_prepared_context", None)
        if prepared is not None:
            source = digest({"prepared": prepared.signature, "witness": source})
        self.market_binding = MarketBinding(self.runtime.context.run_id, source,
            digest(PreparedMetricWitness.calendar_key(index)), scorer._meta_economics_id,
            source, self.compatibility())

    def observer_evaluator(self, data, fold, task):
        from ....endpoint import QuantBTEndpoint
        from ....walkforward import WalkForwardEngine
        from ..runtime import isolated_observer_rng

        owner = self.runtime
        auxiliary = WalkForwardEngine(owner.engine.strategy,
            replace(owner.engine.config, meta_selection=None), scorer=owner.engine.scorer)
        auxiliary._prepared_context = owner.engine._prepared_context
        auxiliary._strategy_market_fingerprints = {}
        auxiliary._lifecycle_records, auxiliary._lifecycle_records_dropped = [], 0
        scorer = owner.engine.scorer
        witness = scorer._meta_witness

        def evaluate(candidate):
            self._check()
            with isolated_observer_rng(task.resolved_fold_seed + candidate.native_trial_id + 1):
                output = auxiliary._call_strategy(data, dict(candidate.effective_params), fold)
                prefix = {s: data[s].loc[:fold.test_index[-1]] for s in self.execution_contract.universe}
                signature = (witness.market_signature(prefix, fold.test_index) if witness is not None
                             else market_signature(prefix, fold.test_index, config=scorer.score_config))
                binding = self.bind_input(payload=output, index=fold.test_index,
                    params=candidate.effective_params, stage=EvaluationStage.POST_SEAL_FORWARD,
                    input_signature=signature, information_as_of=task.data_cutoff,
                    decision_sealed_at=task.decision_sealed_at)
                diagnostic = QuantBTEndpoint(scorer.score_config)
                result = self.evaluate(binding, lambda b: diagnostic.backtest(
                    data={s: frame.loc[fold.test_index] for s, frame in prefix.items()},
                    positions=b.payload, symbols=scorer.symbols))
                return DomainEvaluationOutput(binding, result)

        return evaluate, auxiliary._lifecycle_records
