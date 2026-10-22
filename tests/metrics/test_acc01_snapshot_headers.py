"""ACC-01 F11: header edits cannot reuse an immutable observation identity."""

from copy import copy, deepcopy
from dataclasses import replace
import pickle

import numpy as np
import pytest

from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting.account import reduce_account
from quantbt.metrics.reporting.cache import ReportingCache
from quantbt.metrics.reporting.drawdown import scan_drawdown
from quantbt.metrics.reporting.execution import ExecutionObservations, reduce_execution
from quantbt.metrics.reporting.inputs import AccountObservations, ReturnObservations


def contract():
    return ReportingContractV1(scope="full", unit="account_period", currency="USD",
        baseline_equity=100., baseline_time_ns=0, scope_end_ns=10,
        sampling="observed_bar", annual_periods=1., equity_clock="bar_close")


def account():
    coverage = ReportingCoverageV1(result_identity="acc01-headers", producer="recorded fixture",
        profile="completed", ledger="unsupported", retained_rows=0, dropped_rows=0,
        reason="account marks are not outcomes")
    returns = ReturnObservations(values=[0., .1], end_times_ns=[0, 10],
        partial_mask=[False, False], sampling="observed_bar", witness="two complete marks")
    return AccountObservations(times_ns=[0, 10], equity=[100., 110.], coverage=coverage, returns=returns)


def mutate(array, mutation):
    if mutation == "dtype":
        array.dtype = np.uint8 if array.dtype == np.bool_ else np.uint64
    elif mutation == "shape":
        array.shape = (*array.shape, 1)
    else:
        array.strides = (0,) * array.ndim


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("field", ["equity", "times_ns", "returns.values", "returns.end_times_ns", "returns.partial_mask"])
@pytest.mark.parametrize("mutation", ["dtype", "shape", "strides"])
def test_f11_account_cache_and_fresh_reducers_reject_changed_headers(backend, field, mutation):
    obs, policy = account(), contract()
    with ReportingCache() as cache:
        cached = cache.reduce("account", obs, policy, backend=backend)
        assert cached.metric("account.total_return").value == pytest.approx(.1)
        signature = obs.identity
        target = obs
        for name in field.split("."):
            target = getattr(target, name)
        mutate(target, mutation)
        assert obs.identity == signature
        for operation in (
            lambda: cache.reduce("account", obs, policy, backend=backend),
            lambda: reduce_account(obs, policy, backend=backend),
            lambda: scan_drawdown(obs, policy, backend=backend),
            lambda: obs.with_derived_returns(policy, partial_mask=[False, False], witness="recorded"),
            lambda: copy(obs), lambda: deepcopy(obs), lambda: pickle.dumps(obs),
        ):
            with pytest.raises(ValueError, match="array header changed"):
                operation()
        assert cache.hits == 0 and cache.misses == 1


@pytest.mark.parametrize("field", ["times", "fees"])
@pytest.mark.parametrize("mutation", ["dtype", "shape", "strides"])
def test_f11_execution_headers_checked_before_cache_and_reduction(field, mutation):
    obs = account()
    execution = ExecutionObservations(coverage=obs.coverage, currency="USD", scope_start_ns=0,
        scope_end_ns=10, witness="recorded fees", times_ns=[0, 10], paths=(("fees", [2., 3.]),))
    with ReportingCache() as cache:
        cached = cache.reduce("execution", execution, contract())
        assert cached.metric("execution.sum_fees").value == 5
        mutate(execution.times_ns if field == "times" else execution.paths[0][1], mutation)
        with pytest.raises(ValueError, match="array header changed"):
            cache.reduce("execution", execution, contract())
        with pytest.raises(ValueError, match="array header changed"):
            reduce_execution(execution, contract())


@pytest.mark.parametrize("field", ["integers", "numbers"])
@pytest.mark.parametrize("mutation", ["dtype", "shape", "strides"])
def test_f11_cached_episode_headers_checked_before_read_or_serialization(field, mutation):
    obs = replace(account(), equity=[100., 80.], returns=None)
    with ReportingCache() as cache:
        report = cache.reduce("account", obs, contract(), retain_episodes=True)
        assert report.metric("drawdown.max_depth").value == pytest.approx(.2)
        mutate(getattr(report.episodes, field), mutation)
        for operation in (
            report.to_metadata, report.episodes.to_rows,
            lambda: cache.reduce("account", obs, contract(), retain_episodes=True),
            lambda: deepcopy(report), lambda: pickle.dumps(report),
        ):
            with pytest.raises(ValueError, match="array header changed"):
                operation()


