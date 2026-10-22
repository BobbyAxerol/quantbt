"""Public Mode-4 causal example using the existing SMA strategy demonstration.

Synthetic OHLCV and reduced support are engineering demonstrations, not edge.
Run: python -m examples.wfo_meta_selection --mode shadow --demo-support
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.common import wire
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory


PARAM_RANGES = {"window": (3, 31, 2)}


def strategy(data, params, train_index, test_index, fold):
    """Same public SMA rule as walk_forward_train_test; no private alpha."""
    window = int(params.get("window", 10))
    frame = data.loc[: test_index[-1]]
    signal = (frame["close"] > frame["close"].rolling(window).mean()).astype(float)
    return signal.reindex(test_index).fillna(0.0)


def market(bars=850):
    index = pd.date_range("2020-01-01", periods=bars, freq="1D", tz="UTC")
    t = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.025 * t + 3.0 * np.sin(t / 13.0) + np.cos(t / 5.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000.0 + t,
        },
        index=index,
    )


def make_endpoint(mode, *, observer=False, min_origins=12, policy="auto"):
    return QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optimization_config={
            "scoring_backend": "endpoint",
            "use_scalar_trial_scoring": False,
            "native_prepared_wfo": "off",
            "wfo_execution_reuse": "off",
            "top_is_fraction": 0.5,
            "flat_eps": 1.0,
            "flat_min_samples": 1,
            "is_subperiods": 3,
            "scoring_trading_days": 365,
            "min_trades_per_year": 100,
            "trade_penalty_factor": 0.5,
            "meta_selection": {
                "mode": mode,
                "min_matured_origins": min_origins,
                "native_batch_policy": policy,
                "label_observer": observer,
            },
        },
        optuna_trials=6,
        optuna_early_stopping=None,
        random_seed=731,
        initial_capital=20000.0,
        alloc_per_trade=1000.0,
        leverage=3.0,
        fee_rate=0.0005,
        use_funding=False,
        target_runtime="numba",
    )


def run_demo(mode="shadow", *, observer=True, min_origins=12, native_module=None):
    endpoint = make_endpoint(
        mode,
        observer=observer,
        min_origins=min_origins,
        policy="require" if native_module is not None else "auto",
    )
    history = MetaHistory(max_revisions=256)
    context = MetaHistoryContext(
        history=history,
        corpus_id="public-sma-demo",
        instrument_id="SYNTHETIC-USD-linear",
        timeframe="1D",
        run_id="qms05-demo",
        native_module=native_module,
    )
    runtime = {"meta_history": context} if mode != "off" else {}
    result = endpoint.backtest(data=market(), param_ranges=PARAM_RANGES, **runtime)
    return endpoint, result, context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("off", "shadow", "active"), default="shadow")
    parser.add_argument(
        "--demo-support",
        action="store_true",
        help="Override minimum origins to one for engineering smoke only",
    )
    parser.add_argument(
        "--extension",
        type=Path,
        help="Private QMS numeric candidate, not the financial backend",
    )
    args = parser.parse_args()
    native = None
    if args.extension:
        from tools.build_qms04_candidate import load_candidate

        native = load_candidate(args.extension)
    endpoint, result, _ = run_demo(
        args.mode,
        min_origins=1 if args.demo_support else 12,
        native_module=native,
    )
    wf = result.metadata["walk_forward"]
    print("Synthetic public SMA smoke; not economic acceptance or live deployment")
    print(wf["fold_table"].to_string(index=False))
    endpoint.show_metrics()
    if "meta_selection" in wf:
        fields = (
            "fold_id",
            "matured_origins",
            "final_selection_reason",
            "selected_params",
            "information_as_of",
            "ready_at",
            "effective_at",
            "past_matured_forward_used_for_selection",
        )
        print(
            json.dumps(
                wire(
                    [{k: r[k] for k in fields} for r in wf["meta_selection"]["records"]]
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
