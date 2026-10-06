"""Independent sampling/status checks; no new Sharpe or financial estimator."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.observer import (
    ResultMetricAdapter, canonical_metric_contract, economics_identity, market_signature,
)
from quantbt.optimization.meta_selection.records import OutcomeStatus


def original(prices, *, capital=20000., alloc=1000., leverage=2., frequency="D"):
    values = np.asarray(prices, dtype=float)
    idx = pd.date_range("2023-01-01", periods=len(values), freq=frequency, tz="UTC")
    frame = pd.DataFrame({k: values for k in ("open", "high", "low", "close")}, index=idx)
    frame["volume"] = 1000.
    endpoint = QuantBTEndpoint(mode="single_signal", sizing="unit", initial_capital=capital, alloc_per_trade=alloc,
        leverage=leverage, fee_rate=0., slippage=0., use_funding=False,
        backend="native_vectorized")
    result = endpoint.backtest(data=frame, signal=pd.Series(1., index=idx), symbols=["X"])
    return endpoint, result, frame


def observe(endpoint, result, frame, *, expected=None):
    return ResultMetricAdapter(canonical_metric_contract()).observe(result,
        expected_index=frame.index if expected is None else expected,
        economics_id=economics_identity(endpoint.config, symbols=["X"]),
        input_signature=market_signature(frame, frame.index, config=endpoint.config),
        execution_config=endpoint.config)


def test_pre02_m06_daily_first_hourly_raw_sharpe_ddof_activity():
    t = np.arange(24*31)/24
    endpoint, result, frame = original(100*np.exp(.00015*t+.025*np.sin(t/11)+.01*np.cos(t/5)), frequency="h")
    observation = observe(endpoint, result, frame)
    # The authoritative account, sampled by UTC day's last mark, independently.
    daily = result.equity.groupby(result.equity.index.normalize()).last().to_numpy()
    sample = daily[1:]/daily[:-1]-1
    expected = sample.mean()/sample.std(ddof=1)*np.sqrt(365)
    assert observation.raw_sharpe == pytest.approx(expected, rel=1e-12, abs=1e-12)
    assert observation.sample_count == 30
    assert observation.sample_std == pytest.approx(sample.std(ddof=1), rel=1e-12)
    positions = result.positions.to_numpy()
    activity = positions.shape[1]+np.count_nonzero(np.diff(positions, axis=0))
    assert observation.activity_count == activity == 2  # Initial count + next-bar entry.
    assert observation.status == OutcomeStatus.VALID


def test_pre02_m06_valid_near_zero_is_not_undefined():
    endpoint, result, frame = original([100., 100., 110., 99., 108.9, 98.01], capital=100., alloc=100.)
    observation = observe(endpoint, result, frame)
    assert observation.sample_std > 0
    assert observation.raw_sharpe == pytest.approx(0., abs=1e-12)
    assert observation.status == OutcomeStatus.VALID


def test_pre02_m06_flat_liquidated_and_incomplete_remain_distinct():
    endpoint, flat, frame = original([100.]*6)
    assert observe(endpoint, flat, frame).status == OutcomeStatus.NO_VARIANCE
    endpoint, bankrupt, frame = original([100., 100., 120., 1., 1., 1., 1.], capital=100., alloc=200., leverage=3.)
    assert bankrupt.liquidated and bankrupt.equity.iloc[-1] == 0.
    observation = observe(endpoint, bankrupt, frame)
    assert observation.status == OutcomeStatus.CENSORED
    assert observation.sample_count == 6  # Legacy zero-base sample contract is retained.
    assert observe(endpoint, bankrupt, frame, expected=frame.index[:-1]).status == OutcomeStatus.INCOMPLETE_WINDOW


def test_pre02_m07_foreign_economics_cannot_relabel_original_measurement():
    endpoint, result, frame = original([100., 101., 99., 102.])
    from quantbt.optimization.meta_selection.common import MetaRecordError
    changed = replace(endpoint.config, account=replace(endpoint.config.account, leverage=1.))
    with pytest.raises(MetaRecordError, match="economics"):
        ResultMetricAdapter(canonical_metric_contract()).observe(result, expected_index=frame.index,
            economics_id=economics_identity(changed, symbols=["X"]),
            input_signature=market_signature(frame, frame.index, config=changed))


def test_pre02_intrabar_full_funding_series_matches_exact_original_window():
    from tests.meta_selection.pre_e06_02_support import endpoint, generate, tape, account_equal
    from quantbt.wfo_execution import execute_window
    data = tape("intrabar", end="2020-06-30")
    bt = endpoint("intrabar", data, "off")
    config = bt.config.wfo_execution_config
    index = data.index[90:120]
    payload = generate("intrabar", data, {"window": 5}, index)
    a = execute_window(config, data, payload)
    b = execute_window(replace(config, funding_rate=config.funding_rate.loc[index]), data, payload)
    account_equal(a, b)
    assert np.count_nonzero(a.funding) > 0
    # Rates must not be filled or silently repaired when a required bar is absent.
    with pytest.raises(KeyError):
        execute_window(replace(config, funding_rate=config.funding_rate.drop(index[0])), data, payload)
    with pytest.raises(ValueError, match="unique"):
        execute_window(replace(config, funding_rate=pd.concat([config.funding_rate, config.funding_rate])), data, payload)


def test_pre02_exact_source_amendment_rejects_unreviewed_changes():
    from tools.qms_pre02_source_guard import NAME, BASE, ROOT, verify, without_pre02_repairs
    assert verify()["scientific_estimator_changed"] is False
    for name in (NAME, BASE):
        with pytest.raises(AssertionError, match="unreviewed"):
            without_pre02_repairs((ROOT/name).read_bytes()+b"\n# hidden change\n", name)


def test_pre02_historical_inventory_does_not_certify_amended_source():
    import json
    from tools import qms_pre_e06_inventory as audit
    from tools.qms_pre02_source_guard import verify_pre01_archive
    payload = json.loads((audit.ROOT/audit.MANIFEST).read_text())
    assert verify_pre01_archive(payload) is payload
    with pytest.raises(ValueError, match="cannot change runtime"):
        audit.verify_manifest(payload)
