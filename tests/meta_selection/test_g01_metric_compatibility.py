"""G01 uses the existing metric estimator; only sampling compatibility changes."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt.backends.native_prepared_evaluation import (
    NativeEvaluationMetricContractV1, NativePreparedEvaluationRuntimeV1,
    NativePreparedWorkloadV1,
)
from quantbt.metrics.performance import _array_returns_for_stats, _array_sharpe
from quantbt.preparation.native_execution import NativeExecutionPreparationCache, CachePolicy

LEGACY = "legacy_zero_base_v1"
DEFAULT = "native_skip_zero_base_v1"


def requests():
    index = pd.date_range("2020-01-01", periods=7, freq="1D", tz="UTC")
    prices = np.array([100., 100., 120., 1., 1., 1., 1.]).reshape(-1, 1)
    cache = NativeExecutionPreparationCache(CachePolicy(max_entries=32, max_bytes=100_000))
    market = cache.prepare_market(timestamps_ns=index.asi8, opens=prices, highs=prices,
        lows=prices, closes=prices, volumes=np.ones_like(prices), funding=np.zeros_like(prices),
        funding_mask=np.zeros(len(index), dtype=bool), symbols=["A"])
    template = cache.prepare_template(market, contract_sizes=np.ones(1), leverages=np.array([3.]),
        fee_rates=np.zeros(1), initial_capital=100., maintenance_ratio=.005,
        slippage_rate=0., use_funding=False)
    targets = np.full_like(prices, 2.)
    return index, cache, template, targets


def test_g01_policy_changes_metric_fingerprint_but_default_is_stable():
    native = NativeEvaluationMetricContractV1()
    legacy = NativeEvaluationMetricContractV1(zero_base_return_policy=LEGACY)
    assert native.fingerprint != legacy.fingerprint
    with pytest.raises(NotImplementedError):
        NativeEvaluationMetricContractV1(zero_base_return_policy="invented")


@pytest.mark.parametrize("profile", [0, 1, 2])
def test_g01_liquidation_score_compact_audit_and_prepared_parity(profile):
    index, cache, template, targets = requests()
    before = cache.direct_target_request(template, targets=targets, output_profile=profile)
    repaired = cache.direct_target_request(template, targets=targets, output_profile=profile,
        metric_zero_base_policy=LEGACY)
    repeated = cache.direct_target_request(template, targets=targets, output_profile=profile,
        metric_zero_base_policy=LEGACY)
    assert repaired is repeated and repaired.signature != before.signature
    assert repaired.core.metric_zero_base_policy == LEGACY
    a, b = dict(before.core.execute()), dict(repaired.core.execute())
    assert a["liquidated"] and b["liquidated"]
    for key in ("final_equity", "total_fee", "total_funding", "total_turnover", "fill_count", "rejected_count"):
        assert a[key] == b[key]
    compact = cache.direct_target_request(template, targets=targets, output_profile=1,
        metric_zero_base_policy=LEGACY)
    path = dict(compact.core.execute())
    equity = np.asarray(path["equity"], dtype=float).reshape(-1)
    returns = _array_returns_for_stats(index, equity, np.zeros(len(index)))
    expected = _array_sharpe(returns, 365.)
    assert int(b["native_metric_sample_count"]) == len(index)-1
    assert int(a["native_metric_sample_count"]) < int(b["native_metric_sample_count"])
    assert b["native_metric_sharpe"] == pytest.approx(expected, abs=1e-12)
    assert b["native_metric_zero_base_return_policy"] == LEGACY
    if profile:
        np.testing.assert_array_equal(a["equity"], b["equity"])
        np.testing.assert_array_equal(a["positions"], b["positions"])
    runtime = NativePreparedEvaluationRuntimeV1(cache, workers=1)
    try:
        with pytest.raises(ValueError, match="zero-base policies differ"):
            runtime.bind_request(repaired, workload=NativePreparedWorkloadV1.TARGET_UNITS, candidate_id=0)
        binding = runtime.bind_request(repaired, workload=NativePreparedWorkloadV1.TARGET_UNITS,
            candidate_id=0, metric_contract=NativeEvaluationMetricContractV1(zero_base_return_policy=LEGACY))
        result = runtime.evaluate_score_columns([binding])
        assert float(result.sharpe[0]) == pytest.approx(expected, abs=1e-12)
    finally:
        runtime.close()


def test_g01_guard_rejects_an_unsupported_policy_before_execution():
    _, cache, template, targets = requests()
    with pytest.raises(NotImplementedError, match="zero-base"):
        cache.direct_target_request(template, targets=targets, metric_zero_base_policy="invented")


def test_g01_old_extension_cannot_relabel_a_cached_request(monkeypatch):
    _, cache, template, targets = requests()
    original = cache._native()
    monkeypatch.setattr(cache, "_native", lambda: SimpleNamespace(NativeTargetExecutionRequestCore=object))
    with pytest.raises(NotImplementedError, match="lacks legacy"):
        cache.direct_target_request(template, targets=targets, metric_zero_base_policy=LEGACY)
    monkeypatch.setattr(cache, "_native", lambda: original)


def test_g01_exact_source_amendment_rejects_unreviewed_bytes():
    from tools.qms_g01_source_guard import ALLOW, ROOT, verify, without_g01
    assert not verify()["scientific_estimator_changed"]
    for name in ALLOW:
        with pytest.raises(AssertionError, match="unreviewed"):
            without_g01((ROOT/name).read_bytes()+b"\n// hidden drift\n", name)
