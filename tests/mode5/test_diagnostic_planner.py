"""M5-04 synthetic acceptance; no private strategy/schema enters the repo."""

from copy import deepcopy
from dataclasses import replace
import pickle

import numpy as np
import pytest

from quantbt.preparation.cache import CachePolicy, PreparedObjectCache
from tools.mode5_diagnostics import (
    AccessPolicy, AccessWitness, AnalysisKey, DiagnosticNeeds, DiagnosticReuse,
    ExecutionEvidence, ExecutionKey, MissingInputs, PanelRow, SelectionKey, compile_plan,
)
from tools.mode5_diagnostics.identity import digest


def key():
    return ExecutionKey("alpha-v1", "params-v1", "market-v1", "flat-state", "v2-close",
        "linear-v1", "one-way-0.0002", "no-funding", "account-v1", "mark-only", "warmup-v1", 731,
        "source-v1/rust-batched")


def witness(role="development"):
    return AccessWitness("manifest-v1", role, 0, 6, 7)


def policy(*, cutoff=7, role="development", purpose="diagnostic"):
    return AccessPolicy("policy-v1", (role,), ("manifest-v1",), cutoff, purpose)


def plan(*metrics):
    return compile_plan(DiagnosticNeeds(objective=metrics or ("return",)), route_id="event_orders", backend="rust")


def output(k=None, w=None, **kw):
    return ExecutionEvidence.from_arrays((k or key()).identity, w or witness(),
        dict(timestamps=np.arange(6, dtype=np.int64), equity=np.arange(6.)+100),
        source_ref="synthetic/source", backend="synthetic", **kw)


def reuse(max_bytes=1024**2, max_entries=32):
    log = []
    return DiagnosticReuse(PreparedObjectCache(CachePolicy(max_bytes=max_bytes, max_entries=max_entries)),
                           access_log=log.append), log


@pytest.mark.parametrize("field", ["costs", "funding", "instrument"])
def test_m5t_031_economic_contract_change_is_an_execution_miss(field):
    owner, _ = reuse()
    for k in (key(), replace(key(), **{field: "changed"})):
        owner.evaluate(k, witness(), policy(), plan(), lambda p: output(k))
    assert owner.executions == 2


@pytest.mark.parametrize("field", ["alpha_code", "effective_params", "market_snapshot", "source_backend"])
def test_m5t_032_source_effective_market_lineage_is_not_display_name(field):
    assert replace(key(), **{field: "changed"}).identity != key().identity


@pytest.mark.parametrize("field", ["initial_state", "clock", "account", "terminal", "warmup", "scenario_seed"])
def test_m5t_033_state_clock_warmup_terminal_seed_invalidate(field):
    value = 732 if field == "scenario_seed" else "changed"
    assert replace(key(), **{field: value}).identity != key().identity


def test_m5t_034_objective_revision_reuses_union_and_does_not_change_history():
    owner, _ = reuse()
    union = compile_plan(DiagnosticNeeds(objective=("return",), constraints=("psr",),
        axes=("hac",), batteries=("account_tail",)), route_id="event_orders", backend="rust")
    assert union.financial_retention == "compact" and not union.native_score_eligible
    assert set(union.reducers) == {"return", "psr", "hac", "account_tail"}
    out, _ = owner.evaluate(key(), witness(), policy(), union, lambda p: output())
    a = AnalysisKey(key().identity, "whole", "daily-v1", "ref-v1")
    raw, _ = owner.analyze(a, out, policy(), lambda e: {"pnl": float(e.arrays()["equity"][-1]-100.)})
    history = [("trial-1", raw["pnl"])]
    s1 = SelectionKey((a.identity,), "universe", "weight1", "fixed-plan", policy().identity)
    s2 = replace(s1, objective_selector_preferences="weight2")
    assert s1.identity != s2.identity
    owner.require_selection(s2, (a,), (out,), policy())
    assert raw["pnl"] == 5 and history == [("trial-1", 5.)]
    assert owner.evaluate(key(), witness(), policy(), union, lambda p: pytest.fail("rerun"))[1] == "REUSED"
    assert owner.executions == 1


def test_m5t_035_reference_revision_reduces_again_without_simulation():
    owner, _ = reuse()
    out, _ = owner.evaluate(key(), witness(), policy(), plan(), lambda p: output())
    a = AnalysisKey(key().identity, "whole", "daily-v1", "ref-v1")
    assert owner.analyze(a, out, policy(), lambda e: {"value": 5}) == ({"value": 5}, "REDUCED")
    assert owner.analyze(a, out, policy(), lambda e: pytest.fail("reduction"))[1] == "REUSED"
    assert owner.analyze(replace(a, normalization_reference="ref-v2"), out, policy(),
                         lambda e: {"value": 2}) == ({"value": 2}, "REDUCED")
    assert owner.executions == 1


