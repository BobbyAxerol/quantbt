from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict


PROJECT_ROOT = Path("/root/bobby/pool_alpha")
PACKAGE_ROOT = PROJECT_ROOT / "quantbt"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_real_df():
    """
    Execute only the data/signal construction part of test_real.py.

    The source file is notebook-style and runs a legacy analyze() at the end.
    For endpoint matrix testing we stop before the first quantbt import so this
    runner controls every backtest call explicitly.
    """
    source_path = PACKAGE_ROOT / "tests" / "test_real.py"
    source = source_path.read_text(encoding="utf-8")
    marker = "\n\n\nimport sys\nsys.path.append('/root/bobby/pool_alpha')\nfrom quantbt import BacktestEngine\n"
    if marker not in source:
        raise RuntimeError("test_real.py layout changed; marker not found")
    namespace: Dict = {"__name__": "__quantbt_real_signal_build__"}
    exec(compile(source.split(marker, 1)[0], str(source_path), "exec"), namespace)
    return namespace["df_result"]


def summarize_result(name: str, result) -> Dict:
    from quantbt.metrics import full_report

    rpt = full_report(result)
    summary = {
        "name": name,
        "backend": result.metadata.get("backend", "legacy"),
        "initial_capital": float(result.initial_capital),
        "final_equity": float(result.equity.iloc[-1]),
        "total_return_pct": float(rpt["total_return_pct"]),
        "sharpe": float(rpt["sharpe"]),
        "max_drawdown_pct": float(rpt["max_drawdown_pct"]),
        "trades": int(rpt["num_trades"]),
        "liquidated": bool(result.liquidated),
    }
    for key in ("orders_count", "fills_count", "positions_count"):
        if key in result.metadata:
            summary[key] = int(result.metadata[key])
    return summary


def run_legacy_pct_equity(df):
    from quantbt import BacktestEngine

    bt = BacktestEngine(
        Datetime=df.index,
        Position=df["pos_weight"],
        Close=df["close"],
        High=df["high"],
        Low=df["low"],
        fee=0.0004,
        use_pyramiding=False,
        initial_capital=20_000,
        leverage=5,
        maintenance_ratio=0.005,
        contract_size=1.0,
        use_funding_rate=True,
        funding_rate=0.0001,
        alloc_per_trade=0.5,
        hedge_type="%_equity",
        slippage=0.0001,
    )
    return summarize_result("legacy_pct_equity", bt.result)


def run_v2_vectorized_signal_notional(df):
    from quantbt import AccountConfig, BacktestEngineV2, ExecutionConfig

    engine = BacktestEngineV2(
        data=df[["open", "high", "low", "close", "volume"]],
        signals=df["pos_weight"],
        symbols=["ETHUSDT"],
        backend="native_vectorized",
        account=AccountConfig(initial_capital=20_000, leverage=5, maintenance_ratio=0.005),
        execution=ExecutionConfig(slippage_bps=1.0),
        fee_rate=0.0002,
        use_funding=True,
        funding_rate=0.0001,
        alloc_per_trade=10_000,
        hedge_type="signal_notional",
    )
    return summarize_result("v2_native_vectorized_signal_notional", engine.result)


def run_v2_event_signal_notional(df):
    from quantbt import AccountConfig, BacktestEngineV2, ExecutionConfig

    engine = BacktestEngineV2(
        data=df[["open", "high", "low", "close", "volume"]],
        signals=df["pos_weight"],
        symbols=["ETHUSDT"],
        backend="native_event",
        account=AccountConfig(initial_capital=20_000, leverage=5, maintenance_ratio=0.005),
        execution=ExecutionConfig(slippage_bps=1.0),
        fee_rate=0.0002,
        use_funding=True,
        funding_rate=0.0001,
        alloc_per_trade=10_000,
        hedge_type="signal_notional",
    )
    summary = summarize_result("v2_native_event_signal_notional", engine.result)
    summary["orders"] = len(engine.result.orders)
    summary["fills"] = len(engine.result.fills)
    return summary


def run_v2_basket_smoke(df):
    from quantbt import AccountConfig, BacktestEngineV2, BasketLegSpec, BasketSpec

    sample = df.iloc[:2_000].copy()
    signal = (sample["pos_weight"].fillna(0.0) != 0.0).astype(float)
    basket = BasketSpec(
        basket_id="ETH_BASKET_SMOKE",
        legs=(
            BasketLegSpec(symbol="ETHUSDT", ratio=1.0),
            BasketLegSpec(symbol="ETHHEDGE", ratio=-0.5),
        ),
        gross_notional=10_000,
    )
    closes = {
        "ETHUSDT": sample["close"],
        "ETHHEDGE": sample["close"] * 0.1,
    }
    engine = BacktestEngineV2(
        backend="native_event",
        basket=basket,
        signal=signal,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=sample.index,
        account=AccountConfig(initial_capital=50_000, leverage=5, maintenance_ratio=0.005),
        use_funding=False,
    )
    summary = summarize_result("v2_native_event_basket_smoke", engine.result)
    summary["fills"] = len(engine.result.fills)
    return summary


def run_nautilus_optional(df):
    try:
        from quantbt import AccountConfig, BacktestEngineV2
        from quantbt.adapters.nautilus import NautilusBacktestEngine

        NautilusBacktestEngine.check_available()
        sample = sample_with_transitions(df, min_transitions=20, max_rows=8_000)
        engine = BacktestEngineV2(
            data=sample[["open", "high", "low", "close", "volume"]],
            signals=sample["pos_weight"],
            symbols=["BTCUSDT-PERP.BINANCE"],
            backend="nautilus",
            account=AccountConfig(initial_capital=20_000, leverage=5, maintenance_ratio=0.005),
            alloc_per_trade=10_000,
            use_funding=False,
        )
        summary = summarize_result("nautilus_optional_signal_series", engine.result)
        summary["rows"] = int(len(sample))
        summary["pos_changes"] = int((sample["pos_weight"].fillna(0.0).diff().fillna(0.0) != 0.0).sum())
        return summary
    except ImportError as exc:
        return {"name": "nautilus_optional_signal_series", "status": "skipped", "reason": str(exc)}
    except Exception as exc:
        return {"name": "nautilus_optional_signal_series", "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}


def sample_with_transitions(df, min_transitions: int, max_rows: int):
    pos = df["pos_weight"].fillna(0.0)
    change_locs = list(pos.diff().fillna(0.0).ne(0.0).to_numpy().nonzero()[0])
    if not change_locs:
        return df.iloc[:max_rows].copy()
    start = max(0, change_locs[0] - 10)
    end = min(len(df), start + max_rows)
    for loc in change_locs:
        if loc <= start:
            continue
        if loc - start >= max_rows:
            break
        if sum(1 for x in change_locs if start <= x < loc) >= min_transitions:
            end = min(len(df), loc + 10)
            break
    return df.iloc[start:end].copy()


def main() -> int:
    df = load_real_df()
    summaries = [
        {
            "name": "source_custom_core",
            "backend": "custom_numba_signal_builder",
            "initial_capital": 10_000.0,
            "final_equity": float(df["equity"].iloc[-1]),
            "pos_changes": int((df["pos_weight"].fillna(0.0).diff().fillna(0.0) != 0.0).sum()),
            "rows": int(len(df)),
        },
        run_legacy_pct_equity(df),
        run_v2_vectorized_signal_notional(df),
        run_v2_event_signal_notional(df),
        run_v2_basket_smoke(df),
        run_nautilus_optional(df),
    ]
    print(json.dumps(summaries, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
