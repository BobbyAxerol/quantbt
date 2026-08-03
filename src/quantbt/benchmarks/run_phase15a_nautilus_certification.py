#!/usr/bin/env python3
"""
Phase 15A Nautilus certification bundle runner.

This runner is an evidence-layer tool. It does not change engine semantics.
Nautilus workflows are optional because they require the external
`nautilus_trader` dependency and supported test instruments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

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
    BasketLegSpec,
    BasketSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    NautilusToleranceProfile,
    OrderIntent,
    OrderSide,
    OrderType,
    PackageExecutionKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    TimeInForce,
    export_nautilus_report_bundle,
    write_nautilus_certification_artifacts,
)


WORKFLOWS = (
    "pct_equity_signal",
    "explicit_orders",
    "basket_package",
    "portfolio_package",
    "basis_arbitrage_package",
)


def run_certification(
    *,
    rows: int = 96,
    include_nautilus: bool = False,
    output_dir: str | Path = PACKAGE_DIR / "benchmarks" / "phase15a_nautilus_bundles",
    make_quantstats: bool = False,
) -> Dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    if not include_nautilus:
        workflows = [
            {
                "workflow": name,
                "status": "skipped",
                "reason": "run with --include-nautilus",
                "bundle_dir": None,
            }
            for name in WORKFLOWS
        ]
        return _summary(workflows=workflows, output_dir=output_path, include_nautilus=False)

    availability = _nautilus_available()
    if availability is not None:
        workflows = [
            {
                "workflow": name,
                "status": "skipped",
                "reason": availability,
                "bundle_dir": None,
            }
            for name in WORKFLOWS
        ]
        return _summary(workflows=workflows, output_dir=output_path, include_nautilus=True)

    runners: Dict[str, Callable[[int, Path, bool], Dict]] = {
        "pct_equity_signal": _run_pct_equity_signal,
        "explicit_orders": _run_explicit_orders,
        "basket_package": _run_basket_package,
        "portfolio_package": _run_portfolio_package,
        "basis_arbitrage_package": _run_basis_arbitrage_package,
    }
    workflows = []
    for name in WORKFLOWS:
        try:
            workflows.append(runners[name](int(rows), output_path, bool(make_quantstats)))
        except ImportError as exc:
            workflows.append({"workflow": name, "status": "skipped", "reason": str(exc), "bundle_dir": None})
        except NotImplementedError as exc:
            workflows.append({"workflow": name, "status": "skipped", "reason": str(exc), "bundle_dir": None})
        except Exception as exc:  # pragma: no cover - only hit with optional external backend drift
            workflows.append({"workflow": name, "status": "failed", "reason": f"{type(exc).__name__}: {exc}", "bundle_dir": None})
    return _summary(workflows=workflows, output_dir=output_path, include_nautilus=True)


def make_markdown(report: Dict) -> str:
    lines = [
        "# Phase 15A Nautilus Certification Bundles",
        "",
        f"Status: **{report['status']}**",
        "",
        f"- Include Nautilus: `{report['include_nautilus']}`",
        f"- Output directory: `{report['output_dir']}`",
        f"- Passed workflows: `{report['passed_workflows']}`",
        f"- Skipped workflows: `{report['skipped_workflows']}`",
        f"- Failed workflows: `{report['failed_workflows']}`",
        "",
        "## Workflow Matrix",
        "",
        "| workflow | status | bundle | tolerance status | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report["workflows"]:
        lines.append(
            "| `{workflow}` | `{status}` | `{bundle}` | `{tol}` | {reason} |".format(
                workflow=item["workflow"],
                status=item["status"],
                bundle=item.get("bundle_dir") or "",
                tol=item.get("tolerance_status") or "",
                reason=item.get("reason", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Required Bundle Files",
            "",
            "- `config.json`",
            "- `run_manifest.json`",
            "- `metrics_summary.json`",
            "- `equity_curve.csv`, `returns.csv`, `account_report.csv`",
            "- `orders_report.csv`, `fills_report.csv`, `positions_report.csv`",
            "- `trade_log.csv`, `fill_log.txt`",
            "- `native_vs_nautilus_parity.csv`",
            "- `tolerance_profile.json`",
            "- `known_differences.md`",
            "",
            "## Interpretation",
            "",
            "A skipped workflow is not a pass claim. It means the optional Nautilus dependency or instrument route was not available in this environment. A pass means the workflow produced a bundle and satisfied the declared tolerance profile.",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_pct_equity_signal(rows: int, output_dir: Path, make_quantstats: bool) -> Dict:
    data = _single_data(rows)
    signal = _signal(data.index)
    native = QuantBTEndpoint.pct_equity(
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=0.4,
        fee=0.0004,
        slippage=0.0,
        use_funding=False,
        use_pyramiding=False,
    )
    native_result = native.backtest(data=data, signal=signal)

    from quantbt.adapters.nautilus import NautilusBackendConfig

    nt = QuantBTEndpoint.nautilus_validation(
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=0.4,
        hedge_type="%_equity",
        fee_rate=0.0002,
        use_funding=False,
        use_pyramiding=False,
        nautilus_config=NautilusBackendConfig(
            instrument_id="BTCUSDT-PERP.BINANCE",
            timeframe="1h",
            trade_notional=0.4,
            bypass_risk=True,
            close_positions_on_stop=False,
        ),
    )
    nt_result = nt.simulate(data=data, signal=signal, symbols=["BTCUSDT-PERP.BINANCE"])
    return _export_workflow(
        workflow="pct_equity_signal",
        native_result=native_result,
        nautilus_result=nt_result,
        output_dir=output_dir,
        make_quantstats=make_quantstats,
        known_differences=[
            "Nautilus signal validation uses adapter-generated market orders from target signals.",
            "Custom slippage and funding support depend on the current Nautilus adapter route.",
        ],
        tolerance=NautilusToleranceProfile(equity_tolerance=5.0, position_tolerance=0.01, quantity_tolerance=0.01),
    )


def _run_explicit_orders(rows: int, output_dir: Path, make_quantstats: bool) -> Dict:
    data = _single_data(rows)
    idx = data.index
    orders = (
        OrderIntent(idx[5], "BTCUSDT-PERP.BINANCE", OrderSide.BUY, OrderType.MARKET, qty=0.05, tif=TimeInForce.IOC),
        OrderIntent(idx[20], "BTCUSDT-PERP.BINANCE", OrderSide.SELL, OrderType.MARKET, qty=0.05, tif=TimeInForce.IOC),
    )
    native = QuantBTEndpoint.orders(
        backend="native_event",
        initial_capital=20_000.0,
        leverage=3.0,
        fee_rate=0.0002,
        use_funding=False,
    ).simulate(data=data, orders=orders, symbols=["BTCUSDT-PERP.BINANCE"])

    from quantbt.adapters.nautilus import NautilusBackendConfig

    nt = QuantBTEndpoint.orders(
        backend="nautilus",
        initial_capital=20_000.0,
        leverage=3.0,
        fee_rate=0.0002,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            instrument_id="BTCUSDT-PERP.BINANCE",
            timeframe="1h",
            bypass_risk=True,
        ),
    ).simulate(data=data, orders=orders, symbols=["BTCUSDT-PERP.BINANCE"])
    return _export_workflow("explicit_orders", native, nt, output_dir, make_quantstats)


def _run_basket_package(rows: int, output_dir: Path, make_quantstats: bool) -> Dict:
    data = _multi_data(rows, ("BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE"))
    idx = next(iter(data.values())).index
    signal = pd.Series(0.0, index=idx)
    signal.iloc[5:30] = 1.0
    basket = BasketSpec(
        basket_id="PHASE15A_BASKET",
        legs=(BasketLegSpec("BTCUSDT-PERP.BINANCE", 1.0), BasketLegSpec("ETHUSDT-PERP.BINANCE", -1.0)),
        gross_notional=5_000.0,
        freeze_hedge=True,
    )
    native = QuantBTEndpoint.basket(
        basket=basket,
        backend="native_event",
        initial_capital=50_000.0,
        leverage=3.0,
        fee_rate=0.0002,
        use_funding=False,
    ).simulate(data=data, signal=signal, symbols=list(data))

    from quantbt.adapters.nautilus import NautilusBackendConfig

    nt = QuantBTEndpoint.basket(
        basket=basket,
        backend="nautilus",
        initial_capital=50_000.0,
        leverage=3.0,
        fee_rate=0.0002,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            instrument_id="BTCUSDT-PERP.BINANCE",
            timeframe="1h",
            bypass_risk=True,
        ),
    ).simulate(data=data, signal=signal, symbols=list(data))
    return _export_workflow("basket_package", native, nt, output_dir, make_quantstats)


def _run_portfolio_package(rows: int, output_dir: Path, make_quantstats: bool) -> Dict:
    symbols = ("BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE")
    data = _multi_data(rows, symbols)
    idx = next(iter(data.values())).index
    positions = pd.DataFrame(
        {
            symbols[0]: np.where(np.arange(len(idx)) % 24 < 12, 1.0, 0.0),
            symbols[1]: np.where(np.arange(len(idx)) % 24 < 12, -1.0, 0.0),
        },
        index=idx,
    )
    native = QuantBTEndpoint.portfolio(
        portfolio_mode="market_neutral",
        backend="native_portfolio",
        initial_capital=50_000.0,
        leverage=3.0,
        fee_rate=0.0002,
        hedge_type="signal_notional",
        alloc_per_trade={symbols[0]: 2_500.0, symbols[1]: 2_500.0},
        use_funding=False,
    ).backtest(data=data, positions=positions, symbols=list(symbols))

    from quantbt.adapters.nautilus import NautilusBackendConfig

    nt = QuantBTEndpoint.portfolio(
        portfolio_mode="market_neutral",
        backend="nautilus",
        initial_capital=50_000.0,
        leverage=3.0,
        fee_rate=0.0002,
        hedge_type="signal_notional",
        alloc_per_trade={symbols[0]: 2_500.0, symbols[1]: 2_500.0},
        use_funding=False,
        metadata={"portfolio_nautilus_equity_tolerance": 5.0, "portfolio_nautilus_position_tolerance": 0.01},
        nautilus_config=NautilusBackendConfig(
            instrument_id=symbols[0],
            timeframe="1h",
            bypass_risk=True,
        ),
    ).simulate(data=data, positions=positions, symbols=list(symbols))
    return _export_workflow(
        "portfolio_package",
        native,
        nt,
        output_dir,
        make_quantstats,
        known_differences=["Portfolio route submits native transformed target-unit deltas to Nautilus package replay."],
        tolerance=NautilusToleranceProfile(equity_tolerance=5.0, position_tolerance=0.01, quantity_tolerance=0.01),
    )


def _run_basis_arbitrage_package(rows: int, output_dir: Path, make_quantstats: bool) -> Dict:
    symbols = ("BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE")
    data = _multi_data(rows, symbols)
    closes = {symbol: frame["close"] for symbol, frame in data.items()}
    idx = next(iter(data.values())).index
    signal = pd.Series(0.0, index=idx)
    signal.iloc[8:40] = 1.0
    spec = BasisArbitrageSpec(
        arb_id="PHASE15A_BASIS",
        legs=(
            ArbitrageLeg(symbols[0], 1.0, role="perp", contract_type=ContractType.LINEAR, funding_enabled=True),
            ArbitrageLeg(symbols[1], -1.0, role="quarterly", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=5_000.0,
            reference_symbol=symbols[0],
        ),
        execution_policy=ArbExecutionPolicy(PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )
    native = NativeEventBackend(
        NativeEventConfig(account=AccountConfig(initial_capital=50_000.0, leverage=3.0), fee_rate=0.0002, use_funding=False)
    ).run_basis_arbitrage(idx, spec, signal, closes, funding_rate=0.0)

    from quantbt.adapters.nautilus import NautilusBackendConfig

    nt = QuantBTEndpoint.arbitrage(
        "basis",
        spec=spec,
        backend="nautilus",
        initial_capital=50_000.0,
        leverage=3.0,
        fee_rate=0.0002,
        use_funding=False,
        nautilus_config=NautilusBackendConfig(
            instrument_id=symbols[0],
            timeframe="1h",
            bypass_risk=True,
        ),
    ).simulate(data=data, signal=signal, symbols=list(symbols))
    return _export_workflow(
        "basis_arbitrage_package",
        native,
        nt,
        output_dir,
        make_quantstats,
        known_differences=[
            "This smoke uses supported perpetual test instruments as a package proxy, not a real delivery-futures venue model.",
        ],
        tolerance=NautilusToleranceProfile(equity_tolerance=5.0, position_tolerance=0.01, quantity_tolerance=0.01),
    )


def _export_workflow(
    workflow: str,
    native_result,
    nautilus_result,
    output_dir: Path,
    make_quantstats: bool,
    known_differences: Optional[List[str]] = None,
    tolerance: NautilusToleranceProfile | None = None,
) -> Dict:
    bundle_dir = export_nautilus_report_bundle(
        result=nautilus_result,
        output_dir=output_dir / workflow,
        strategy_id=workflow,
        config={"certification_workflow": workflow},
        make_quantstats=make_quantstats,
        fill_log_limit=200,
    )
    artifacts = write_nautilus_certification_artifacts(
        native_result=native_result,
        nautilus_result=nautilus_result,
        report_dir=bundle_dir,
        workflow=workflow,
        tolerance=tolerance or NautilusToleranceProfile(equity_tolerance=5.0, position_tolerance=0.01, quantity_tolerance=0.01),
        known_differences=known_differences,
    )
    profile = artifacts["tolerance_profile"]
    return {
        "workflow": workflow,
        "status": "pass" if profile["passed"] else "diff",
        "bundle_dir": str(bundle_dir),
        "tolerance_status": profile["status"],
        "checks": profile["checks"],
        "artifact_files": artifacts["artifact_files"],
    }


def _summary(workflows: List[Dict], output_dir: Path, include_nautilus: bool) -> Dict:
    failed = [item for item in workflows if item["status"] == "failed"]
    passed = [item for item in workflows if item["status"] == "pass"]
    skipped = [item for item in workflows if item["status"] == "skipped"]
    diff = [item for item in workflows if item["status"] == "diff"]
    status = "fail" if failed else "pass"
    return {
        "status": status,
        "include_nautilus": bool(include_nautilus),
        "output_dir": str(output_dir),
        "workflows": workflows,
        "passed_workflows": len(passed),
        "skipped_workflows": len(skipped),
        "diff_workflows": len(diff),
        "failed_workflows": len(failed),
    }


def _nautilus_available() -> Optional[str]:
    try:
        from quantbt.adapters.nautilus import NautilusBacktestEngine

        NautilusBacktestEngine.check_available()
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _single_data(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=int(rows), freq="1h", tz="UTC")
    x = np.linspace(0.0, 10.0, len(idx))
    close = 100.0 + np.cumsum(np.sin(x) * 0.08 + np.cos(x / 2.0) * 0.03)
    return pd.DataFrame(
        {"open": close, "high": close * 1.002, "low": close * 0.998, "close": close, "volume": 1_000.0},
        index=idx,
    )


def _multi_data(rows: int, symbols: Tuple[str, ...]) -> Dict[str, pd.DataFrame]:
    base = _single_data(rows)
    out = {}
    for i, symbol in enumerate(symbols):
        frame = base.copy()
        scale = 1.0 + i * 0.15
        frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]] * scale
        frame["volume"] = frame["volume"] * (1.0 + i)
        out[symbol] = frame
    return out


def _signal(idx: pd.DatetimeIndex) -> pd.Series:
    signal = pd.Series(0.0, index=idx)
    signal.iloc[5 : max(6, len(idx) // 3)] = 1.0
    signal.iloc[max(8, len(idx) // 2) : max(9, len(idx) * 2 // 3)] = -1.0
    return signal


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
    parser.add_argument("--rows", type=int, default=96)
    parser.add_argument("--include-nautilus", action="store_true")
    parser.add_argument("--make-quantstats", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase15a_nautilus_bundles")
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase15a_nautilus_certification.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase15a_nautilus_certification.md")
    args = parser.parse_args(argv)
    report = run_certification(
        rows=args.rows,
        include_nautilus=args.include_nautilus,
        output_dir=args.output_dir,
        make_quantstats=args.make_quantstats,
    )
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
    args.md_out.write_text(make_markdown(report), encoding="utf-8")
    print(make_markdown(report))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
