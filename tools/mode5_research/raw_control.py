"""Raw whole-account control over the shared sampler and ordered study owner.

This research control neither executes finance nor qualifies a provider. The
caller supplies an independently authorized continuous evaluation and expected
request. Its finite-Sharpe eligibility is not the challenger's annual gates.
"""

from dataclasses import dataclass
import math

import optuna

from quantbt.mode5.continuous import ContinuousAccountEvaluation, ContinuousObservationRequest
from quantbt.mode5.continuous_runtime import _GeometryBridge
from quantbt.mode5.continuous_eligibility import WholeAccountEligibility
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.records import Record
from quantbt.optimization.study_schedule import run_ordered_study
from quantbt.optimization.meta_selection.common import wire


SCHEMA = "mode5.raw_whole_sharpe_control.v1"


def whole_score(evaluation, expected_request):
    """Read the original observed score; no rescore or annual-mean substitution."""
    if (not isinstance(evaluation, ContinuousAccountEvaluation)
            or not isinstance(expected_request, ContinuousObservationRequest)
            or evaluation.request != expected_request
            or evaluation.execution.request_identity != expected_request.identity
            or expected_request.role != "formal_search"):
        raise ValueError("exact typed formal-query request and original continuous account required")
    value = evaluation.raw_whole_sharpe
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite original whole-account Sharpe or explicit undefined required")
    return value