CLONES = [pytest.param(copy, id="copy"), pytest.param(deepcopy, id="deepcopy")]
CLONES += [pytest.param(lambda value, protocol=protocol: pickle.loads(pickle.dumps(value, protocol=protocol)),
                        id=f"pickle-{protocol}") for protocol in range(pickle.HIGHEST_PROTOCOL + 1)]


def assert_readonly_ancestry(array):
    while isinstance(array, np.ndarray):
        with pytest.raises(ValueError):
            array.setflags(write=True)
        array = array.base
    assert isinstance(array, bytes)


@pytest.mark.parametrize("clone", CLONES)
def test_f11_roundtrips_keep_storage_readonly_and_private_headers(clone):
    original = account()
    restored = clone(original)
    assert original.identity == restored.identity
    for left, right in zip(
        (original.times_ns, original.equity, original.returns.values,
         original.returns.end_times_ns, original.returns.partial_mask),
        (restored.times_ns, restored.equity, restored.returns.values,
         restored.returns.end_times_ns, restored.returns.partial_mask),
    ):
        assert left is not right
        assert_readonly_ancestry(right)
        np.testing.assert_array_equal(left, right)
    with ReportingCache() as cache:
        cached = cache.reduce("account", original, contract())
        assert cache.reduce("account", restored, contract()) is cached
        restored.equity.dtype = np.int64
        with pytest.raises(ValueError, match="array header changed"):
            cache.reduce("account", restored, contract())
        assert cache.reduce("account", original, contract()) is cached
        assert cached.metric("account.total_return").value == pytest.approx(.1)


def test_f11_canonical_storage_has_no_exposed_mutable_base_header():
    owner = np.frombuffer(np.array([100., 110.]).tobytes(), np.float64)
    obs = replace(account(), equity=owner)
    assert isinstance(obs.equity.base, bytes)
    owner.dtype = np.int64
    owner.shape = (2, 1)
    obs.validate_snapshot()
    np.testing.assert_array_equal(obs.equity, [100., 110.])
    assert reduce_account(obs, contract()).metric("account.total_return").value == pytest.approx(.1)


def test_f11_historical_state_does_not_trust_serialized_layout_or_identity():
    original = account()
    state = dict(original.__dict__)
    state["equity"] = np.array([100., 80.])
    state["returns"] = None
    state["_snapshot_layout"] = ((), ())
    restored = object.__new__(AccountObservations)
    restored.__setstate__(state)
    assert restored.identity != original.identity
    assert_readonly_ancestry(restored.equity)
    assert reduce_account(restored, contract()).metric("account.total_return").value == pytest.approx(-.2)
    restored.equity.dtype = np.int64
    with pytest.raises(ValueError, match="array header changed"):
        restored.validate_snapshot()


@pytest.mark.parametrize("size", [2, 100_000])
def test_f11_warm_cache_does_not_rehash_or_scan_observations(monkeypatch, size):
    from quantbt.metrics.reporting import cache as cache_module, inputs

    times = np.arange(size, dtype=np.int64)
    obs = AccountObservations(times_ns=times, equity=np.full(size, 100.), coverage=account().coverage)
    policy = replace(contract(), scope_end_ns=size - 1)
    with ReportingCache() as cache:
        cached = cache.reduce("account", obs, policy)

        def forbidden(*args, **kwargs):
            raise AssertionError("cache hit scanned or hashed observation content")

        with monkeypatch.context() as patch:
            patch.setattr(inputs, "identity", forbidden)
            patch.setattr(cache_module, "reduce_account", forbidden)
            patch.setattr(np, "isfinite", forbidden)
            for _ in range(3):
                assert cache.reduce("account", obs, policy) is cached
        assert cache.hits == 3 and cache.misses == 1
