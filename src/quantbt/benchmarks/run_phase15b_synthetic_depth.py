#!/usr/bin/env python3
"""
Phase 15B synthetic depth evidence runner.

This script creates deterministic OHLCV and synthetic-book depth cases. It is
not a venue L2 replay benchmark; it is an audit artifact for package-depth
invariants before optional Nautilus validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    NautilusExecutionDepthConfig,
    OrderIntent,
    OrderSide,
    OrderType,
    l2_replay_available,
    simulate_nautilus_order_package_depth,
)


def run_phase15b_synthetic_depth() -> Dict:
    data = {"BTCUSDT-PERP.BINANCE": _frame()}
    idx = data["BTCUSDT-PERP.BINANCE"].index
    cases = [
        (
            "synthetic_market_vwap",
            [
                OrderIntent(
                    timestamp=idx[1],
                    symbol="BTCUSDT-PERP.BINANCE",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=2.0,
                )
            ],
            NautilusExecutionDepthConfig(
                depth_model="synthetic_book",
                allow_partial_fills=True,
                synthetic_spread_bps=10.0,
                synthetic_level_spacing_bps=10.0,
                synthetic_levels=3,
                synthetic_base_depth_qty=1.0,
            ),
        ),
        (
            "synthetic_partial_queue",
            [
                OrderIntent(
                    timestamp=idx[1],
                    symbol="BTCUSDT-PERP.BINANCE",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=3.0,
                )
            ],
            NautilusExecutionDepthConfig(
                depth_model="synthetic_book",
                allow_partial_fills=True,
                synthetic_levels=2,
                synthetic_base_depth_qty=1.0,
                queue_ahead_qty=0.5,
            ),
        ),
        (
            "ohlcv_all_or_none_baseline",
            [
                OrderIntent(
                    timestamp=idx[1],
                    symbol="BTCUSDT-PERP.BINANCE",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    metadata={"package_id": "P1", "package_type": "basket_package"},
                )
            ],
            NautilusExecutionDepthConfig(all_or_none_packages=True),
        ),
    ]
    results: List[Dict] = []
    for name, orders, cfg in cases:
        preflight = simulate_nautilus_order_package_depth(orders, data, cfg)
        row = preflight.order_report.iloc[0].to_dict()
        results.append(
            {
                "case": name,
                "depth_model": cfg.depth_model,
                "status": str(row.get("status")),
                "filled_qty": float(row.get("filled_qty", 0.0)),
                "fill_price": float(row.get("fill_price", 0.0)),
                "levels_consumed": int(row.get("levels_consumed", 0)),
                "accepted_orders": int(preflight.metadata["accepted_orders"]),
                "rejected_orders": int(preflight.metadata["rejected_orders"]),
            }
        )
    return {
        "phase": "15B",
        "status": "pass" if all(item["status"] in {"filled", "partial"} for item in results) else "review",
        "l2_replay_available": bool(l2_replay_available()),
        "cases": results,
        "claim_scope": "Level-2 synthetic stress only; not venue L2 replay.",
    }


def make_markdown(report: Dict) -> str:
    lines = [
        "# Phase 15B Synthetic Depth Evidence",
        "",
        f"Status: **{report['status']}**",
        "",
        f"- L2 replay provider available: `{report['l2_replay_available']}`",
        f"- Claim scope: {report['claim_scope']}",
        "",
        "| case | depth model | status | filled qty | fill price | levels | accepted | rejected |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["cases"]:
        lines.append(
            "| `{case}` | `{depth_model}` | `{status}` | {filled_qty:.8f} | {fill_price:.8f} | {levels_consumed} | {accepted_orders} | {rejected_orders} |".format(
                **item
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Synthetic depth proves deterministic queue, participation, spread and level-consumption behavior. It does not certify real exchange queue priority. Real L2 certification remains gated by venue snapshots, incremental updates and trade prints.",
        ]
    )
    return "\n".join(lines) + "\n"


def _frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [101.0, 101.0, 101.0, 101.0],
            "low": [99.0, 99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 100.0, 100.0],
            "volume": [100.0, 100.0, 100.0, 100.0],
        },
        index=idx,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", default=str(PACKAGE_DIR / "benchmarks" / "phase15b_synthetic_depth.json"))
    parser.add_argument("--output-md", default=str(PACKAGE_DIR / "benchmarks" / "phase15b_synthetic_depth.md"))
    args = parser.parse_args()
    report = run_phase15b_synthetic_depth()
    json_path = Path(args.output_json)
    md_path = Path(args.output_md)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
