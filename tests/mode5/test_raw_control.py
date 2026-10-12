"""Software fixtures for a separate raw whole-account research control."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from quantbt.mode5.continuous_runtime import ContinuousMode5MetricPolicy
from quantbt.mode5.continuous_scope import ContinuousAccountScope
from quantbt.mode5.diagnostics.identity import digest
from quantbt.optimization.config import SamplerConfig
from quantbt.optimization.wfo_study import WfoSamplerStudy
from quantbt.endpoint import _WalkForwardEndpointScorer
from tools.mode5_research.raw_control import RawControlSeal, RawWholeControl, whole_score

from test_continuous_runtime import continuous_setup


def actual_query(tmp_path, *, budget=6):
    endpoint, data, ranges, calibration = continuous_setup(tmp_path, trials=budget, preload_days=2)
    contract = calibration.continuous_contract
    scope = ContinuousAccountScope.from_contract(contract, data.index)
    wf = endpoint.config.walkforward_config
    scorer = _WalkForwardEndpointScorer(endpoint.config, "pct_equity", wf_config=wf)
    policy = scorer.mode5_metric_policy
    assert isinstance(policy, ContinuousMode5MetricPolicy)
    policy.bind_producer(scorer, endpoint.config.strategy_class)
    fold = scope.folds()[0]

    def query(params, trial_id):
        output = endpoint.config.strategy_class(data, params, fold.train_index, fold.test_index, fold)
        request = contract.request(data, params)
        with policy.evaluation(data, params, stage="mode5.search"):
            scored = scorer(data=data, output=output, index=scope.scored_index,
                fold=fold, params=params, context="mode5.search", trading_days=365)
        return request, scored["mode5_continuous_evaluation"]

    bridge = WfoSamplerStudy(SamplerConfig(name="tpe_legacy"), ranges,
        seed=wf.random_seed, budget=budget, cutoff=data.index[-1],
        strategy_identity=contract.source.data["alpha"], stage="raw_whole_control")
    seal = RawControlSeal(contract.identity, calibration.dossier.record.identity,
        digest("synthetic original scorer fixture, not alpha research authority"),
        digest("pre-outcome software control registration"), budget, wf.random_seed)
    return RawWholeControl(seal, contract, bridge), query, policy, scorer


def test_actual_control_uses_finite_whole_not_annual_or_utility(tmp_path):
    control, query, policy, scorer = actual_query(tmp_path)
    try:
        result = control.run(query).data
        assert result["query_attempts"] == 6
        assert result["study_budget_complete"] is True
        assert policy.evaluations == len(control.accounts)
        complete = [r for r in result["trial_ledger"] if r["state"] == "COMPLETE"]
        assert complete
        for row in complete:
            observed = control.accounts[row["trial_id"]]
            assert row["score"] == observed.raw_whole_sharpe
            assert row["evaluation_ref"] == observed.identity
            assert row["annual_mean_raw_sharpe"] is None
            assert row["finance_account_calls"] == 1
            assert observed.observations.equity.flags.writeable is False
        best = min(complete, key=lambda r: (-r["score"], r["candidate_id"]))
        assert result["selected_trial"] == best["trial_id"]
        assert result["independent_oos"] is False
        assert result["deployment_authorized"] is False
        with pytest.raises(RuntimeError, match="fresh control"):
            control.run(query)
    finally:
        scorer.release_prepared_state()


def test_whole_score_retains_annual_quality_failure_and_rejects_request_drift(tmp_path):
    control, query, _, scorer = actual_query(tmp_path)
    try:
        request, account = query({"period": 8}, 0)
        annual = tuple(type(v).of({**v.data, "quality_pass": False, "raw_sharpe": -999.})
                       for v in account.annual_views)
        bad_annual = replace(account, annual_views=annual)
        assert whole_score(bad_annual, request) == account.raw_whole_sharpe
        assert whole_score(account, request) == account.whole.data["raw_sharpe"]
        assert whole_score(replace(account, whole=type(account.whole).of(
            {**account.whole.data, "raw_sharpe": None})), request) is None
        with pytest.raises(ValueError, match="formal-query"):
            whole_score(account, replace(request, role="held_local_validation"))
        with pytest.raises(ValueError, match="formal-query"):
            whole_score(account, replace(request, data_identity=digest("different market")))
        with pytest.raises(ValueError, match="formal-query"):
            whole_score(SimpleNamespace(raw_whole_sharpe=10.), request)
    finally:
        scorer.release_prepared_state()


@pytest.mark.parametrize("field,value", [("budget", True), ("budget", 0), ("seed", None),
    ("batch_size", 0), ("provider_qualification_identity", "claimed")])
def test_control_seal_rejects_unbound_budget_context(field, value):
    values = dict(contract_identity=digest("contract"), dossier_identity=digest("dossier"),
        provider_qualification_identity=digest("qualification"), registration_identity=digest("registration"),
        budget=256, seed=731, batch_size=1)
    values[field] = value
    with pytest.raises(ValueError):
        RawControlSeal(**values)


def test_control_duplicate_pruning_does_not_manufacture_account_work(tmp_path):
    control, original_query, policy, scorer = actual_query(tmp_path, budget=8)
    base = control.bridge.bridge
    base.suggest = lambda trial: ({"period": 8}, {"period": 8})
    try:
        result = control.run(original_query).data
        assert result["query_attempts"] == 8
        assert result["unique_executed_candidates"] == policy.evaluations == 1
        assert len(control.accounts) == 1
        assert sum(r.get("reason") == "DUPLICATE_EFFECTIVE_PARAMS" for r in result["trial_ledger"]) == 7
    finally:
        scorer.release_prepared_state()


def test_control_failure_and_undefined_retains_observed_account(tmp_path):
    control, query, _, scorer = actual_query(tmp_path, budget=2)

    def undefined(params, trial_id):
        request, observed = query(params, trial_id)
        return request, replace(observed, whole=type(observed.whole).of(
            {**observed.whole.data, "raw_sharpe": None}))

    try:
        result = control.run(undefined).data
        assert result["status"] == "NO_SELECTION"
        assert len(control.accounts) >= 1
        assert all(r["state"] == "PRUNED" for r in result["trial_ledger"])
    finally:
        scorer.release_prepared_state()


def test_control_query_wrong_contract_fails_without_synthetic_score(tmp_path):
    control, query, _, scorer = actual_query(tmp_path)

    def wrong(params, trial_id):
        request, account = query(params, trial_id)
        return replace(request, source_identity=digest("another alpha")), account

    try:
        with pytest.raises(ValueError, match="authorized original source"):
            control.run(wrong)
        result = control.metadata().data
        assert result["query_attempts"] == 1
        assert result["trial_ledger"][0]["state"] == "FAILED"
        assert result["trial_ledger"][0]["score"] is None
        assert result["study_budget_complete"] is False
    finally:
        scorer.release_prepared_state()
