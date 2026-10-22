"""Zero-copy Python scalar access must retain the original NumPy-scalar answers."""

import numpy as np
import pytest

from quantbt.metrics.reporting.account import _period_scan
from quantbt.metrics.reporting.drawdown import _scan
from quantbt.metrics.reporting.ledger import _streaks


@pytest.mark.parametrize("seed", range(12))
def test_array_memoryview_scans_are_exact(seed):
    rng = np.random.default_rng(731 + seed)
    values = rng.uniform(-.2, .2, 2000)
    values[::17] = 0.
    args = (8760., seed % 2, .001, .002, .001, bool(seed % 2))
    np.testing.assert_array_equal(_period_scan(values, *args), _period_scan(memoryview(values), *args))
    times = np.arange(2000, dtype=np.int64) * 100
    equity = 100. * np.cumprod(1 + values)
    args = (100., 0, .00001 if seed % 2 else 0., True)
    original = _scan(times, equity, *args)
    optimized = _scan(memoryview(times), memoryview(equity), *args)
    for left, right in zip(original, optimized):
        np.testing.assert_array_equal(left, right)
    assert _streaks(values, .001) == _streaks(memoryview(values), .001)


@pytest.mark.parametrize("values", [[], [0.], [0., 0., 0.], [-1., .1], [-1.5, .1],
                                   [1e150, -1e150, 0.], [1e300, -1e300, 0.], [-1e308, .1]])
def test_scalar_access_keeps_empty_bankrupt_and_extreme_return_policies(values):
    array = np.array(values, dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        original = _period_scan(array, 365., 1, 0., 0., 0., False)
        optimized = _period_scan(memoryview(array), 365., 1, 0., 0., 0., False)
    np.testing.assert_array_equal(original, optimized)