@dataclass(frozen=True)
class RawControlSeal:
    """A separate preregistered control, not a substituted challenger recipe."""

    contract_identity: str
    dossier_identity: str
    provider_qualification_identity: str
    registration_identity: str
    budget: int
    seed: int
    batch_size: int = 1
    eligibility_policy: Record | None = None

    def __post_init__(self):
        for name in ("contract_identity", "dossier_identity", "provider_qualification_identity",
                     "registration_identity"):
            value = getattr(self, name)
            if (not isinstance(value, str) or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("externally sealed exact control/context identities required")
        if (type(self.budget) is not int or self.budget < 1 or type(self.seed) is not int
                or type(self.batch_size) is not int or self.batch_size < 1):
            raise ValueError("explicit query budget, seed and observation schedule required")
        if self.eligibility_policy is not None:
            WholeAccountEligibility.read(self.eligibility_policy)

    @property
    def identity(self):
        from dataclasses import asdict
        values = asdict(self)
        if self.eligibility_policy is None:
            values.pop("eligibility_policy")
        return digest(dict(schema=SCHEMA, **values, objective="original_raw_whole_account_sharpe",
            eligibility="finite_whole_sharpe_only" if self.eligibility_policy is None else "matched_whole_quality_annual_risk_support_v1",
            tie_break="candidate_id_lexicographic_v1"))


class RawWholeControl:
    """Own only the control ledger and immutable delivered accounts."""

    def __init__(self, seal, contract, bridge):
        if not isinstance(seal, RawControlSeal) or seal.contract_identity != contract.identity:
            raise ValueError("control must bind its exact authorized observation contract")
        if (bridge.budget != seal.budget or bridge.seed != seal.seed
                or bridge.space.specs != contract.geometry.specs):
            raise ValueError("actual shared sampler budget/seed/original geometry differ from control")
        self.seal, self.contract = seal, contract
        self.bridge = _GeometryBridge(bridge, contract.geometry)
        self.rows, self.accounts, self.study = [], {}, None

    def run(self, query, *, cancellation=None, deadline_seconds=None):
        """Each query returns (expected request, delivered immutable evaluation).

        The caller must check external source/role/provider receipts before this
        method. Identity pins are prerequisites, not proof of finance authority.
        No warm starts, old observations or source-success claims are inferred.
        """
        if self.study is not None:
            raise RuntimeError("one fresh control per run; use declared checkpoint semantics for continuation")
        if not callable(query):
            raise TypeError("qualified financial query callback required")
        self.bridge.sampler()
        self.study = optuna.create_study(direction="maximize", sampler=self.bridge.observed,
                                        pruner=optuna.pruners.NopPruner())
        seen = {}

        def evaluate(trial, suggested):
            requested, params = suggested
            point = self.contract.geometry.resolve(params)
            row = dict(trial_id=trial.number, requested_params=requested, effective_params=params,
                       candidate_id=point.identity, state="RUNNING", score=None, evaluation_ref=None)
            self.rows.append(row)
            if point.identity in seen:
                row.update(state="PRUNED", reason="DUPLICATE_EFFECTIVE_PARAMS",
                           evaluation_ref=seen[point.identity])
                trial.set_user_attr("qms_rejection_reason", "DUPLICATE_EFFECTIVE_PARAMS")
                raise optuna.TrialPruned("DUPLICATE_EFFECTIVE_PARAMS")
            try:
                request, account = query(params, trial.number)
                if (request.contract_identity != self.contract.identity or request.point != point
                        or request.source_identity != self.contract.source.identity):
                    raise ValueError("control query differs from authorized original source/contract/point")
                score = whole_score(account, request)
                self.accounts[trial.number] = account
                seen[point.identity] = account.identity
                row.update(evaluation_ref=account.identity, raw_whole_sharpe=score,
                    annual_mean_raw_sharpe=None, objective="original_raw_whole_account_sharpe",
                    score=score, annual_quality_eligibility=all(v.data["quality_pass"] for v in account.annual_views),
                    finance_account_calls=account.execution.financial_execution_count,
                    internal_execution_counts_status="UNAVAILABLE" if account.execution.internal_execution_counts is None else "RECORDED")
                if self.seal.eligibility_policy is not None:
                    policy = WholeAccountEligibility.read(self.seal.eligibility_policy)
                    row["declared_common_eligibility"] = policy.eligible(account.whole.data, (v.data for v in account.annual_views))
                if score is None:
                    row.update(state="PRUNED", reason="UNDEFINED_WHOLE_SHARPE")
                    raise optuna.TrialPruned("UNDEFINED_WHOLE_SHARPE")
                row["state"] = "COMPLETE"
                return score
            except optuna.TrialPruned:
                raise
            except BaseException as error:
                row.update(state="FAILED", error_type=type(error).__name__)
                raise

        try:
            run_ordered_study(self.study, budget=self.seal.budget, batch_size=self.seal.batch_size,
                suggest=self.bridge.suggest, evaluate=evaluate, cancellation=cancellation,
                deadline_seconds=deadline_seconds)
        finally:
            attempted = {r["trial_id"] for r in self.rows}
            for trial in self.study.get_trials(deepcopy=False):
                if trial.number not in attempted:
                    self.rows.append(dict(trial_id=trial.number, candidate_id=None, state=trial.state.name,
                        score=None, evaluation_ref=None, reason=trial.user_attrs.get("termination", "NOT_EVALUATED")))
            self.rows.sort(key=lambda r: r["trial_id"])
        return self.metadata()

    def metadata(self):
        complete = [r for r in self.rows if r["state"] == "COMPLETE" and r.get("declared_common_eligibility", True)]
        terminal_complete = sum(r["state"] == "COMPLETE" for r in self.rows)
        selected = min(complete, key=lambda r: (-r["score"], r["candidate_id"])) if complete else None
        queried = {r["candidate_id"] for r in self.rows if r["evaluation_ref"] is not None and r["candidate_id"] is not None}
        return Record.of(wire(dict(schema=SCHEMA, seal_identity=self.seal.identity,
            objective="original_raw_whole_account_sharpe", unit="annualized_ratio",
            eligibility="finite_whole_sharpe_only_not_common_annual_quality" if self.seal.eligibility_policy is None else "matched_whole_quality_annual_risk_support_v1",
            **({} if self.seal.eligibility_policy is None else dict(eligibility_policy=self.seal.eligibility_policy.data,
                eligible_complete_rows=len(complete), gate_excluded_complete_rows=terminal_complete-len(complete))),
            selected_trial=None if selected is None else selected["trial_id"],
            selected_candidate=None if selected is None else selected["candidate_id"],
            status="NO_SELECTION" if selected is None else "CONTROL_SELECTED_NOT_DEPLOYMENT",
            query_attempts=0 if self.study is None else len(self.study.trials),
            unique_executed_candidates=len(queried), complete_rows=terminal_complete,
            study_budget_complete=self.study is not None and len(self.study.trials) == self.seal.budget,
            trial_ledger=self.rows, sampler=None if self.study is None else self.bridge.metadata(self.study),
            financial_provider_qualification="EXTERNAL_PREREQUISITE_NOT_ISSUED_BY_THIS_CONSUMER",
            independent_oos=False, deployment_authorized=False)))
