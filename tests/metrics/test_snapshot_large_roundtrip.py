"""Cover bytes-backed writable ancestry seen in larger NumPy pickles."""

from dataclasses import replace
import pickle

import numpy as np
import pytest

from quantbt import ReportingCache
from quantbt.metrics.reporting.execution import ExecutionObservations
from quantbt.metrics.reporting.inputs import AccountObservations, ReturnObservations
from quantbt.metrics.reporting.snapshots import immutable_storage

from .test_account_reducers import coverage, policy, reduce_account
from .test_snapshot_roundtrip import CLONES


def large_snapshot():
    times = np.arange(144, dtype=np.int64) * 3_600_000_000_000
    equity = np.full(len(times), 100.0)
    equity[len(times) // 2] = 90.0
    equity[-1] = 110.0
    returns = ReturnObservations(
        values=equity / np.r_[100.0, equity[:-1]] - 1.0,
        end_times_ns=times,
        partial_mask=np.zeros(len(times), dtype=np.bool_),
        sampling="observed_bar",
        witness="144 complete synthetic hourly marks",
    )
    return AccountObservations(
        times_ns=times, equity=equity, coverage=coverage(), returns=returns,
    )


@pytest.mark.parametrize("clone", CLONES)
def test_large_account_roundtrip_keeps_all_storage_and_headers_immutable(clone):
    original = large_snapshot()
    restored = clone(original)
    assert restored.identity == original.identity
    pairs = (
        (original.times_ns, restored.times_ns),
        (original.equity, restored.equity),
        (original.returns.values, restored.returns.values),
        (original.returns.end_times_ns, restored.returns.end_times_ns),
        (original.returns.partial_mask, restored.returns.partial_mask),
    )
    for left, right in pairs:
        np.testing.assert_array_equal(left, right)
        assert left.dtype == right.dtype
        assert left is not right
        assert not right.flags.writeable
        with pytest.raises(ValueError):
            right.setflags(write=True)
        left.shape = (12, 12)
        assert right.shape == (144,)


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_large_pickled_account_cannot_change_under_a_cached_identity(protocol):
    original = large_snapshot()
    contract = replace(policy(original.times_ns), sampling="observed_bar")
    with ReportingCache() as cache:
        cached = cache.reduce("account", original, contract)
        restored = pickle.loads(pickle.dumps(original, protocol=protocol))
        with pytest.raises(ValueError):
            restored.equity.setflags(write=True)
        with pytest.raises(ValueError):
            restored.equity[-1] = 80.0
        assert cache.reduce("account", restored, contract) is cached
        changed_equity = restored.equity.copy()
        changed_equity[-1] = 80.0
        changed = replace(restored, equity=changed_equity, returns=None)
        assert changed.identity != restored.identity
        corrected = cache.reduce("account", changed, contract)
        assert cached.metric("account.total_return").value == pytest.approx(0.1)
        assert corrected.metric("account.total_return").value == pytest.approx(-0.2)
        assert corrected.to_metadata() == reduce_account(changed, contract).to_metadata()
        assert (cache.hits, cache.misses) == (1, 2)


@pytest.mark.parametrize("clone", CLONES)
def test_large_execution_roundtrip_keeps_fee_path_frozen(clone):
    account = large_snapshot()
    fees = np.arange(144, dtype=np.float64) / 100.0
    original = ExecutionObservations(
        coverage=account.coverage,
        currency="USDT",
        scope_start_ns=int(account.times_ns[0]),
        scope_end_ns=int(account.times_ns[-1]),
        witness="144 recorded synthetic fee marks",
        times_ns=account.times_ns,
        paths=(("fees", fees),),
    )
    restored = clone(original)
    assert restored.identity == original.identity
    np.testing.assert_array_equal(restored.paths[0][1], fees)
    for value in (restored.times_ns, restored.paths[0][1]):
        assert not value.flags.writeable
        with pytest.raises(ValueError):
            value.setflags(write=True)
    with ReportingCache() as cache:
        contract = policy(account.times_ns)
        result = cache.reduce("execution", original, contract)
        assert cache.reduce("execution", restored, contract) is result
        assert result.metric("execution.sum_fees").value == pytest.approx(fees.sum())


def test_readonly_bytes_sharing_is_safe_and_keeps_headers_private():
    original = np.frombuffer(np.arange(144, dtype=np.float64).tobytes(), dtype=np.float64)
    restored = immutable_storage(original)
    assert np.shares_memory(restored, original)
    assert restored is not original
    original.shape = (12, 12)
    assert restored.shape == (144,)
    with pytest.raises(ValueError):
        restored.setflags(write=True)


def test_mutable_owner_is_copied_before_snapshot_storage_is_shared():
    original = np.arange(144, dtype=np.float64)
    restored = immutable_storage(original)
    expected = original.copy()
    original[-1] = -1.0
    np.testing.assert_array_equal(restored, expected)
    assert not np.shares_memory(restored, original)
    with pytest.raises(ValueError):
        restored.setflags(write=True)
