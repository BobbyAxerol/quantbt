from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce
from quantbt.core.orders import OrderAction


def _bars(n: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    x = np.arange(n, dtype=np.float64)
    close = 100.0 + 0.002 * x + 2.0 * np.sin(x / 27.0) + 0.7 * np.sin(x / 7.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.25,
            "low": close - 1.25,
            "close": close,
            "volume": 10_000.0 + 100.0 * np.cos(x / 11.0),
        },
        index=idx,
    )


class ReactiveGridStrategy:
    def __init__(self, *, levels: int, reseed_every: int) -> None:
        self.levels = int(levels)
        self.reseed_every = int(reseed_every)
        self.cycle = 0

    def on_bar_close(self, context):
        commands = []
        if context.bar_index % self.reseed_every == 0:
            self.cycle += 1
            commands.append(
                OrderCommand(
                    timestamp=context.timestamp,
                    action=OrderAction.CANCEL_ALL,
                    symbol=context.symbols[0],
                    tag_prefix="GRID-",
                )
            )
            center = float(context.close[0])
            for level in range(1, self.levels + 1):
                commands.append(
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol=context.symbols[0],
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        qty=0.01,
                        price=center - 0.05 * level,
                        tif=TimeInForce.GTC,
                        order_id=f"grid-{self.cycle}-{level}",
                        tag=f"GRID-C{self.cycle}-L{level}",
                        metadata={"campaign_id": "GRID", "cycle_id": str(self.cycle), "level_id": str(level)},
                    )
                )
        if context.positions[context.symbols[0]] > 0.0 and context.bar_index % (self.reseed_every + 7) == 0:
            commands.append(
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=context.symbols[0],
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=abs(float(context.positions[context.symbols[0]])),
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id=f"flatten-{context.bar_index}",
                )
            )
        return commands


def run(*, bars: int, levels: int, reseed_every: int, out_dir: Path) -> dict:
    data = _bars(bars)
    strategy = ReactiveGridStrategy(levels=levels, reseed_every=reseed_every)
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=100_000, leverage=5, use_funding=False)

    t0 = time.perf_counter()
    reactive = endpoint.simulate(data=data, strategy=strategy, symbols=["BTC"])
    reactive_seconds = time.perf_counter() - t0

    t1 = time.perf_counter()
    replay = QuantBTEndpoint.native_event_lifecycle(initial_capital=100_000, leverage=5, use_funding=False).simulate(
        data=data,
        order_commands=reactive.metadata["emitted_command_tape"],
        symbols=["BTC"],
    )
    replay_seconds = time.perf_counter() - t1

    equity_diff = float(np.max(np.abs(reactive.equity.to_numpy() - replay.equity.to_numpy())))
    pos_diff = float(
        np.max(
            np.abs(
                reactive.positions["Position_BTC"].to_numpy()
                - replay.positions["Position_BTC"].to_numpy()
            )
        )
    )
    report = {
        "phase": "30E",
        "bars": int(bars),
        "levels": int(levels),
        "reseed_every": int(reseed_every),
        "emitted_commands": int(reactive.metadata["emitted_command_count"]),
        "fills": int(len(reactive.fills)),
        "reactive_seconds": reactive_seconds,
        "static_replay_seconds": replay_seconds,
        "total_seconds": reactive_seconds + replay_seconds,
        "equity_max_abs_diff": equity_diff,
        "position_max_abs_diff": pos_diff,
        "context_builder": reactive.metadata["reactive_context_builder"],
        "incremental_compile_replays": reactive.metadata["reactive_incremental_compile_replays"],
        "final_equity": float(reactive.equity.iloc[-1]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "phase30e_reactive_runner.json"
    md_path = out_dir / "phase30e_reactive_runner.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(
        "\n".join(
            [
                "# Phase 30E Reactive Runner Benchmark",
                "",
                f"- Bars: {bars:,}",
                f"- Grid levels: {levels}",
                f"- Emitted commands: {report['emitted_commands']:,}",
                f"- Fills: {report['fills']:,}",
                f"- Reactive runner seconds: {reactive_seconds:.6f}",
                f"- Static replay seconds: {replay_seconds:.6f}",
                f"- Max equity diff: {equity_diff:.12f}",
                f"- Max position diff: {pos_diff:.12f}",
                f"- Context builder: {report['context_builder']}",
                "",
                "Final accounting is still produced by one static native-event v2 replay.",
            ]
        ),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=25_000)
    parser.add_argument("--levels", type=int, default=20)
    parser.add_argument("--reseed-every", type=int, default=50)
    parser.add_argument("--out-dir", type=Path, default=Path("benchmarks/out"))
    args = parser.parse_args()
    print(json.dumps(run(bars=args.bars, levels=args.levels, reseed_every=args.reseed_every, out_dir=args.out_dir), indent=2))


if __name__ == "__main__":
    main()
