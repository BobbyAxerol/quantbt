"""Pct activity admission and identity only; no financial/native execution."""

from hashlib import sha256
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from quantbt.backends import native_prepared_evaluation as prepared
from quantbt.backends import native_wfo_public as public
from quantbt.core.schema import AccountConfig, ExecutionConfig
from quantbt.preparation.native_execution import NativeExecutionPreparationCache, NativePreparedRequest


ACTIVITY = "accepted_qty_position_states_v1"


class _Runtime:
    def __init__(self, **kwargs):
        self.binds = []

    def bind(self, request, workload, **kwargs):
        self.binds.append((request, workload, kwargs))
        return object()


class _Native:
    FullPreparedMarketCore = NativeExecutionTemplateCore = NativeExecutionRequestCore = object
    NativePreparedEvaluationRuntimeCore = _Runtime
    NativeTargetExecutionRequestCore = SimpleNamespace(
        metric_zero_base_policies=lambda: ["native_skip_zero_base_v1", "legacy_zero_base_v1"])
    QMS_PREPARED_METRIC_SUPPORT_V1 = "same-pass-ddof1-daily-first-mark-v1"
    __version__ = "0.4.3"

    def __init__(self, activity):
        self.activity = activity
        self.activity_reads = 0

    def __getattr__(self, name):
        if name == "PCT_EQUITY_ACCEPTED_QTY_ACTIVITY_V1":
            self.activity_reads += 1
            return self.activity
        raise AttributeError(name)


def _runtime(activity):
    native = _Native(activity)
    cache = NativeExecutionPreparationCache(module=native)
    runtime = prepared.NativePreparedEvaluationRuntimeV1(cache)
    request = NativePreparedRequest(core=SimpleNamespace(bars=4), template=None,
        signature="unchanged-request", workload="direct_target_v1", request_bytes=32)
    return runtime, request, native


@pytest.mark.parametrize("activity", (None, True, "processed_signal_states_v1", "accepted_qty_position_states_v0"))
def test_old_same_version_pct_cannot_reach_native_bind(activity):
    runtime, request, native = _runtime(activity)
    assert native.__version__ == "0.4.3"
    with pytest.raises(NotImplementedError, match="PCT_EQUITY_ACTIVITY_SUPPORT_MISSING"):
        runtime.bind_request(request, workload="pct_equity_transition")
    assert runtime._native_runtime.binds == []
    assert native.activity_reads == 1


def _old_binding_identity(request, workload):
    return dict(request_signature=request.signature, workload=workload, candidate_id=0,
        fold_id=0, scenario_id=0, cutoff_bar=None, evaluation_start=0, evaluation_end=4,
        account_policy="fresh_account_per_evaluation",
        metric_contract=prepared.NativeEvaluationMetricContractV1().fingerprint)


def _digest(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def test_pct_binding_invalidates_old_identity_without_changing_unit_identity():
    runtime, request, native = _runtime(ACTIVITY)
    unit = runtime.bind_request(request, workload="target_units")
    assert unit.binding_fingerprint == _digest(_old_binding_identity(request, "target_units"))
    pct = runtime.bind_request(request, workload="pct_equity_transition")
    old = _old_binding_identity(request, "pct_equity_transition")
    assert pct.binding_fingerprint != _digest(old)
    assert pct.binding_fingerprint == _digest(dict(old, engine_semantic_build=ACTIVITY))
    assert pct.metric_contract == unit.metric_contract
    assert native.activity_reads == 1
    assert len(runtime._native_runtime.binds) == 2


def test_non_pct_runtime_does_not_require_new_activity_marker():
    runtime, request, native = _runtime(None)
    unit = runtime.bind_request(request, workload="target_units")
    assert unit.binding_fingerprint == _digest(_old_binding_identity(request, "target_units"))
    assert len(runtime._native_runtime.binds) == native.activity_reads == 1


def _scorer(target, meta=False):
    config = SimpleNamespace(account=AccountConfig(initial_capital=20_000, leverage=1),
        execution=ExecutionConfig(), fee=0.0008, v2_fee_rate=0.0004, slippage=0.,
        target_runtime="rust", symbols=["SYNTHETIC"], use_funding=False, funding_rate=0.)
    wf = SimpleNamespace(metadata={"native_prepared_wfo": "require"}, scoring_trading_days=365)
    return public.NativePreparedPublicWfoScorerV1(config=config, target_mode=target,
        wf_config=wf, meta_metric_support=meta)


class _MarketReached(Exception):
    pass


@pytest.mark.parametrize("target", ("pct_equity", "%_equity"))
@pytest.mark.parametrize("meta", (False, True))
@pytest.mark.parametrize("activity", (None, ACTIVITY))
def test_pct_public_admission_checks_activity_even_without_meta(monkeypatch, target, meta, activity):
    native = _Native(activity)
    calls = []
    def market(**kwargs):
        calls.append(kwargs)
        raise _MarketReached
    cache = SimpleNamespace(_native=lambda: native, prepare_market=market)
    monkeypatch.setattr(public, "NativeExecutionPreparationCache", lambda policy: cache)
    index = pd.date_range("2020-01-01", periods=4, freq="1D", tz="UTC")
    context = SimpleNamespace(datetime_index=index,
        data=pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=1.), index=index))
    scorer = _scorer(target, meta)
    if activity is None:
        with pytest.raises(public.NativePreparedPublicWfoUnsupported, match="PCT_EQUITY_ACTIVITY_SUPPORT_MISSING"):
            scorer.bind_walkforward_context(context)
        assert calls == []
    else:
        with pytest.raises(_MarketReached):
            scorer.bind_walkforward_context(context)
        assert len(calls) == 1
    assert native.activity_reads == 1


@pytest.mark.parametrize("target", ("pct_equity", "%_equity", "unit"))
def test_score_reuse_semantic_build_changes_for_pct_only(target):
    scorer = _scorer(target)
    scorer._resolved = "native_prepared"
    scorer._state = SimpleNamespace(template=SimpleNamespace(signature="template",
        market=SimpleNamespace(signature="market")),
        metric_contract=prepared.NativeEvaluationMetricContractV1())
    contract = scorer.wfo_execution_reuse_contract()
    expected = "native_prepared_public_wfo_legacy_zero_base_v1"
    if target in {"pct_equity", "%_equity"}:
        expected = "native_prepared_public_wfo_legacy_zero_base_pct_accepted_qty_v1"
    assert contract["engine_semantic_build"] == expected
    assert contract["numeric_contract"] == "native_prepared_scalar_columns_v1"
    assert contract["cross_run_reuse"] is False
    assert contract["metric_identity"] == scorer._state.metric_contract.fingerprint
