#!/usr/bin/env python3
"""
Phase 12A arbitrage production-certification smoke runner.

The runner uses deterministic realistic market data inspired by the local
Arbops Binance basis-arb alpha, but it does not import or commit that private
alpha.  The copied alpha sandbox, if present, must live under
`.local_arbitrage_sandboxes/` and is intentionally git-ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    AccountConfig,
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    CrossExchangeArbSpec,
    ExecutionConfig,
    HedgePolicy,
    HedgePolicyKind,
    IndexBasketArbSpec,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    OptionsVolArbSpec,
    PackageExecutionKind,
    SignalModel,
    SignalModelKind,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
    TriangularArbSpec,
    build_arbitrage_order_plan,
    compare_native_arbitrage_results,
    build_arbitrage_domain_audit,
)


def generate_basis_market(rows: int = 900, seed: int = 42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=rows, freq="1h", tz="UTC")
    base_ret = rng.normal(0.0, 0.006, size=rows)
    perp = 25_000.0 * np.exp(np.cumsum(base_ret))
    basis = 550.0 * np.exp(-np.linspace(0.0, 4.5, rows)) + 65.0 * np.sin(np.linspace(0.0, 18.0, rows))
    basis += rng.normal(0.0, 18.0, size=rows)
    quarterly = np.maximum(perp + basis, 1.0)
    spread = pd.Series(perp - quarterly, index=idx)
    z = (spread - spread.rolling(48, min_periods=12).mean()) / spread.rolling(48, min_periods=12).std()
    signal = pd.Series(np.where(z > 1.0, 1.0, np.where(z < -1.0, -1.0, 0.0)), index=idx).ffill().fillna(0.0)
    # Force a terminal flat state so audit can verify package flattening.
    signal.iloc[-3:] = 0.0

    closes = {
        "perpetual": pd.Series(perp, index=idx),
        "quarterly": pd.Series(quarterly, index=idx),
    }
    highs = {symbol: series * 1.002 for symbol, series in closes.items()}
    lows = {symbol: series * 0.998 for symbol, series in closes.items()}
    funding = {
        "perpetual": pd.Series(0.00004 + rng.normal(0.0, 0.00001, size=rows), index=idx),
        "quarterly": pd.Series(0.0, index=idx),
    }
    return idx, signal, closes, highs, lows, funding


def basis_spec() -> BasisArbitrageSpec:
    return BasisArbitrageSpec(
        arb_id="PHASE12_BTC_PERP_QUARTERLY",
        legs=(
            ArbitrageLeg(
                "perpetual",
                1.0,
                role="perp",
                contract_type=ContractType.LINEAR,
                contract_size=1.0,
                funding_enabled=True,
            ),
            ArbitrageLeg(
                "quarterly",
                -1.0,
                role="quarterly",
                contract_type=ContractType.LINEAR,
                contract_size=1.0,
                funding_enabled=False,
            ),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(
            kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=20_000.0,
            reference_symbol="perpetual",
        ),
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )


def stat_spec() -> StatArbPairSpec:
    return StatArbPairSpec(
        arb_id="PHASE12_STAT_PAIR",
        legs=(
            ArbitrageLeg("asset_a", 1.0, role="base", contract_type=ContractType.LINEAR),
            ArbitrageLeg("asset_b", -1.0, role="hedge", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=30_000.0),
        signal_model=SignalModel(kind=SignalModelKind.ZSCORE),
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )


def run_certification(rows: int = 900, include_nautilus: bool = False) -> Dict:
    idx, signal, closes, highs, lows, funding = generate_basis_market(rows=rows)
    account = AccountConfig(initial_capital=100_000.0, leverage=8.0, maintenance_ratio=0.005)
    execution = ExecutionConfig(slippage_bps=0.0)
    event = NativeEventBackend(NativeEventConfig(account=account, execution=execution, fee_rate=0.0002, use_funding=True))
    vector = NativeVectorizedBackend(NativeVectorizedConfig(account=account, execution=execution, fee_rate=0.0002, use_funding=True))

    spec = basis_spec()
    event_result = event.run_basis_arbitrage(idx, spec, signal, closes, highs=highs, lows=lows, funding_rate=funding)
    vector_result = vector.run_basis_arbitrage(idx, spec, signal, closes, highs=highs, lows=lows, funding_rate=funding)
    basis_audit = build_arbitrage_domain_audit(event_result, raise_on_fail=False)
    basis_parity = compare_native_arbitrage_results(event_result, vector_result, raise_on_fail=False)

    stat_idx, stat_signal, stat_closes, stat_highs, stat_lows, stat_funding = _stat_market(rows=rows)
    stat_event = event.run_stat_arb_pair_arbitrage(stat_idx, stat_spec(), stat_signal, stat_closes, highs=stat_highs, lows=stat_lows, funding_rate=stat_funding)
    stat_vector = vector.run_stat_arb_pair_arbitrage(stat_idx, stat_spec(), stat_signal, stat_closes, highs=stat_highs, lows=stat_lows, funding_rate=stat_funding)
    stat_audit = build_arbitrage_domain_audit(stat_event, raise_on_fail=False)
    stat_parity = compare_native_arbitrage_results(stat_event, stat_vector, raise_on_fail=False)

    basket_report = _index_basket_smoke(event, vector, rows)
    schema_report = _schema_only_report(event, vector, idx, signal, closes)
    nautilus_report = _optional_nautilus_report(idx, spec, signal, closes, include_nautilus)

    passed = bool(
        basis_audit["passed"]
        and basis_parity["passed"]
        and _accounting_parity_passed(stat_parity)
        and basket_report["passed"]
        and schema_report["passed"]
        and nautilus_report["status"] in {"pass", "skipped"}
    )
    return {
        "status": "pass" if passed else "fail",
        "sandbox_path": str(PACKAGE_DIR / ".local_arbitrage_sandboxes" / "binance_basis_arb"),
        "basis": _result_summary(event_result, vector_result, basis_audit, basis_parity),
        "stat_pair": {
            "event_final_equity": float(stat_event.equity.iloc[-1]),
            "vectorized_final_equity": float(stat_vector.equity.iloc[-1]),
            "accounting_parity_passed": _accounting_parity_passed(stat_parity),
            "audit": stat_audit,
            "parity": stat_parity,
            "package_report_columns": list(stat_event.metadata["package_pnl_report"].columns),
            "max_package_residual": float(stat_event.metadata["package_pnl_report"]["pnl_residual"].abs().max()),
        },
        "index_basket": basket_report,
        "schema_only": schema_report,
        "nautilus": nautilus_report,
    }


def make_markdown(report: Dict) -> str:
    basis = report["basis"]
    lines = [
        "# Phase 12A Arbitrage Production Certification",
        "",
        f"Status: **{report['status']}**",
        f"Sandbox path: `{report['sandbox_path']}`",
        "",
        "## Basis Perp-Quarterly",
        "",
        f"- Event final equity: `{basis['event_final_equity']:.6f}`",
        f"- Vectorized final equity: `{basis['vectorized_final_equity']:.6f}`",
        f"- Max equity diff: `{basis['parity']['max_abs_equity_diff']}`",
        f"- Audit status: `{basis['audit']['status']}`",
        f"- Orders: `{basis['order_count']}`",
        f"- Fills: `{basis['fill_count']}`",
        f"- Fees: `{basis['fee_total']:.6f}`",
        f"- Funding: `{basis['funding_total']:.6f}`",
        "",
        "## Other Certification Checks",
        "",
        f"- Stat pair accounting parity: `{report['stat_pair']['accounting_parity_passed']}`",
        f"- Stat pair audit status: `{report['stat_pair']['audit']['status']}`",
        f"- Stat pair package-residual report: `{report['stat_pair']['parity']['checks'].get('package_residuals_ok')}`",
        f"- Stat pair max package residual: `{report['stat_pair']['max_package_residual']}`",
        f"- Index basket package smoke: `{report['index_basket']['status']}`",
        f"- Schema-only guardrails: `{report['schema_only']['status']}`",
        f"- Nautilus package parity: `{report['nautilus']['status']}`",
    ]
    return "\n".join(lines) + "\n"


def _stat_market(rows: int):
    idx = pd.date_range("2023-01-01", periods=rows, freq="1h", tz="UTC")
    t = np.linspace(0.0, 12.0, rows)
    a = 100.0 + np.cumsum(np.sin(t) * 0.05 + 0.1)
    b = 50.0 + np.cumsum(np.sin(t + 0.4) * 0.025 + 0.05)
    spread = pd.Series(a - 2.0 * b, index=idx)
    z = (spread - spread.rolling(36, min_periods=12).mean()) / spread.rolling(36, min_periods=12).std()
    signal = pd.Series(np.where(z > 1.0, -1.0, np.where(z < -1.0, 1.0, 0.0)), index=idx).fillna(0.0)
    signal.iloc[-3:] = 0.0
    closes = {"asset_a": pd.Series(a, index=idx), "asset_b": pd.Series(b, index=idx)}
    highs = {s: c * 1.001 for s, c in closes.items()}
    lows = {s: c * 0.999 for s, c in closes.items()}
    funding = {s: pd.Series(0.0, index=idx) for s in closes}
    return idx, signal, closes, highs, lows, funding


def _index_basket_smoke(event: NativeEventBackend, vector: NativeVectorizedBackend, rows: int) -> Dict:
    idx = pd.date_range("2023-01-01", periods=rows, freq="1h", tz="UTC")
    closes = {
        "ETF": pd.Series(100.0 + np.linspace(0.0, 3.0, rows), index=idx),
        "A": pd.Series(30.0 + np.linspace(0.0, 1.0, rows), index=idx),
        "B": pd.Series(70.0 + np.linspace(0.0, 2.0, rows), index=idx),
    }
    signal = pd.Series(0.0, index=idx)
    signal.iloc[20: rows // 2] = 1.0
    signal.iloc[-3:] = 0.0
    spec = IndexBasketArbSpec(
        arb_id="PHASE12_INDEX_BASKET",
        legs=(ArbitrageLeg("ETF", -1.0), ArbitrageLeg("A", 1.0), ArbitrageLeg("B", 1.0)),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.NOTIONAL_NEUTRAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=30_000.0),
        execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )
    event_result = event.run_package_arbitrage(idx, spec, signal, closes)
    vector_result = vector.run_package_arbitrage(idx, spec, signal, closes)
    parity = compare_native_arbitrage_results(event_result, vector_result, raise_on_fail=False)
    return {"status": "pass" if parity["passed"] else "fail", "passed": bool(parity["passed"]), "parity": parity}


def _schema_only_report(event: NativeEventBackend, vector: NativeVectorizedBackend, idx, signal, closes) -> Dict:
    probes = {}
    specs = {
        "cross_exchange": CrossExchangeArbSpec(
            arb_id="X",
            legs=(
                ArbitrageLeg("BINANCE_BTCUSDT", 1.0, venue="BINANCE"),
                ArbitrageLeg("OKX_BTCUSDT", -1.0, venue="OKX"),
            ),
            hedge_policy=HedgePolicy(kind=HedgePolicyKind.NOTIONAL_NEUTRAL),
            sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=10_000.0),
        ),
        "triangular": TriangularArbSpec(
            arb_id="T",
            legs=(
                ArbitrageLeg("BTCUSDT", 1.0, base_currency="BTC", quote_currency="USDT"),
                ArbitrageLeg("ETHBTC", 1.0, base_currency="ETH", quote_currency="BTC"),
                ArbitrageLeg("ETHUSDT", -1.0, base_currency="ETH", quote_currency="USDT"),
            ),
            hedge_policy=HedgePolicy(kind=HedgePolicyKind.NOTIONAL_NEUTRAL),
            sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=10_000.0),
        ),
        "options_vol": OptionsVolArbSpec(
            arb_id="O",
            legs=(
                ArbitrageLeg("BTC_CALL", 1.0, contract_type=ContractType.OPTION),
                ArbitrageLeg("BTC_PERP", -0.5, contract_type=ContractType.LINEAR),
            ),
            hedge_policy=HedgePolicy(kind=HedgePolicyKind.VEGA_NEUTRAL),
            sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=10_000.0),
        ),
    }
    for name, spec in specs.items():
        backend_rejections = {}
        for backend_name, backend in (("native_event", event), ("native_vectorized", vector)):
            try:
                backend.run_package_arbitrage(idx, spec, signal, closes)
                backend_rejections[backend_name] = {"rejected": False, "error": None}
            except NotImplementedError as exc:
                backend_rejections[backend_name] = {"rejected": True, "error": type(exc).__name__, "message": str(exc)}
        probes[name] = backend_rejections
    passed = all(
        all(route["rejected"] for route in backend_rejections.values())
        for backend_rejections in probes.values()
    )
    return {"status": "pass" if passed else "fail", "passed": passed, "probes": probes}


def _optional_nautilus_report(idx, spec, signal, closes, include_nautilus: bool) -> Dict:
    if not include_nautilus:
        return {"status": "skipped", "reason": "run with --include-nautilus"}
    try:
        from quantbt import QuantBTEndpoint
        from quantbt.adapters.nautilus import NautilusBackendConfig

        nt_symbols = ("BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE")
        nt_spec = BasisArbitrageSpec(
            arb_id="PHASE12_NAUTILUS_PACKAGE_SMOKE",
            legs=(
                ArbitrageLeg(nt_symbols[0], 1.0, role="perp", contract_type=ContractType.LINEAR),
                ArbitrageLeg(nt_symbols[1], -1.0, role="quarterly", contract_type=ContractType.LINEAR),
            ),
            hedge_policy=HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
            sizing_policy=SizingPolicy(
                kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
                notional=50_000.0,
                reference_symbol=nt_symbols[0],
            ),
            execution_policy=ArbExecutionPolicy(kind=PackageExecutionKind.ATOMIC_ALL_OR_NONE),
            metadata={"certification_note": "Nautilus supported-instrument package smoke; not a quarterly venue model."},
        )
        source_series = [closes["perpetual"], closes["quarterly"]]
        data = {
            symbol: pd.DataFrame(
                {
                    "open": close,
                    "close": close,
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "volume": 10_000.0,
                },
                index=idx,
            )
            for symbol, close in zip(nt_symbols, source_series)
        }
        endpoint = QuantBTEndpoint.arbitrage(
            arb_type="basis",
            spec=nt_spec,
            backend="nautilus",
            initial_capital=100_000.0,
            leverage=8.0,
            fee_rate=0.0002,
            use_funding=False,
            nautilus_config=NautilusBackendConfig(timeframe="1h", instrument_id=nt_symbols[0], bypass_risk=True),
        )
        result = endpoint.simulate(data=data, signal=signal, symbols=list(nt_symbols))
        return {"status": "pass", "orders": int(result.metadata.get("orders_count", 0)), "fills": int(result.metadata.get("fills_count", 0))}
    except Exception as exc:
        return {"status": "skipped", "reason": f"{type(exc).__name__}: {exc}"}


def _result_summary(event_result, vector_result, audit, parity):
    return {
        "event_final_equity": float(event_result.equity.iloc[-1]),
        "vectorized_final_equity": float(vector_result.equity.iloc[-1]),
        "order_count": int(len(event_result.metadata.get("order_report", []))),
        "fill_count": int(len(event_result.fills)),
        "fee_total": float(event_result.fees.sum()),
        "funding_total": float(event_result.funding.sum()),
        "audit": audit,
        "parity": parity,
    }


def _accounting_parity_passed(parity: Dict) -> bool:
    checks = parity.get("checks", {})
    return bool(
        checks.get("equity_matches")
        and checks.get("positions_match")
        and checks.get("target_units_match")
        and checks.get("package_residuals_ok")
    )


def _json_default(value):
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=900)
    parser.add_argument("--include-nautilus", action="store_true")
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase12_arbitrage_cert.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase12_arbitrage_cert.md")
    args = parser.parse_args(argv)
    report = run_certification(rows=args.rows, include_nautilus=args.include_nautilus)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8")
    args.md_out.write_text(make_markdown(report), encoding="utf-8")
    print(make_markdown(report))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
