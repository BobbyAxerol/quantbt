"""Ownership/copy optimizations must preserve the original snapshot contract."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import pickle
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import ReportingCache, ReportingContractV1, ReportingRequest
from quantbt.metrics.reporting.account import reduce_account
from quantbt.metrics.reporting.adapters import account_from_completed
from quantbt.metrics.reporting.inputs import AccountObservations, ReturnObservations, frozen_array
from quantbt.metrics.reporting.public import build_completed_report


def fixture(unit="ns", scope="full", sampling="observed_bar"):
    index = pd.date_range("2025-01-01", periods=60, freq="h", tz="Europe/Paris").as_unit(unit)
    values = 100 + 3*np.sin(np.arange(60)/3)
    result = SimpleNamespace(equity=pd.Series(values, index=index))
    start = 0 if scope == "full" else 7
    end = len(index)-1 if scope == "full" else 47
    contract = ReportingContractV1(scope=scope, unit="account_period", currency="USDT",
        baseline_equity=100., baseline_time_ns=int(index[start].value), scope_end_ns=int(index[end].value),
        sampling=sampling, annual_periods=8760. if sampling == "observed_bar" else 365., equity_clock="bar_close")
    times = index.as_unit("ns").asi8[start:end+1].copy()
    marks = values[start:end+1].copy()
    indices = np.arange(len(marks))
    if sampling == "observed_daily_utc":
        days = times // 86_400_000_000_000
        indices = indices[np.r_[days[1:] != days[:-1], True]]
    mask = (True,) + (False,)*(len(indices)-1)
    request = ReportingRequest(account=contract, result_identity="snapshot-regression",
        partial_mask=mask, return_witness="disclosed synthetic partial periods", retain_episodes=True)
    return result, request, times, marks, indices


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
@pytest.mark.parametrize("scope", ["full", "scoped"])
@pytest.mark.parametrize("sampling", ["observed_bar", "observed_daily_utc"])
@pytest.mark.parametrize("backend", ["python", "numba"])
def test_original_derive_and_sha_exact(unit, scope, sampling, backend):
    result, request, times, marks, indices = fixture(unit, scope, sampling)
    actual = account_from_completed(result, request.account, result_identity=request.result_identity,
        partial_mask=request._partial_mask_array, return_witness=request.return_witness)
    # Original all-bar/daily fancy-index recipe, not the optimized helper.
    values = marks[indices] / np.r_[request.account.baseline_equity, marks[indices][:-1]] - 1
    returns = ReturnObservations(values=values, end_times_ns=times[indices],
        partial_mask=np.asarray(request.partial_mask), sampling=sampling, witness=request.return_witness)
    expected = AccountObservations(times_ns=times, equity=marks, coverage=actual.coverage, returns=returns)
    digest = sha256(json.dumps(dict(coverage=actual.coverage.__dict__, sampling=sampling,
        witness=request.return_witness), sort_keys=True, allow_nan=False, separators=(",", ":")).encode())
    for array in (times, marks, values, times[indices], np.asarray(request.partial_mask)):
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(str(array.shape).encode("ascii"))
        digest.update(array.tobytes())
    assert actual.identity == expected.identity == digest.hexdigest()
    for partial in ("include_disclosed", "exclude_disclosed"):
        contract = replace(request.account, partial_periods=partial)
        assert reduce_account(actual, contract, backend=backend, retain_episodes=True).to_metadata() == \
            reduce_account(expected, contract, backend=backend, retain_episodes=True).to_metadata()


@pytest.mark.parametrize("kind", ["writable", "readonly", "view", "memoryview", "readonly_memoryview", "strided"])
def test_mutable_owners_are_always_snapshotted(kind):
    owner = np.arange(12, dtype=np.float64)
    if kind == "readonly":
        owner.setflags(write=False)
    inputs = {"writable": owner, "readonly": owner, "view": owner.view(),
        "memoryview": memoryview(owner), "readonly_memoryview": memoryview(owner).toreadonly(),
        "strided": owner[::2]}
    frozen = frozen_array(inputs[kind], np.float64)
    before = frozen.copy()
    assert not np.shares_memory(frozen, owner)
    owner.setflags(write=True)
    owner[:] = -1
    np.testing.assert_array_equal(frozen, before)
    with pytest.raises(ValueError):
        frozen.setflags(write=True)


@pytest.mark.parametrize("kind", ["direct", "view", "slice", "reshape"])
def test_only_bytes_owned_contiguous_arrays_reuse(kind):
    owner = np.frombuffer(np.arange(12, dtype=np.float64).tobytes(), np.float64)
    values = {"direct": owner, "view": owner.view(), "slice": owner[2:8], "reshape": owner.reshape(3, 4).reshape(-1)}[kind]
    frozen = frozen_array(values, np.float64)
    assert np.shares_memory(frozen, values)
    with pytest.raises(ValueError):
        frozen.setflags(write=True)


@pytest.mark.parametrize("clone", [lambda v: v, deepcopy, lambda v: pickle.loads(pickle.dumps(v))])
def test_mask_preparation_survives_request_copy_and_is_not_reversible(clone):
    _, request, *_ = fixture()
    request = clone(request)
    assert tuple(request._partial_mask_array) == request.partial_mask
    with pytest.raises(ValueError):
        request._partial_mask_array.setflags(write=True)
    changed = replace(request, partial_mask=(False,)*len(request.partial_mask))
    assert not changed._partial_mask_array.any()
    assert request._partial_mask_array[0]


def test_public_hash_once_per_call_and_cache_still_detects_source_mutation(monkeypatch):
    from quantbt.metrics.reporting import inputs
    result, request, *_ = fixture()
    original, calls = inputs.identity, []
    def spy(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(inputs, "identity", spy)
    with ReportingCache() as cache:
        request = replace(request, cache=cache)
        first = build_completed_report(result, request).to_metadata()
        assert build_completed_report(result, request).to_metadata() == first
        assert cache.hits == 1 and len(calls) == 2
        result.equity.iloc[-1] -= 5
        changed = build_completed_report(result, request).to_metadata()
        assert changed != first and cache.misses == 2 and len(calls) == 3


def test_plot_uses_same_single_snapshot_as_reduction(monkeypatch):
    import matplotlib.pyplot as plt
    from quantbt.metrics.reporting import public
    from quantbt.metrics.reporting.plot import plot_reporting_account
    result, request, *_ = fixture()
    original, captured = public.account_from_completed, []
    def spy(*args, **kwargs):
        obs = original(*args, **kwargs)
        captured.append(obs)
        return obs
    monkeypatch.setattr(public, "account_from_completed", spy)
    figure = plot_reporting_account(result, request)
    try:
        assert len(captured) == 1
        np.testing.assert_array_equal(figure.axes[0].lines[0].get_ydata()[1:], captured[0].equity)
        figure.canvas.draw()
    finally:
        plt.close(figure)
