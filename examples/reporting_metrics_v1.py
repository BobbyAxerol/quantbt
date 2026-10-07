"""Public synthetic reporting example; no strategy secrets or execution replay.

Run: python -m examples.reporting_metrics_v1
"""

from dataclasses import replace

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint, ReportingCache, ReportingContractV1, ReportingRequest


def example():
    index = pd.date_range("2025-01-01", periods=240, freq="h", tz="UTC")
    close = 100 + 3 * np.sin(np.arange(len(index)) / 12)
    market = pd.DataFrame(dict(open=close, high=close+1, low=close-1, close=close, volume=1000), index=index)
    signal = pd.Series(np.where(np.arange(len(index)) % 48 < 24, .5, -.5), index=index)
    endpoint = QuantBTEndpoint.pct_equity(initial_capital=20_000., leverage=2.,
        alloc_per_trade=.25, fee_rate=.0005, use_funding=False)
    result = endpoint.backtest(data=market, signal=signal, symbols=["SYNTH"])
    contract = ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=result.initial_capital, baseline_time_ns=int(index[0].value),
        scope_end_ns=int(index[-1].value), sampling="observed_bar", annual_periods=365*24,
        equity_clock="bar_close")
    with ReportingCache(max_entries=4, max_bytes=1_048_576) as cache:
        request = ReportingRequest(account=contract, result_identity="public-synthetic-one",
            retain_episodes=True, partial_mask=(False,) * len(index),
            return_witness="complete observed hourly synthetic bars; UTC", cache=cache)
        report = endpoint.full_report(reporting=request)
        assert report == result.full_report(reporting=request)
        assert report["groups"]["closed_action"]["status"] == "unavailable"
    return endpoint, result, replace(request, cache=None), report


if __name__ == "__main__":
    endpoint, result, request, report = example()
    endpoint.show_metrics(reporting=request)
    print("Legacy keys unchanged:", sorted(endpoint.full_report()))
