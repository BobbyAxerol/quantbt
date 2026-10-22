"""Copy/serialization must not turn immutable observations into stale cache keys."""

from copy import copy, deepcopy
from dataclasses import replace
import pickle

import numpy as np
import pytest

from quantbt import ReportingCache, ReportingCoverageV1, ReportingRequest
from quantbt.metrics.reporting.execution import ExecutionObservations
from quantbt.metrics.reporting.inputs import AccountObservations, ReturnObservations

from .test_account_reducers import policy, reduce_account


CLONES = [pytest.param(copy, id="copy"), pytest.param(deepcopy, id="deepcopy")]
CLONES += [pytest.param(lambda value, p=p: pickle.loads(pickle.dumps(value, protocol=p)),
                        id=f"pickle-{p}") for p in range(pickle.HIGHEST_PROTOCOL + 1)]


def snapshot():
    coverage = ReportingCoverageV1(result_identity="copy-review", producer="recorded synthetic marks",
        profile="completed", ledger="unsupported", retained_rows=0, dropped_rows=0,
        reason="account marks do not certify outcome attribution")
    returns = ReturnObservations(values=np.array([0., -.1, 110/90-1]),
        end_times_ns=np.array([0, 10, 20]), partial_mask=np.array([False, False, False]),
        sampling="observed_bar", witness="three complete synthetic periods")
    return AccountObservations(times_ns=np.array([0, 10, 20]), equity=np.array([100., 90., 110.]),
        coverage=coverage, returns=returns)


def arrays(observations):
    return (observations.times_ns, observations.equity, observations.returns.values,
            observations.returns.end_times_ns, observations.returns.partial_mask)


@pytest.mark.parametrize("clone", CLONES)
def test_account_return_roundtrip_is_immutable_and_exact(clone):
    original = snapshot()
    restored = clone(original)
    assert restored.identity == original.identity
    for left, right in zip(arrays(original), arrays(restored)):
        np.testing.assert_array_equal(left, right)
        assert left is not right
        with pytest.raises(ValueError):
            right.setflags(write=True)
        with pytest.raises(ValueError):
            right[0] = 0
    contract = replace(policy([0, 10, 20]), sampling="observed_bar")
    assert reduce_account(original, contract, retain_episodes=True).to_metadata() == \
        reduce_account(restored, contract, retain_episodes=True).to_metadata()


@pytest.mark.parametrize("clone", CLONES)
def test_roundtrip_cannot_reproduce_stale_cached_return(clone):
    original = snapshot()
    contract = replace(policy([0, 10, 20]), sampling="observed_bar")
    with ReportingCache() as cache:
        cached = cache.reduce("account", original, contract)
        restored = clone(original)
        with pytest.raises(ValueError):
            restored.equity[-1] = 80.
        assert cache.reduce("account", restored, contract) is cached
        changed = replace(restored, equity=[100., 90., 80.], returns=None)
        assert changed.identity != restored.identity
        corrected = cache.reduce("account", changed, contract)
        assert cached.metric("account.total_return").value == pytest.approx(.1)
        assert corrected.metric("account.total_return").value == pytest.approx(-.2)
        assert corrected.to_metadata() == reduce_account(changed, contract).to_metadata()
        assert cache.hits == 1 and cache.misses == 2


@pytest.mark.parametrize("clone", CLONES)
def test_execution_paths_roundtrip_and_cache(clone):
    account = snapshot()
    execution = ExecutionObservations(coverage=account.coverage, currency="USDT", scope_start_ns=0,
        scope_end_ns=20, witness="recorded complete fee path", times_ns=account.times_ns,
        paths=(("fees", np.array([1., 2., 3.])),))
    restored = clone(execution)
    assert restored.identity == execution.identity
    assert restored.times_ns is not execution.times_ns
    with pytest.raises(ValueError):
        restored.times_ns.setflags(write=True)
    with pytest.raises(ValueError):
        restored.paths[0][1][-1] = 100.
    contract = policy([0, 10, 20])
    with ReportingCache() as cache:
        report = cache.reduce("execution", execution, contract)
        assert cache.reduce("execution", restored, contract) is report
        assert report.metric("execution.sum_fees").value == 6.


@pytest.mark.parametrize("clone", CLONES)
def test_result_episode_roundtrip_preserves_readonly_headers(clone):
    contract = replace(policy([0, 10, 20]), sampling="observed_bar")
    report = reduce_account(snapshot(), contract, retain_episodes=True)
    restored = clone(report)
    assert restored.to_metadata() == report.to_metadata()
    for name in ("integers", "numbers"):
        original, copied = getattr(report.episodes, name), getattr(restored.episodes, name)
        assert original is not copied
        with pytest.raises(ValueError):
            copied.setflags(write=True)
        with pytest.raises(ValueError):
            copied[0, 0] = 0


@pytest.mark.parametrize("clone", CLONES)
def test_nested_request_snapshot_and_cached_result_roundtrip(clone):
    obs = snapshot()
    contract = replace(policy([0, 10, 20]), sampling="observed_bar")
    execution = ExecutionObservations(coverage=obs.coverage, currency="USDT", scope_start_ns=0,
        scope_end_ns=20, witness="complete fee path", times_ns=obs.times_ns,
        paths=(("fees", np.array([1., 2., 3.])),))
    with ReportingCache() as cache:
        cache.reduce("account", obs, contract, retain_episodes=True)
        request = ReportingRequest(account=contract, result_identity=obs.coverage.result_identity,
            execution=execution, partial_mask=(False, False, False), return_witness="complete bars", cache=cache)
        restored = clone(request)
        with pytest.raises(ValueError):
            restored.execution.paths[0][1][0] = 100.
        with pytest.raises(ValueError):
            restored._partial_mask_array[0] = True
        report = restored.cache.reduce("account", obs, contract, retain_episodes=True)
        with pytest.raises(ValueError):
            report.episodes.numbers.setflags(write=True)


@pytest.mark.parametrize("clone", CLONES)
def test_copy_isolates_all_array_headers_without_copying_immutable_bytes(clone):
    original = snapshot()
    restored = clone(original)
    for left, right in zip(arrays(original), arrays(restored)):
        expected = right.copy()
        left.shape = (3, 1)
        assert right.shape == (3,)
        np.testing.assert_array_equal(right, expected)


def test_historical_pickle_state_revalidates_storage_and_recomputes_hash():
    original = snapshot()
    state = dict(original.__dict__)
    state["equity"] = np.array([100., 90., 80.])
    state["returns"] = None
    state["identity"] = original.identity
    restored = object.__new__(AccountObservations)
    restored.__setstate__(state)
    assert restored.identity != original.identity
    assert reduce_account(restored, policy([0, 10, 20])).metric("account.total_return").value == pytest.approx(-.2)
    with pytest.raises(ValueError):
        restored.equity.setflags(write=True)
    with pytest.raises(ValueError, match="complete"):
        object.__new__(AccountObservations).__setstate__({**state, "unknown": True})
    with pytest.raises(ValueError, match="finite"):
        object.__new__(AccountObservations).__setstate__({**state, "equity": [100., 90., np.nan]})
