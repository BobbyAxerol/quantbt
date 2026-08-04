"""Phase 46B apples-to-apples scalar score and staged RSS benchmark.

Timing children execute exactly one backend.  A separate parity child performs
one audit certification before timing; it is intentionally outside the RSS and
latency measurements.  This prevents Python and Rust prepared ownership from
being mixed in a measured process.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from types import SimpleNamespace


PLATEAU_REPEATS = 100


def _rss_current_mb() -> float:
    statm = Path("/proc/self/statm")
    if statm.exists():
        pages = int(statm.read_text().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024.0 * 1024.0)
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _rss_hwm_mb() -> float:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmHWM:"):
                return float(line.split()[1]) / 1024.0
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _frame(rows: int):
    import numpy as np
    import pandas as pd

    index = pd.date_range("2024-01-01", periods=rows, freq="1min", tz="UTC")
    values = 100.0 + np.sin(np.arange(rows, dtype=np.float64) / 17.0) + np.arange(rows) * 0.0001
    close = pd.Series(values, index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def _commands(index, churn: str):
    from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce

    if churn == "low":
        bars = (index[100], index[len(index) // 2])
        return (
            OrderCommand(
                timestamp=bars[0],
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=0.1,
                tif=TimeInForce.GTC,
                order_id="entry",
            ),
            OrderCommand(
                timestamp=bars[1],
                symbol="BTC",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=0.1,
                tif=TimeInForce.GTC,
                reduce_only=True,
                order_id="exit",
            ),
        )

    commands = []
    for bar in range(10, len(index) - 2, 4):
        buy = bar % 8 == 2
        commands.append(
            OrderCommand(
                timestamp=index[bar],
                symbol="BTC",
                side=OrderSide.BUY if buy else OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=0.1,
                tif=TimeInForce.GTC,
                reduce_only=not buy,
                order_id=f"order-{bar}",
            )
        )
    return tuple(commands)


def _backend():
    from quantbt import AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig

    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=5.0, maintenance_ratio=0.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )


def _audit_common_fingerprint(result, *, rust: bool) -> str:
    import numpy as np

    if rust:
        fields = {
            "equity": result.equity,
            "positions": result.positions,
            "fees": result.fees,
            "turnover": result.turnover,
            "initial_margin": result.initial_margin,
            "maintenance_margin": result.maintenance_margin,
        }
    else:
        fields = {
            "equity": result.equity.to_numpy(dtype=np.float64),
            "positions": result.positions["Position_BTC"].to_numpy(dtype=np.float64),
            "fees": result.fees.to_numpy(dtype=np.float64),
            "turnover": result.diagnostics["turnover"].to_numpy(dtype=np.float64),
            "initial_margin": result.margin["initial_margin"].to_numpy(dtype=np.float64),
            "maintenance_margin": result.margin["maintenance_margin"].to_numpy(dtype=np.float64),
        }
    digest = hashlib.sha256()
    for name in sorted(fields):
        array = np.ascontiguousarray(fields[name], dtype=np.float64)
        digest.update(name.encode("utf-8"))
        digest.update(repr(array.shape).encode("utf-8"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _scalar_fingerprint(result) -> str:
    values = {
        "final_equity": float(result.final_equity),
        "final_position": float(result.final_position if hasattr(result, "final_position") else result.final_positions[0]),
        "total_fee": float(result.total_fee),
        "total_turnover": float(result.total_turnover),
        "fill_count": int(result.fill_count),
        "event_count": int(result.event_count),
        "rejected_count": int(result.rejected_count),
        "canceled_count": int(result.canceled_count),
        "max_initial_margin": float(result.max_initial_margin),
        "max_maintenance_margin": float(result.max_maintenance_margin),
    }
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rust_canonical_audit(result):
    """Adapt the Rust transport event enum to the Python semantic enum.

    The Rust ABI intentionally uses a compact transport mapping while the
    Python lifecycle ledger exposes ``core.event.ORDER_EVENT_*`` codes.  The
    parity certificate compares semantics, so the adapter is explicit and
    local to this benchmark rather than silently changing either backend.
    """
    import numpy as np

    rust_to_python_event = {
        0: 0,  # place
        1: 1,  # cancel
        2: 4,  # fill
        3: 7,  # reject
        4: 3,  # amend
        5: 2,  # replace
    }
    return SimpleNamespace(
        equity=result.equity,
        positions=result.positions,
        fees=result.fees,
        turnover=result.turnover,
        initial_margin=result.initial_margin,
        maintenance_margin=result.maintenance_margin,
        fill_bar=result.fill_bar,
        fill_order_id=result.fill_order_id,
        fill_side=result.fill_side,
        fill_qty=result.fill_qty,
        fill_price=result.fill_price,
        fill_fee=result.fill_fee,
        event_bar=result.event_bar,
        event_kind=np.asarray(
            [rust_to_python_event[int(value)] for value in result.event_kind],
            dtype=np.int64,
        ),
        event_status=result.event_status,
        event_order_id=result.event_order_id,
        event_target_id=result.event_target_id,
        liquidated=False,
        liquidation_bar=-1,
    )


def _child(*, backend_name: str, rows: int, repeats: int, churn: str) -> dict[str, object]:
    rss_interpreter = _rss_current_mb()
    import numpy as np

    backend = _backend()
    if backend_name == "rust":
        from quantbt import RustBatchedRunner

    rss_after_import_quantbt = _rss_current_mb()
    frame = _frame(rows)
    index = frame.index
    market = backend.prepare_market_arrays(
        datetime_index=index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    rss_after_market_prepare = _rss_current_mb()
    commands = _commands(index, churn)
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    rss_after_command_compile = _rss_current_mb()

    runner = None
    if backend_name == "rust":
        runner = RustBatchedRunner(
            idx=frame.index,
            symbols=["BTC"],
            market_arrays=market,
            contract_size=1.0,
            leverage=5.0,
            fee_rate=0.0002,
            initial_capital=50_000.0,
            maintenance_ratio=0.0,
            slippage=0.0002,
            use_funding=False,
        )
    rss_after_runner_prepare = _rss_current_mb()

    if backend_name in {"python", "rust"}:
        del frame
        gc.collect()
        rss_after_runner_prepare = _rss_current_mb()

    if backend_name == "python":
        def score_fn():
            return backend.run_compiled_tape_score(index, compiled, market_arrays=market)
    elif backend_name == "rust":
        def score_fn():
            return runner.run_tape_score(compiled)
    else:
        audit = backend.run_order_commands(
            datetime_index=frame.index,
            commands=commands,
            closes={"BTC": frame["close"]},
            highs={"BTC": frame["high"]},
            lows={"BTC": frame["low"]},
            symbols=["BTC"],
            market_arrays=market,
            compiled_commands=compiled,
            report_level="audit",
        )
        return {
            "backend": backend_name,
            "rows": int(rows),
            "churn": churn,
            "repeats": int(repeats),
            "median_seconds": 0.0,
            "mean_cpu_seconds": 0.0,
            "audit_accounting_fingerprint": _audit_common_fingerprint(audit, rust=False),
            "scalar_contract_fingerprint": None,
            "scalar": None,
            "rss_interpreter": float(rss_interpreter),
            "rss_after_import_quantbt": float(rss_after_import_quantbt),
            "rss_after_market_prepare": float(rss_after_market_prepare),
            "rss_after_command_compile": float(rss_after_command_compile),
            "rss_after_runner_prepare": float(rss_after_runner_prepare),
            "rss_after_score_warmup": float(rss_after_runner_prepare),
            "peak_rss_during_run": float(_rss_hwm_mb()),
            "rss_after_run": float(_rss_current_mb()),
            "import_baseline_rss": float(rss_after_import_quantbt - rss_interpreter),
            "prepared_incremental_rss": float(rss_after_runner_prepare - rss_after_import_quantbt),
            "incremental_prepared_rss": float(rss_after_runner_prepare - rss_after_import_quantbt),
            "execution_incremental_peak": 0.0,
            "incremental_execution_peak": 0.0,
            "rss_samples": [],
            "rss_plateau": False,
        }

    # Warmup is outside the repeated latency sample and establishes the
    # execution allocation baseline after market/tape preparation.
    final_scalar = score_fn()
    score_fingerprint = _scalar_fingerprint(final_scalar)
    rss_after_score_warmup = _rss_current_mb()
    peak_rss_during_run = max(_rss_hwm_mb(), rss_after_score_warmup)
    timings = []
    cpu_timings = []
    rss_samples = [rss_after_score_warmup]
    for _ in range(int(repeats)):
        start = time.perf_counter()
        cpu_start = time.process_time()
        final_scalar = score_fn()
        cpu_timings.append(time.process_time() - cpu_start)
        timings.append(time.perf_counter() - start)
        peak_rss_during_run = max(peak_rss_during_run, _rss_hwm_mb(), _rss_current_mb())
        rss_samples.append(_rss_current_mb())
    rss_after_run = _rss_current_mb()
    scalar_payload = {
        "final_equity": float(final_scalar.final_equity),
        "final_position": float(final_scalar.final_position if hasattr(final_scalar, "final_position") else final_scalar.final_positions[0]),
        "total_fee": float(final_scalar.total_fee),
        "total_turnover": float(final_scalar.total_turnover),
        "fill_count": int(final_scalar.fill_count),
        "event_count": int(final_scalar.event_count),
        "rejected_count": int(final_scalar.rejected_count),
        "canceled_count": int(final_scalar.canceled_count),
        "max_initial_margin": float(final_scalar.max_initial_margin),
        "max_maintenance_margin": float(final_scalar.max_maintenance_margin),
    }
    return {
        "backend": backend_name,
        "rows": int(rows),
        "churn": churn,
        "repeats": int(repeats),
        "median_seconds": float(np.median(np.asarray(timings, dtype=np.float64))),
        "mean_cpu_seconds": float(np.mean(np.asarray(cpu_timings, dtype=np.float64))),
        "audit_accounting_fingerprint": None,
        "scalar_contract_fingerprint": score_fingerprint,
        "scalar": scalar_payload,
        "rss_interpreter": float(rss_interpreter),
        "rss_after_import_quantbt": float(rss_after_import_quantbt),
        "rss_after_market_prepare": float(rss_after_market_prepare),
        "rss_after_command_compile": float(rss_after_command_compile),
        "rss_after_runner_prepare": float(rss_after_runner_prepare),
        "rss_after_score_warmup": float(rss_after_score_warmup),
        "peak_rss_during_run": float(peak_rss_during_run),
        "rss_after_run": float(rss_after_run),
        "import_baseline_rss": float(rss_after_import_quantbt - rss_interpreter),
        "prepared_incremental_rss": float(rss_after_runner_prepare - rss_after_import_quantbt),
        "incremental_prepared_rss": float(rss_after_runner_prepare - rss_after_import_quantbt),
        "execution_incremental_peak": float(peak_rss_during_run - rss_after_runner_prepare),
        "incremental_execution_peak": float(peak_rss_during_run - rss_after_runner_prepare),
        "rss_samples": [float(value) for value in rss_samples],
        "rss_plateau": bool(max(rss_samples) - min(rss_samples) <= 2.0),
    }


def _parity_child(*, rows: int, churn: str) -> dict[str, object]:
    """Certify Rust audit against a replay audit outside timing children."""
    import numpy as np
    from quantbt import RustBatchedRunner, assert_native_event_full_parity

    frame = _frame(rows)
    backend = _backend()
    market = backend.prepare_market_arrays(
        datetime_index=frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    commands = _commands(frame.index, churn)
    compiled = backend.compile_order_commands(frame.index, commands, symbols=["BTC"])
    replay = backend.run_order_commands(
        datetime_index=frame.index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        market_arrays=market,
        compiled_commands=compiled,
        report_level="audit",
    )
    runner = RustBatchedRunner(
        idx=frame.index,
        symbols=["BTC"],
        market_arrays=market,
        contract_size=1.0,
        leverage=5.0,
        fee_rate=0.0002,
        initial_capital=50_000.0,
        maintenance_ratio=0.0,
        slippage=0.0002,
        use_funding=False,
    )
    rust = runner.run_tape_audit(compiled)
    fill_ledger = replay.metadata["compact_fill_ledger"]
    event_ledger = replay.metadata["compact_order_event_ledger"]
    event_order_id = np.where(
        event_ledger.command_index >= 0,
        compiled.command_order_id[event_ledger.command_index],
        -1,
    )
    event_target_id = np.where(
        event_ledger.related_command_index >= 0,
        compiled.command_order_id[event_ledger.related_command_index],
        -1,
    )
    replay_arrays = SimpleNamespace(
        equity=replay.equity.to_numpy(dtype=np.float64),
        positions=replay.positions["Position_BTC"].to_numpy(dtype=np.float64),
        fees=replay.fees.to_numpy(dtype=np.float64),
        turnover=replay.diagnostics["turnover"].to_numpy(dtype=np.float64),
        initial_margin=replay.margin["initial_margin"].to_numpy(dtype=np.float64),
        maintenance_margin=replay.margin["maintenance_margin"].to_numpy(dtype=np.float64),
        fill_bar=fill_ledger.bar,
        fill_order_id=fill_ledger.order_id_code,
        fill_side=fill_ledger.side,
        fill_qty=fill_ledger.qty,
        fill_price=fill_ledger.price,
        fill_fee=fill_ledger.fee,
        event_bar=event_ledger.bar,
        event_kind=event_ledger.event_type,
        event_status=event_ledger.status,
        event_order_id=event_order_id,
        event_target_id=event_target_id,
    )
    certificate = assert_native_event_full_parity(
        _rust_canonical_audit(rust),
        replay_arrays,
        capabilities={"funding": False, "liquidation": False},
    )
    return {
        "full_parity_passed": bool(certificate["passed"]),
        "oracle_fingerprint": certificate["oracle_fingerprint"],
        "python_fingerprint": certificate["oracle_fingerprint"],
        "rust_fingerprint": certificate["candidate_fingerprint"],
        "compared_fields": certificate["compared_fields"],
        "python_audit_accounting_fingerprint": _audit_common_fingerprint(replay, rust=False),
        "rust_audit_accounting_fingerprint": _audit_common_fingerprint(rust, rust=True),
    }


def _run_child(backend_name: str, rows: int, repeats: int, churn: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            __file__,
            "--child",
            "--backend",
            backend_name,
            "--rows",
            str(rows),
            "--repeats",
            str(repeats),
            "--churn",
            churn,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _run_parity(rows: int, churn: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, __file__, "--parity", "--rows", str(rows), "--churn", churn],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--parity", action="store_true")
    parser.add_argument("--backend", choices=("python", "rust", "replay"), default="python")
    parser.add_argument("--rows", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--churn", choices=("low", "high"), default="low")
    parser.add_argument("--json-out", default="benchmarks/native_event/phase46b_score_rss.json")
    args = parser.parse_args()

    if args.child:
        print(json.dumps(_child(backend_name=args.backend, rows=args.rows, repeats=args.repeats, churn=args.churn), sort_keys=True))
        return
    if args.parity:
        print(json.dumps(_parity_child(rows=args.rows, churn=args.churn), sort_keys=True))
        return

    parity = {churn: _run_parity(args.rows, churn) for churn in ("low", "high")}
    runs = {}
    for churn in ("low", "high"):
        runs[churn] = {
            "python": _run_child("python", args.rows, args.repeats, churn),
            "rust": _run_child("rust", args.rows, args.repeats, churn),
            "replay": _run_child("replay", args.rows, 1, churn),
            "plateau_python": _run_child("python", args.rows, PLATEAU_REPEATS, churn),
            "plateau_rust": _run_child("rust", args.rows, PLATEAU_REPEATS, churn),
        }
    score_parity = {
        churn: {
            "passed": runs[churn]["python"]["scalar_contract_fingerprint"]
            == runs[churn]["rust"]["scalar_contract_fingerprint"],
            "python_fingerprint": runs[churn]["python"]["scalar_contract_fingerprint"],
            "rust_fingerprint": runs[churn]["rust"]["scalar_contract_fingerprint"],
        }
        for churn in ("low", "high")
    }
    full_parity_passed = all(bool(item["full_parity_passed"]) for item in parity.values()) and all(
        bool(item["passed"]) for item in score_parity.values()
    )
    payload = {
        "phase": "46B",
        "status": "passed" if full_parity_passed else "parity_failed",
        "full_parity_passed": full_parity_passed,
        "oracle_fingerprint": parity["low"]["oracle_fingerprint"],
        "python_fingerprint": parity["low"]["python_fingerprint"],
        "rust_fingerprint": parity["low"]["rust_fingerprint"],
        "parity": parity,
        "score_parity": score_parity,
        "runs": runs,
        "benchmark_contract": {
            "artifact": "scalar_tape_score",
            "timing_excludes_full_audit": True,
            "separate_backend_processes": True,
            "repetitions": int(args.repeats),
            "plateau_repetitions": PLATEAU_REPEATS,
            "rss_checkpoints": [
                "rss_interpreter",
                "rss_after_import_quantbt",
                "rss_after_market_prepare",
                "rss_after_command_compile",
                "rss_after_runner_prepare",
                "rss_after_score_warmup",
                "peak_rss_during_run",
                "rss_after_run",
            ],
        },
    }
    output = Path(args.json_out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
