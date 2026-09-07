"""Isolated public callback benchmark: tag, frozen projection, current projection.

The reference lane runs today's execution code with the pre-change audit
builders. It must have identical complete accounting/trace output. The optional
tag lane measures the actual checkout, not the Phase 43A JSON saved in that tag.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "100k_low_orders": (100_000, 8000, 20, False, False),
    "100k_high_churn": (100_000, 200, 20, False, False),
    "parent_oco_heavy": (25_000, 80, 16, True, False),
    "gtd_heavy": (25_000, 120, 12, False, True),
    "prepared_100_scores": (5000, 500, 20, False, False),
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def child(args):
    source = args.source.resolve()
    sys.path.insert(0, str(source / "src"))
    os.environ["QUANTBT_NATIVE_BACKEND"] = "python"
    import quantbt
    import numpy as np
    import pandas as pd

    fixture = load_module("reactive_fixture", source / "benchmarks/native_event/benchmark_reactive_session.py")
    if args.lane == "reference":
        from quantbt.core import execution_trace, accounting_contracts
        oracle = load_module("trace_oracle", ROOT / "tests/fixtures/canonical_trace_pre_optimization.py")
        ledger = load_module("ledger_oracle", ROOT / "tests/fixtures/accounting_pre_optimization.py")
        execution_trace.build_canonical_execution_trace = oracle.build_canonical_execution_trace
        accounting_contracts.build_native_accounting_audit = ledger.build_native_accounting_audit

    captured = []
    original = fixture.QuantBTEndpoint.simulate

    def simulate(endpoint, *a, **kw):
        result = original(endpoint, *a, **kw)
        captured.append(result)
        return result

    fixture.QuantBTEndpoint.simulate = simulate
    n, every, hold, bracket, gtd = CASES[args.case]
    score = args.case == "prepared_100_scores"
    result = fixture._run_case(
        args.case, n, fixture.PeriodicStrategy(every=every, hold=hold, bracket=bracket, gtd=gtd),
        repeats=100 if score else 1, prepared_score=score,
    )
    # Hashes are outside measured time and sampled RSS. Benchmark retention
    # matches the public result, including every requested audit artifact.
    if captured:
        public = captured[0]
        digest = hashlib.sha256()
        for name in ("equity", "returns", "positions", "fees", "funding", "margin"):
            value = getattr(public, name)
            digest.update(name.encode())
            digest.update(np.asarray(value, dtype="<f8").tobytes())
            digest.update(value.index.asi8.tobytes())
        result["accounting_hash"] = digest.hexdigest()
        metadata = public.metadata
        result["trace_hash"] = metadata.get("canonical_trace_fingerprint")
        result["trace_rows"] = metadata.get("canonical_trace_row_count")
        result["trace_replay"] = metadata.get("canonical_trace_replay_v1")
        ledger_digest = hashlib.sha256()
        for name in ("accounting_ledger_v1", "symbol_accounting_ledger_v1", "liquidation_attribution_v1"):
            frame = metadata.get(name)
            if isinstance(frame, pd.DataFrame):
                ledger_digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
        result["ledger_hash"] = ledger_digest.hexdigest()
    result.update(lane=args.lane, import_file=quantbt.__file__, python=sys.version,
                  numpy=np.__version__, pandas=pd.__version__)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--lane", default="current")
    parser.add_argument("--case", choices=CASES, default="100k_low_orders")
    parser.add_argument("--tag-source", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    lanes = [("reference", ROOT), ("current", ROOT)]
    if args.tag_source:
        lanes.insert(0, ("v1.1.0", args.tag_source))
    rows = []
    for case in args.cases:
        for repeat in range(args.repeats):
            for lane, source in lanes:
                completed = subprocess.run([
                    sys.executable, str(Path(__file__).resolve()), "--child", "--source", str(source),
                    "--lane", lane, "--case", case, "--output", str(args.output),
                ], check=True, capture_output=True, text=True, cwd="/tmp")
                row = json.loads(completed.stdout.strip().splitlines()[-1])
                row["repeat"] = repeat
                rows.append(row)
                print(f"{case} {lane}: {row['wall_seconds']:.3f}s, {row['peak_rss_mb']:.1f} MiB", flush=True)
    for case in args.cases:
        records = [row for row in rows if row["name"] == case]
        for key in ("final_equity", "fill_count", "command_count", "event_count", "accounting_hash"):
            values = [row.get(key) for row in records]
            if len(set(values)) != 1:
                raise AssertionError((case, key, values))
        for key in ("trace_hash", "ledger_hash", "trace_rows", "trace_replay"):
            values = [json.dumps(row.get(key), sort_keys=True) for row in records if row["lane"] != "v1.1.0"]
            if len(set(values)) != 1:
                raise AssertionError((case, key, values))
    summary = []
    for case in args.cases:
        for lane, _ in lanes:
            selected = [row for row in rows if row["name"] == case and row["lane"] == lane]
            wall = statistics.median(row["wall_seconds"] for row in selected)
            summary.append({
                "case": case, "lane": lane, "median_seconds": wall,
                "bars_per_second": CASES[case][0] * (100 if case == "prepared_100_scores" else 1) / wall,
                "median_peak_rss_mib": statistics.median(row["peak_rss_mb"] for row in selected),
                "median_retained_rss_mib": statistics.median(row["post_run_rss_mb"] for row in selected),
            })
    payload = {
        "schema": "generic-callback-audit-closure-v1", "parity": "pass", "rows": rows, "summary": summary,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_files_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in [ROOT / "src/quantbt/core/execution_trace.py",
                                             ROOT / "src/quantbt/core/_trace_columns.py",
                                             ROOT / "src/quantbt/core/accounting_contracts.py"]},
        "measurement": "Isolated subprocess per sample; fixture excludes data construction; no Rust rebuild needed.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
