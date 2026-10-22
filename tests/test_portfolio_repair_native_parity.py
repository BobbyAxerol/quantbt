"""Source-matched native consumer controls, including portfolio review failures."""

from pathlib import Path
import hashlib
import os

import numpy as np
import pandas as pd
import pytest

from quantbt import AccountConfig
from quantbt.backends._native_event_rust import probe_native_event_rust_extension
from quantbt.backends.native_portfolio_package import run_shared_portfolio_target_market
from quantbt.core.preprocessor import make_funding_mask, prepare_funding
from tools.portfolio_account_review import run


@pytest.fixture(scope="module", autouse=True)
def source_matched_extension():
    import _quantbt_native

    status = probe_native_event_rust_extension()
    assert status.available and status.compatible
    artifact = next(Path(_quantbt_native.__file__).parent.glob("*.so"))
    expected = os.environ.get("QUANTBT_REPAIR_NATIVE_SHA256")
    assert expected, "repair native proof requires the freshly built extension hash"
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected


def native(prices, targets, *, policy="sequential_legacy", capital=1000., leverage=10.,
           fee=0., funding_rate=0., index=None, min_qty=0., min_notional=0.):
    values = np.asarray(prices, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    names = tuple(f"S{i}" for i in range(values.shape[1]))
    index = index if index is not None else pd.date_range(
        "2024-01-01 06:00", periods=len(values), freq="h", tz="UTC")
    funding = prepare_funding(funding_rate, list(names), index)
    return run_shared_portfolio_target_market(
        timestamps_ns=index.as_unit("ns").asi8, opens=values, highs=values, lows=values,
        closes=values, volumes=np.ones_like(values), symbols=names,
        funding=np.column_stack([funding[s].to_numpy() for s in names]), funding_mask=make_funding_mask(index),
        contract_sizes=np.ones(len(names)), leverages=np.full(len(names), leverage),
        fee_rates=np.full(len(names), fee), initial_capital=capital, maintenance_ratio=.005,
        slippage_rate=0., use_funding=bool(funding_rate), targets=np.asarray(targets, dtype=float).reshape(values.shape),
        min_qty=np.full(len(names), min_qty), min_notional=np.full(len(names), min_notional),
        admission_policy=policy, report_level="audit",
    ).payload


@pytest.mark.parametrize("policy", ["sequential_legacy", "reduce_first_then_increase",
                                   "pro_rata_to_available_margin", "all_or_none_rebalance"])
def test_fresh_native_partial_reduction_matches_independent_oracle(policy):
    output = native([100, 100, 110], [0, -19, -18], policy=policy,
                    capital=2000., leverage=1., fee=.0004)
    np.testing.assert_allclose(output["positions"], [0, -19, -18])
    np.testing.assert_allclose(output["equity"], [2000, 1999.24, 1809.196])


@pytest.mark.parametrize("policy", ["sequential_legacy", "reduce_first_then_increase",
                                   "pro_rata_to_available_margin", "all_or_none_rebalance"])
def test_fresh_native_delta_minima_and_small_reduction(policy):
    output = native([100] * 5, [0, 1, 1.1, .9, 0], policy=policy, min_qty=.5, min_notional=50.)
    np.testing.assert_allclose(output["positions"], [0, 1, 1, .9, 0])


def test_fresh_native_and_numba_share_actual_funding_and_account_paths():
    prices = [[100, 50], [100, 50], [110, 45], [110, 45]]
    targets = [[0, 0], [2, -3], [2, -3], [0, 0]]
    output = native(prices, targets, fee=.001, funding_rate=.01, policy="all_or_none_rebalance")
    reference = run(prices, targets, fee_rate=.001, use_funding=True, funding_rate=.01)
    np.testing.assert_allclose(output["equity"], [1000, 999.65, 1033.8, 1033.445], atol=1e-9)
    np.testing.assert_allclose(output["equity"], reference.equity, atol=1e-9)
    np.testing.assert_allclose(output["positions"], reference.positions.to_numpy().reshape(-1), atol=1e-12)
    np.testing.assert_allclose(output["funding"], reference.funding, atol=1e-12)
    np.testing.assert_allclose(output["fees"], reference.fees, atol=1e-12)


def test_fresh_native_daily_carried_settlements_match_numba():
    index = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    output = native([100] * 4, [0, 1, 1, 1], index=index, funding_rate=.01)
    reference = run([100] * 4, [0, 1, 1, 1], index=index, use_funding=True,
                    funding_rate=.01, account=AccountConfig(initial_capital=1000, leverage=10))
    np.testing.assert_allclose(output["equity"], [1000, 1000, 997, 994])
    np.testing.assert_allclose(output["equity"], reference.equity)
