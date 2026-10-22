"""Reuse shared tape lifecycle while delegating all package execution unchanged."""

from dataclasses import asdict

from ..common import digest
from .contracts import DomainCompatibility, InputKind
from .portfolio import PortfolioDomainAdapter
from .portfolio_contract import funding_policy
from .package_contract import (package_execution_contract, validate_package_market,
                               validate_package_payload)


class PackageDomainAdapter(PortfolioDomainAdapter):
    domain = "package"
    input_kind = InputKind.PACKAGE

    def __init__(self, runtime):
        # The shared owner only holds bindings/counters, not account state.
        from .base import DomainAdapter
        DomainAdapter.__init__(self, runtime)
        scorer = runtime.engine.scorer
        self.execution_contract = package_execution_contract(scorer.config,
            runtime.engine.config, symbols=scorer.symbols)

    @property
    def metadata(self):
        from .base import DomainAdapter
        return {**DomainAdapter.metadata.fget(self),
            "package_execution": asdict(self.execution_contract),
            "legacy_family_identity_preserved": False, "empirical_promotion": False,
            "economic_evidence": "REAL_PACKAGE_ALPHA_OWNER_REVIEW_PENDING",
            "metric_authority": "original_package_account_full_report",
            "spread_proxy_metrics": False, "exchange_native_atomicity": False}

    def compatibility(self):
        scorer, cfg, c = self.runtime.engine.scorer, self.runtime.engine.config, self.execution_contract
        return DomainCompatibility(self.domain, self.input_kind, c.universe, cfg.calendar_contract,
            c.semantic_id, digest(funding_policy(scorer.score_config, c.universe)),
            scorer._meta_economics_id, scorer._meta_adapter.contract.metric_id, c.timing,
            c.diagnostic_account, c.final_account, "original-package-account-result-v1")

    def validate_payload(self, payload, index):
        validate_package_payload(payload, index)

    def validate_market(self, data, index, folds):
        validate_package_market(data, index, self.execution_contract.universe)
        super().validate_market(data, index, folds)

    def _execute_diagnostic(self, endpoint, data, payload, symbols):
        return endpoint.backtest(data=data, signal=payload, symbols=symbols)

