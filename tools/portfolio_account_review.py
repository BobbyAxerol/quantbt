"""Bounded synthetic audit; records discrepancies without changing runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource

import numpy as np
import pandas as pd

from quantbt import AccountConfig, ExecutionConfig, PortfolioBacktestEngine
from quantbt.core.schema import FillPricePolicy, MarginMode, OmsMode
from quantbt.core.preprocessor import make_funding_mask


def run(closes, targets, *, index=None, **kwargs):
    prices = np.asarray(closes, dtype=float)
    target = np.asarray(targets, dtype=float)
    if prices.ndim == 1:
        prices = prices[:, None]
    if target.ndim == 1:
        target = target[:, None]
    index = index if index is not None else pd.date_range(
        "2024-01-01 06:00", periods=len(prices), freq="h", tz="UTC"
    )
    names = [f"S{i}" for i in range(prices.shape[1])]
    close = {s: pd.Series(prices[:, j], index=index) for j, s in enumerate(names)}
    positions = {s: pd.Series(target[:, j], index=index) for j, s in enumerate(names)}
    low_values = np.asarray(kwargs.pop("low_values", prices), dtype=float).reshape(prices.shape)
    high_values = np.asarray(kwargs.pop("high_values", prices), dtype=float).reshape(prices.shape)
    defaults = dict(
        positions=positions, closes=close, datetime_index=index,
        lows={s: pd.Series(low_values[:, j], index=index) for j, s in enumerate(names)},
        highs={s: pd.Series(high_values[:, j], index=index) for j, s in enumerate(names)},
        account=AccountConfig(initial_capital=1000, leverage=10),
        hedge_type="target_units", backend="native_portfolio", contract_size=1,
        use_funding=False, fee_rate=0, funding_rate=0,
    )
    defaults.update(kwargs)
    return PortfolioBacktestEngine(**defaults).result


def view(result):
    return dict(
        equity=result.equity.tolist(), positions=result.positions.to_numpy().tolist(),
        fees=None if result.fees is None else result.fees.tolist(),
        funding=None if result.funding is None else result.funding.tolist(),
        margin=None if result.margin is None else result.margin.to_dict("list"),
        liquidated=result.liquidated,
        reconciliation=result.metadata.get("portfolio_reconciliation_report"),
        contract=result.metadata.get("portfolio_contract_report"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metrics-only", action="store_true")
    args = parser.parse_args()
    if args.metrics_only:
        metrics_review(args.output)
        return
    evidence = {}
    # Independently calculated linear long/short accounting, funding and fee.
    good = run([[100, 50], [100, 50], [110, 45], [110, 45]],
               [[0, 0], [2, -3], [2, -3], [0, 0]],
               fee_rate=.001, use_funding=True, funding_rate=.01)
    expected = [1000, 999.65, 1033.8, 1033.445]
    np.testing.assert_allclose(good.equity, expected, rtol=0, atol=1e-9)
    evidence["linear_control"] = {"expected_equity": expected, "actual": view(good)}

    modes = {}
    for mode in MarginMode:
        for oms in OmsMode:
            modes[f"{mode.value}/{oms.value}"] = view(run(
                [100, 100, 100], [0, 15, 15],
                account=AccountConfig(initial_capital=1000, leverage=2,
                                      margin_mode=mode, oms_mode=oms, margin_buffer=.5)))
    evidence["account_modes"] = modes
    policies = {}
    for policy in (FillPricePolicy.CLOSE, FillPricePolicy.NEXT_OPEN, FillPricePolicy.OPEN):
        policies[policy.value] = view(run(
            [100, 100, 120], [0, 1, 1],
            execution=ExecutionConfig(fill_price_policy=policy, min_order_notional=1000)))
    evidence["execution_options"] = policies

    masks = {}
    for freq in ("h", "8h", "12h", "D"):
        index = pd.date_range("2024-01-01", periods=5, freq=freq, tz="UTC")
        masks[freq] = {"index": index.astype(str).tolist(), "mask": make_funding_mask(index).tolist()}
    evidence["funding_clock"] = masks
    daily = run([100] * 4, [0, 1, 1, 1],
                index=pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC"),
                use_funding=True, funding_rate=.01)
    evidence["daily_funding"] = view(daily)

    liq = run([100, 100, 100, 100], [0, 10, 10, 0], low_values=[100, 100, 10, 100],
              account=AccountConfig(initial_capital=100, leverage=20),
              use_funding=True, funding_rate=.01)
    evidence["liquidation_funding_reconciliation"] = view(liq)

    legs = run([[100, 100]] * 3, [[0, 0], [1, -1], [0, 0]],
               fee_rate=.01, execution=ExecutionConfig(slippage_bps=100))
    leg_pnl = legs.metadata["symbol_pnl_report"]
    evidence["leg_fee_attribution"] = {
        "actual": view(legs), "entry_fees": leg_pnl[leg_pnl.timestamp == legs.equity.index[1]][["symbol", "fee", "total_pnl"]].to_dict("records"),
        "expected_entry_fees": {"S0": 1.01, "S1": .99},
        "kernel_symbol_pnl": legs.metadata["kernel_symbol_pnl"].to_dict("list"),
    }
    reduction = run([100, 100, 110], [0, -19, -18],
                    account=AccountConfig(initial_capital=2000, leverage=1), fee_rate=.0004)
    evidence["risk_reduction_below_initial_margin"] = {
        "actual": view(reduction), "expected_reduced_qty": -18,
        "equity_after_requested_reduction": 1809.196,
        "required_initial_margin": 1980, "maintenance_margin": 9.9,
    }
    qty = run([100] * 3, [0, 1, 1.1], min_qty=.5, min_notional=50)
    evidence["delta_minimum_order"] = {"actual": view(qty), "second_delta": .1,
                                      "min_qty": .5, "min_notional": 50}
    heterogeneous = run([[100, 100]] * 3, [[0, 0], [1, -1], [1, -1]],
                        leverage={"S0": 1, "S1": 10})
    evidence["buying_power"] = heterogeneous.metadata["exposure_report"].to_dict("list")
    evidence["finite_validation"] = view(run([100] * 3, [0, 100, 100], leverage=float("nan")))

    evidence["contract_size_sizing"] = {}
    for backend in ("native_portfolio", "legacy_portfolio"):
        for sizing in ("signal_notional", "notional", "unit"):
            observed = run([100, 100, 101], [0, 1, 1], backend=backend,
                           hedge_type=sizing, alloc_per_trade=100, contract_size=10)
            evidence["contract_size_sizing"][f"{backend}/{sizing}"] = view(observed)
    evidence["legacy_missing_marks"] = view(run(
        [100, 100, np.nan, 100], [0, 1, 1, 1], backend="legacy_portfolio",
        hedge_type="signal_notional", alloc_per_trade=100))
    evidence["legacy_constraints"] = view(run(
        [100] * 3, [0, 1, 1], backend="legacy_portfolio", hedge_type="signal_notional",
        alloc_per_trade=15, qty_step=.1, min_notional=200,
        execution=ExecutionConfig(slippage_bps=100)))
    evidence["native_constraints_control"] = view(run(
        [100] * 3, [0, 1, 1], hedge_type="signal_notional",
        alloc_per_trade=15, qty_step=.1, min_notional=200))

    from quantbt import BacktestEngine
    legacy_index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    legacy_old = BacktestEngine(
        Datetime=legacy_index,
        Position={"A": pd.Series([0, 1, 1, 1], index=legacy_index),
                  "B": pd.Series(0., index=legacy_index)},
        Close={"A": pd.Series(100., index=legacy_index),
               "B": pd.Series(100., index=legacy_index)},
        initial_capital=50, leverage=1, alloc_per_trade=100,
        fee=0, slippage=0, use_funding_rate=False).result
    evidence["old_backtester_rejected_positions"] = {
        "equity": legacy_old.equity.tolist(), "positions": legacy_old.positions.to_dict("list"),
        "metrics": legacy_old.full_report()}
    flat = run([[100, 100]] * 4, [[0, 0]] * 4)
    legs_only = run([[100, 100], [100, 100], [110, 105], [110, 105]],
                    [[0, 0], [1, -1], [1, -1], [0, 0]])
    evidence["legacy_metrics"] = {
        "flat": flat.full_report(), "winning_account_losing_short": legs_only.full_report(),
        "symbol_pnl": legs_only.metadata["kernel_symbol_pnl"].to_dict("list"),
        "fills_count": len(legs_only.fills), "trades_count": len(legs_only.trades)}

    from quantbt.metrics.performance import compute_performance_metrics
    dd_index = pd.date_range("2024-01-01 09:00", periods=4, freq="h", tz="UTC")
    dd_equity = np.array([1000., 1200., 1000., 1100.])
    evidence["intraday_drawdown_duration"] = compute_performance_metrics(
        timestamps=dd_index, equity=dd_equity, returns=pd.Series(dd_equity).pct_change().fillna(0),
        positions=np.zeros((4, 1)), symbols=["S0"], initial_capital=1000)

    from quantbt.backends.native_portfolio_package import run_shared_portfolio_target_market
    def rust_case(prices, targets, **kw):
        prices = np.array(prices, dtype=float).reshape(-1, 1)
        index = pd.date_range("2024-01-01 06:00", periods=len(prices), freq="h", tz="UTC")
        inputs = dict(timestamps_ns=index.asi8, opens=prices, highs=prices, lows=prices,
                      closes=prices, volumes=np.ones_like(prices), funding=np.zeros_like(prices),
                      funding_mask=make_funding_mask(index), symbols=("S0",),
                      contract_sizes=np.ones(1), leverages=np.ones(1), fee_rates=np.array([.0004]),
                      initial_capital=2000, maintenance_ratio=.005, slippage_rate=0,
                      use_funding=False, targets=np.array(targets, dtype=float).reshape(-1, 1),
                      report_level="audit", admission_policy="all_or_none_rebalance")
        inputs.update(kw)
        result = run_shared_portfolio_target_market(**inputs)
        return {key: np.asarray(result.payload[key]).tolist() for key in
                ("equity", "positions", "fees", "funding", "initial_margin", "maintenance_margin", "liquidated")}
    evidence["rust_risk_reduction"] = rust_case([100, 100, 110], [0, -19, -18])
    evidence["rust_minimum_delta"] = rust_case([100] * 3, [0, 1, 1.1], qty_step=np.array([.1]),
                                              min_qty=np.array([.5]), min_notional=np.array([50.]))
    evidence["rust_risk_reduction_policies"] = {
        policy: rust_case([100, 100, 110], [0, -19, -18], admission_policy=policy)
        for policy in ("sequential_legacy", "reduce_first_then_increase", "pro_rata_to_available_margin")}
    evidence["rust_liquidation_funding"] = rust_case(
        [100] * 4, [0, 10, 10, 0], lows=np.array([100, 100, 10, 100.]).reshape(-1, 1),
        initial_capital=100, leverages=np.array([20.]), fee_rates=np.zeros(1),
        funding=np.full((4, 1), .01), use_funding=True)

    sources = ["src/quantbt/core/engine.py", "src/quantbt/backends/native_portfolio.py",
               "src/quantbt/portfolio.py", "src/quantbt/core/preprocessor.py",
               "src/quantbt/core/schema.py", "src/quantbt/engines.py",
               "rust/crates/quantbt-execution/src/target.rs"]
    import _quantbt_native
    from quantbt.backends._native_event_rust import probe_native_event_rust_extension
    native_root = Path(_quantbt_native.__file__).parent
    native_status = probe_native_event_rust_extension()
    evidence["native_status"] = {"version": native_status.version,
                                 "compatible": native_status.compatible,
                                 "reason": native_status.reason}
    evidence["native_artifacts"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in native_root.glob("*.so")
    }
    evidence["source_hashes"] = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}
    evidence["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(evidence, stream, indent=2, allow_nan=True, default=str)
    print(json.dumps({"receipt": str(args.output), "cases": len(evidence),
                      "peak_rss_kib": evidence["peak_rss_kib"]}))


def metrics_review(output):
    from quantbt import MultiSymbolPortfolio
    from quantbt.metrics.performance import compute_performance_metrics
    from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
    from quantbt.metrics.reporting.ledger_inputs import RecordedOutcome, LedgerObservations
    from quantbt.metrics.reporting.ledger import reduce_ledger
    from quantbt.metrics.reporting.public import build_completed_report
    from quantbt.metrics.reporting.request import ReportingRequest

    evidence = {}
    index = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    evidence["timestamp_resolution"] = {
        unit: compute_performance_metrics(
            timestamps=index.as_unit(unit), equity=[100, 90, 99], returns=[0, -.1, .1],
            positions=np.zeros((3, 2)), symbols=["A", "B"], initial_capital=100)
        for unit in ("ns", "us")}
    legacy = MultiSymbolPortfolio(
        positions={"A": pd.Series([0., 1., 0.], index), "B": pd.Series(0., index)},
        closes={"A": pd.Series([100., 200., 100.], index), "B": pd.Series(100., index)},
        datetime_index=index, hedge_type="unit", alloc_per_trade=100,
        initial_capital=1000, fee_rate=0, use_funding=False)
    evidence["legacy_side_hitrate"] = {
        "equity": legacy.result.equity.tolist(), "per_symbol": legacy.hitrate_per_symbol()}

    contract = ReportingContractV1(
        scope="full", unit="closed_trade", currency="USD", baseline_equity=100,
        baseline_time_ns=0, scope_end_ns=30, sampling="observed_bar", annual_periods=365,
        equity_clock="bar_close", matching="position_episode", ledger_scope="closed_in_scope_lifetime")
    coverage = ReportingCoverageV1(result_identity="r", producer="snapshot", profile="audit",
                                   ledger="complete", retained_rows=1, dropped_rows=0)
    row = RecordedOutcome(trade_id="t", symbol="A", side="long", currency="USD",
                          opened_at_ns=0, closed_at_ns=10, close_sequence=0, net_pnl=1.)
    observations = LedgerObservations(records=(row,), coverage=coverage,
                                     matching="position_episode", valuation_time_ns=10)
    evidence["stale_ledger"] = {
        "snapshot_end_ns": 10, "requested_scope_end_ns": 30,
        "report": reduce_ledger(observations, contract).to_metadata()}

    result = run([100] * 4, [0, 1, 1, 0])
    times = result.equity.index.asi8
    account_contract = ReportingContractV1(
        scope="full", unit="account_period", currency="USD", baseline_equity=1000,
        baseline_time_ns=int(times[0]), scope_end_ns=int(times[-1]),
        sampling="observed_bar", annual_periods=365 * 24, equity_clock="bar_close")
    request = ReportingRequest(account=account_contract, result_identity="review-result",
                               partial_mask=(False,) * 4, return_witness="complete synthetic hourly marks")
    evidence["new_report_without_ledger"] = build_completed_report(result, request).to_metadata()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(evidence, stream, indent=2, allow_nan=True, default=str)
    print(json.dumps({"receipt": str(output), "cases": len(evidence)}))


if __name__ == "__main__":
    main()