def test_m5t_036_cached_holdout_cannot_be_relabelled_or_selected():
    owner, log = reuse()
    holdout = witness("holdout")
    p = policy(role="holdout", purpose="independent_validation")
    out, _ = owner.evaluate(key(), holdout, p, plan(), lambda _: output(w=holdout))
    with pytest.raises(PermissionError):
        owner.evaluate(key(), holdout, policy(), plan(), lambda _: pytest.fail("executed"))
    with pytest.raises(PermissionError):
        owner.evaluate(key(), witness(), policy(), plan(), lambda _: pytest.fail("executed"))
    with pytest.raises(PermissionError):
        owner.analyze(AnalysisKey(key().identity, "whole", "metric", "ref"), out, policy(), lambda _: {})
    assert owner.executions == 1 and any(r["decision"] == "DENIED" for r in log)


def test_m5t_036_earlier_cutoff_denies_an_already_cached_mature_record():
    owner, _ = reuse()
    owner.evaluate(key(), witness(), policy(), plan(), lambda _: output())
    with pytest.raises(PermissionError, match="immature"):
        owner.evaluate(key(), witness(), policy(cutoff=6), plan(), lambda _: pytest.fail("executed"))


def test_m5t_038_runtime_failure_never_cached_as_bad_economic_sample():
    owner, _ = reuse()
    def fail(_):
        raise RuntimeError("synthetic failed runtime")
    with pytest.raises(RuntimeError):
        owner.evaluate(key(), witness(), policy(), plan(), fail)
    assert owner.cache.diagnostics["entry_count"] == 0
    out, _ = owner.evaluate(key(), witness(), policy(), plan(), lambda _: output(status="VALID_ADVERSE"))
    assert out.status == "VALID_ADVERSE" and owner.executions == 2


def test_m5t_039_scalar_retention_explicitly_blocks_richer_queries():
    owner, _ = reuse()
    scalar = ExecutionEvidence.from_arrays(key().identity, witness(), {"score": np.array([1.])},
        source_ref="scalar", backend="synthetic")
    owner.evaluate(key(), witness(), policy(), plan("score"), lambda _: scalar)
    with pytest.raises(MissingInputs, match="REPLAY_REQUIRED"):
        owner.evaluate(key(), witness(), policy(), plan("psr", "campaign_tail"),
                       lambda _: pytest.fail("implicit replay"))
    assert owner.executions == 1


@pytest.mark.parametrize("kind", ["copy", "pickle"])
def test_retained_evidence_survives_copy_pickle_without_writable_hash_staleness(kind):
    out = deepcopy(output()) if kind == "copy" else pickle.loads(pickle.dumps(output()))
    with pytest.raises(ValueError):
        out.arrays()["equity"].setflags(write=True)
    assert out.content_id == output().content_id


def test_budget_bypass_clear_and_analysis_caller_mutation_do_not_change_evidence():
    owner, _ = reuse(max_bytes=0)
    _, state = owner.evaluate(key(), witness(), policy(), plan(), lambda _: output())
    assert state == "EXECUTED_BUDGET_BYPASS" and owner.cache.diagnostics["resident_bytes"] == 0
    owner, _ = reuse()
    out, _ = owner.evaluate(key(), witness(), policy(), plan(), lambda _: output())
    a = AnalysisKey(key().identity, "whole", "metric", "ref")
    value, _ = owner.analyze(a, out, policy(), lambda _: {"nested": [1]})
    value["nested"][0] = 100
    assert owner.analyze(a, out, policy(), lambda _: {})[0] == {"nested": [1]}
    assert owner.cache.clear()["released_entries"] == 2


def test_malformed_required_streams_and_unknown_metrics_fail_closed():
    with pytest.raises(ValueError, match="unknown"):
        plan("custom_unknown")
    bad = ExecutionEvidence.from_arrays(key().identity, witness(),
        {"timestamps": np.arange(6, dtype=np.int64), "equity": np.arange(5.)},
        source_ref="malformed", backend="synthetic")
    with pytest.raises(ValueError, match="cardinality"):
        bad.require(plan())


def test_typed_panel_does_not_conflate_no_trade_adverse_and_runtime_failure():
    row = PanelRow("t1", "raw", "effective", "branch", key().identity, "seed731", "env", witness(),
                   -1, 7, "MET-v1", 6, "VALID_NO_TRADE", 0., "source", "python")
    assert row.record()["witness"]["ready_ns"] == 7
    assert replace(row, status="VALID_ADVERSE", value=-5.).value == -5.
    assert replace(row, status="INVALID_RUNTIME", value=None).value is None
    with pytest.raises(ValueError, match="sentinel"):
        replace(row, status="INVALID_RUNTIME", value=-1e9)
    with pytest.raises(ValueError):
        replace(row, support=-1)


def test_audit_only_never_runs_missing_financial_evidence():
    owner, _ = reuse()
    with pytest.raises(ValueError, match="AUDIT_ONLY"):
        owner.evaluate(key(), witness(), policy(), plan(), lambda _: pytest.fail("executed"), allow_execution=False)
    assert owner.executions == 0


def test_m5t_037_same_effective_params_can_have_distinct_raw_trial_identities():
    assert digest({"active": 2, "inactive": 3}) != digest({"active": 2, "inactive": 5})
    assert digest({"active": 2}) == digest({"active": 2})
