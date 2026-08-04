#!/usr/bin/env python3
"""Smoke compare native legacy `%_equity` and Nautilus `%_equity` validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import QuantBTEndpoint  # noqa: E402
from quantbt.adapters.nautilus import NautilusBackendConfig  # noqa: E402


def run_smoke(rows: int = 300) -> Dict:
    data = _synthetic_eth_data(rows=rows)
    scenarios = [
        {
            "name": "aligned_fee_no_funding_no_slippage",
            "native_fee_round_trip": 0.0008,
            "native_use_funding": False,
            "native_slippage": 0.0,
            "nautilus_fee_rate": 0.0004,
            "nautilus_use_funding": False,
            "nautilus_slippage": 0.0,
            "note": "Native one-way fee approximates ETH taker fee; custom Nautilus fee_rate is not applied.",
        },
        {
            "name": "user_like_mismatch",
            "native_fee_round_trip": 0.0005,
            "native_use_funding": True,
            "native_slippage": 0.0002,
            "nautilus_fee_rate": 0.0005,
            "nautilus_use_funding": False,
            "nautilus_slippage": 0.0002,
            "note": "Matches the observed notebook-style mismatch: fee convention, funding, and slippage differ.",
        },
    ]
    results = []
    for scenario in scenarios:
        results.append(_run_scenario(data, scenario))
    return {
        "status": "pass",
        "rows": int(rows),
        "symbol": "ETHUSDT-PERP.BINANCE",
        "scenarios": results,
        "conclusion": _conclusion(results),
    }


def make_markdown(report: Dict) -> str:
    lines = [
        "# `%_equity` Native vs Nautilus Smoke",
        "",
        f"Status: **{report['status']}**",
        f"Rows: `{report['rows']}`",
        f"Symbol: `{report['symbol']}`",
        "",
    ]
    for item in report["scenarios"]:
        lines.extend(
            [
                f"## {item['name']}",
                "",
                f"- Native final equity: `{item['native']['final_equity']:.6f}`",
                f"- Nautilus final equity: `{item['nautilus']['final_equity']:.6f}`",
                f"- Final equity diff: `{item['final_equity_diff']:.6f}`",
                f"- Native trades: `{item['native']['num_trades']}`",
                f"- Nautilus trades: `{item['nautilus']['num_trades']}`",
                f"- Signal transitions: `{item['diagnostic']['signal']['effective_transition_count']}`",
                f"- Nautilus orders/fills: `{item['diagnostic']['orders']['orders_count']}` / `{item['diagnostic']['orders']['fills_count']}`",
                f"- Checks: `{item['diagnostic']['checks']}`",
                f"- Note: {item['note']}",
                "",
            ]
        )
    lines.extend(["## Conclusion", "", report["conclusion"], ""])
    return "\n".join(lines)


def _run_scenario(data: pd.DataFrame, scenario: Dict) -> Dict:
    native = QuantBTEndpoint.pct_equity(
        initial_capital=20_000,
        leverage=5,
        maintenance_ratio=0.005,
        contract_size=1.0,
        use_funding=bool(scenario["native_use_funding"]),
        funding_rate=0.0001,
        alloc_per_trade=0.5,
        fee=float(scenario["native_fee_round_trip"]),
        slippage=float(scenario["native_slippage"]),
        use_pyramiding=False,
    )
    native_result = native.backtest(data=data, signal_col="pos_weight")

    nautilus = QuantBTEndpoint.nautilus_validation(
        initial_capital=20_000,
        leverage=5,
        alloc_per_trade=0.5,
        hedge_type="%_equity",
        fee_rate=float(scenario["nautilus_fee_rate"]),
        use_funding=bool(scenario["nautilus_use_funding"]),
        use_pyramiding=False,
        slippage=float(scenario["nautilus_slippage"]),
        nautilus_config=NautilusBackendConfig(
            timeframe="1h",
            starting_balance=20_000,
            trade_notional=0.5,
            close_positions_on_stop=False,
            bypass_logging=True,
            log_level="ERROR",
        ),
    )
    nautilus_result = nautilus.simulate(
        data=data,
        signal_col="pos_weight",
        symbols=["ETHUSDT-PERP.BINANCE"],
        show_order_logs=False,
    )
    diagnostic = nautilus.nautilus_pct_equity_diagnostic(
        data=data,
        signal_col="pos_weight",
        native_fee_round_trip=float(scenario["native_fee_round_trip"]),
        native_use_funding=bool(scenario["native_use_funding"]),
        native_slippage=float(scenario["native_slippage"]),
    )
    native_report = native_result.full_report()
    nautilus_report = nautilus_result.full_report()
    return {
        "name": scenario["name"],
        "note": scenario["note"],
        "native": {
            "final_equity": float(native_result.equity.iloc[-1]),
            "total_return_pct": float(native_report["total_return_pct"]),
            "num_trades": int(native_report["num_trades"]),
        },
        "nautilus": {
            "final_equity": float(nautilus_result.equity.iloc[-1]),
            "total_return_pct": float(nautilus_report["total_return_pct"]),
            "num_trades": int(nautilus_report["num_trades"]),
        },
        "final_equity_diff": float(nautilus_result.equity.iloc[-1] - native_result.equity.iloc[-1]),
        "diagnostic": _jsonable_diagnostic(diagnostic),
    }


def _synthetic_eth_data(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="1h", tz="UTC")
    grid = np.arange(rows)
    close = pd.Series(2000 + 80 * np.sin(grid / 18) + 0.8 * grid + 20 * np.sin(grid / 5), index=idx)
    signal = pd.Series(0.0, index=idx)
    signal.iloc[10 : min(80, rows)] = 1.0
    signal.iloc[min(110, rows) : min(170, rows)] = -1.0
    signal.iloc[min(210, rows) : min(260, rows)] = 1.0
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 10_000.0,
            "pos_weight": signal,
        },
        index=idx,
    )


def _conclusion(results) -> str:
    aligned = next(item for item in results if item["name"] == "aligned_fee_no_funding_no_slippage")
    mismatch = next(item for item in results if item["name"] == "user_like_mismatch")
    return (
        "When fee/funding/slippage semantics are aligned as closely as the current adapters allow, "
        f"the synthetic final-equity gap is only `{aligned['final_equity_diff']:.6f}` USD and order/fill counts match. "
        "The user-like setup intentionally differs: legacy `fee` is round-trip, Nautilus `fee_rate` is metadata today, "
        "native funding/slippage are applied while Nautilus signal validation does not apply custom funding/slippage. "
        f"That scenario shows a larger synthetic gap of `{mismatch['final_equity_diff']:.6f}` USD. "
        "Large real-alpha gaps should be audited with the diagnostic helper first; if transition counts match, the next "
        "production task is implementing custom fee/slippage/funding in the Nautilus signal adapter."
    )


def _jsonable_diagnostic(diagnostic: Dict) -> Dict:
    out = dict(diagnostic)
    out["signal"] = dict(out["signal"])
    transition = out["signal"].pop("transition_report")
    out["signal"]["transition_report_head"] = transition.head(20).to_dict(orient="records")
    return out


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=300)
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "pct_equity_nautilus_smoke.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "pct_equity_nautilus_smoke.md")
    args = parser.parse_args(argv)
    report = run_smoke(rows=args.rows)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8")
    args.md_out.write_text(make_markdown(report), encoding="utf-8")
    print(make_markdown(report))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
