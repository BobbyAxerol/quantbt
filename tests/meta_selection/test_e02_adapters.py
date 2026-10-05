"""Actual legacy delegates, typed evidence and run-owned lifecycle conformance."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint, walkforward_support_matrix
from quantbt.core.runtime_governance import RuntimeCanceledError
from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.domains import (
    DomainEvaluationAdapter, EvaluationEvidence, EvaluationStage, InputKind,
)
from quantbt.optimization.meta_selection.domains.scalar import ScalarDomainAdapter
from quantbt.optimization.meta_selection.domains.registry import adapter_for
from quantbt.optimization.meta_selection.observer import ResultMetricAdapter, canonical_metric_contract, economics_identity
from tests.meta_selection.test_e02_contracts import request, compatibility


def scalar_adapter():
    from examples.wfo_meta_scalar import make_scalar_endpoint
    endpoint = make_scalar_endpoint()
    scorer = SimpleNamespace(config=endpoint.config, symbols=None)
    return ScalarDomainAdapter(SimpleNamespace(engine=SimpleNamespace(
        config=endpoint.config.walkforward_config, scorer=scorer)))


def test_e02_t01_adapter_delegates_once_and_observes_original_result_without_replay():
    binding = request()
    endpoint = QuantBTEndpoint.signal_notional(initial_capital=20_000., alloc_per_trade=1_000.,
        fee_rate=.0005, use_funding=False)
    close = np.array([100., 110., 104.])
    data = pd.DataFrame(dict(open=close, high=close+1, low=close-1, close=close), index=binding.index)
    adapter = scalar_adapter()
    calls = []

    def execute(b):
        calls.append(b.payload)
        return endpoint.backtest(data=data, signal=b.payload)

    result = adapter.evaluate(binding, execute)
    evidence = adapter.observe(binding, result,
        metric_adapter=ResultMetricAdapter(canonical_metric_contract()),
        economics_id=economics_identity(endpoint.config))
    assert isinstance(adapter, DomainEvaluationAdapter)
    assert isinstance(evidence, EvaluationEvidence) and evidence.original_result is result
    assert len(calls) == 1 and calls[0] is binding.payload
    assert evidence.observation.verification == "original_result"
    assert adapter.stats["financial_delegate_calls"] == adapter.stats["original_observations"] == 1


@pytest.mark.parametrize("mutation", ["domain", "kind", "matrix", "index", "result_signature"])
def test_e02_t01_wrong_domain_input_and_result_cannot_be_guessed(mutation):
    adapter, binding = scalar_adapter(), request()
    if mutation == "result_signature":
        from quantbt.optimization.meta_selection.records import MetricObservation, OutcomeStatus
        observation = MetricObservation(OutcomeStatus.NO_VARIANCE, 0., 0, 2, 0.,
            "metric", "economics", binding.index[0], binding.index[-1], binding.index[-1],
            20000., 20000., "original", "wrong-signature", "original_result")
        with pytest.raises(MetaRecordError):
            EvaluationEvidence(binding, observation, object())
        return
    changes = {"domain": dict(domain="portfolio"), "kind": dict(input_kind=InputKind.POSITION_MATRIX),
        "matrix": dict(payload=binding.payload.to_frame("BTC")),
        "index": dict(payload=binding.payload.set_axis(binding.index+pd.Timedelta(days=1)))}
    with pytest.raises(MetaRecordError, match="META_DOMAIN_INPUT_MISMATCH"):
        adapter.evaluate(replace(binding, **changes[mutation]), lambda b: pytest.fail("financial call happened"))


def test_e02_t04_reset_cancel_clear_do_not_mutate_payload_or_external_owner():
    adapter, binding = scalar_adapter(), request()
    previous = binding.payload.copy()
    owner = adapter.runtime
    adapter.cancel()
    with pytest.raises(RuntimeCanceledError):
        adapter.evaluate(binding, lambda b: pytest.fail("canceled call happened"))
    adapter.reset()
    assert adapter.evaluate(binding, lambda b: b.payload) is binding.payload
    adapter.clear()
    adapter.clear()
    assert adapter.runtime is None and owner is not None
    with pytest.raises(MetaRecordError, match="CLOSED"):
        adapter.evaluate(binding, lambda b: None)
    pd.testing.assert_series_equal(binding.payload, previous)


def test_e02_t04_failure_and_nested_execution_leave_no_busy_adapter():
    adapter, binding = scalar_adapter(), request()
    with pytest.raises(MetaRecordError, match="EVALUATOR"):
        adapter.evaluate(binding, lambda b: adapter.evaluate(binding, lambda x: None))
    assert adapter.executing is False
    adapter.clear()


def test_e02_t05_existing_discovery_exposes_domain_method_axes_without_new_routes():
    matrix = walkforward_support_matrix(False)
    assert [r["target_mode"] for r in matrix] == ["signal_notional", "notional", "unit", "pct_equity",
        "dca_ladder", "portfolio", "basket", "arbitrage", "nautilus_validation"]
    for row in matrix:
        assert row["meta_route_activated"] == (row["target_mode"] in {"signal_notional", "pct_equity", "notional", "unit", "dca_ladder"})
        if row["meta_route_activated"]:
            assert row["meta_optimization_modes"] == ("mode_4_is_only_robust",)
            assert row["meta_optimization_schedules"] == ("per_fold_causal",)
        else:
            assert row["meta_optimization_modes"] == ()


def test_e02_t05_unknown_scorer_cannot_enter_scalar_adapter_by_series_shape():
    runtime = SimpleNamespace(engine=SimpleNamespace(scorer=SimpleNamespace(meta_route_id="not-certified")))
    with pytest.raises(MetaRecordError, match="scorer"):
        adapter_for(runtime)


@pytest.mark.parametrize("field,value", [("economics_id", "different-fees"), ("metric_id", "different-reducer")])
def test_e02_t03_future_adapter_cannot_borrow_incompatible_legacy_family(field, value):
    from quantbt.optimization.meta_selection.records import CompatibilityFamily
    contract = compatibility()
    family = CompatibilityFamily(*["x"]*6, contract.metric_id, contract.economics_id, *["x"]*4)
    changed = contract.bind_family(family)
    assert changed.family_id != family.family_id
    with pytest.raises(MetaRecordError, match="FAMILY"):
        replace(contract, **{field:value}).bind_family(family)


def test_e02_t06_protocol_payload_reference_has_zero_market_array_copy_and_no_ffi():
    adapter, binding = scalar_adapter(), request()
    for _ in range(20):
        assert adapter.evaluate(binding, lambda b: b.payload) is binding.payload
    assert adapter.metadata["financial_delegate_calls"] == 20
    assert adapter.metadata["adapter_market_array_copies"] == 0
    assert adapter.metadata["adapter_pyo3_calls"] == 0
    assert adapter.metadata["adapter_owned_market_bytes"] == 0
    assert adapter.metadata["financial_replays"] == 0
