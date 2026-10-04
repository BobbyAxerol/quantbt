"""Block qualification, force-native policy and truthful loaded-thread state."""

import sys

import numpy as np
import pytest

from quantbt.optimization.meta_selection.numerics import NumericRuntime, reference_fit
from quantbt.optimization.meta_selection.telemetry import observed_threads
from tests.meta_selection.test_qms07_performance import native as native_fixture

native = native_fixture


@pytest.mark.parametrize("shape", [(180, 8), (4096, 8), (4096, 24), (512, 64)])
def test_actual_native_dispatch_parity_and_charging(native, shape):
    rng = np.random.default_rng(731)
    v = rng.normal(size=shape)
    y, w = rng.normal(size=shape[0]), np.ones(shape[0]) / shape[0]
    runtime = NumericRuntime(native_policy="auto", native_module=native)
    actual, expected = runtime.fit(v, y, w, 10.), reference_fit(v, y, w, 10.)
    for a, b in zip(actual, expected):
        np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-10)
    count = runtime.dispatch_calls
    runtime.fit(v, y, w, 10.)
    assert runtime.dispatch_calls == count
    if shape == (180, 8):
        assert count == 0 and runtime.selected_blocks["gram_solve"] == "rust"
    else:
        assert count == 3
        assert runtime.dispatch_bytes == 3 * (v.nbytes + y.nbytes + w.nbytes)
    forced = NumericRuntime(native_policy="require", native_module=native)
    forced.fit(v, y, w, 10.)
    assert forced.dispatch_calls == 0 and forced.selected_blocks["gram_solve"] == "rust"


def test_dispatch_can_select_blas_without_changing_math(native, monkeypatch):
    from quantbt.optimization.meta_selection import numerics

    # Exact native math, controlled clock only to test the routing branch.
    ticks = iter([0., 0., 10., 10., 11., 11., 21., 21., 22., 22., 32., 32., 33., 34.])
    monkeypatch.setattr(numerics, "perf_counter", lambda: next(ticks))
    rng = np.random.default_rng(1)
    v, y, w = rng.normal(size=(512, 24)), rng.normal(size=512), np.ones(512)
    runtime = NumericRuntime(native_policy="auto", native_module=native)
    actual = runtime.fit(v, y, w, 10.)
    assert runtime.selected_blocks["gram_solve"] == "numpy" and runtime.calls == 0
    for a, b in zip(actual, reference_fit(v, y, w, 10.)):
        np.testing.assert_array_equal(a, b)


def test_thread_observation_distinct_from_request_and_missing_inspector(monkeypatch):
    import threadpoolctl

    monkeypatch.setattr(threadpoolctl, "threadpool_info", lambda: [
        dict(user_api="blas", internal_api="openblas", num_threads=4, prefix="test", version="x")])
    value = observed_threads(configured=dict(blas_threads=1))
    assert value["mismatches"] == [dict(runtime="test", configured=1, observed=4)]
    assert value["observed"]["native_workers"] is None
    monkeypatch.setitem(sys.modules, "threadpoolctl", None)
    value = observed_threads(configured=dict(blas_threads=1))
    assert value["observed"]["libraries"] is None
    assert value["inspection_limits"] == ["THREADPOOLCTL_NOT_INSTALLED"]
