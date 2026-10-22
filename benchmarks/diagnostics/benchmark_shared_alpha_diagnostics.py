"""Small matched cold-report workload, never a WFO or economic benchmark."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import resource
import statistics
import time

import numpy as np

from quantbt.diagnostics import (AccessPolicy, AccessWitness, AlphaDiagnostics,
    DiagnosticContext, DiagnosticObservation)


def run(repeats=5):
    context = DiagnosticContext("synthetic-v1", "synthetic-tape-v1", "synthetic-account-v1",
        "intrabar", (("quality", "synthetic_utility"), ("risk", "synthetic_risk")),
        "quality", "maximize", "fixed_panel", True, "synthetic_entries")
    access = AccessPolicy("benchmark", ("synthetic",), ("synthetic",), 101, "diagnostic")
    ranges = {"window": (1, 128), "threshold": (0.0, 1.0)}
    results = {}
    for outcome_blind in (False, True):
        ctx = replace(context, outcome_blind_roster=outcome_blind,
            generation_method="fixed_panel" if outcome_blind else "adaptive_search")
        owner = AlphaDiagnostics(ranges, context=ctx, access=access)
        rows = [DiagnosticObservation.from_params(geometry=owner.geometry,
            params=dict(window=i+1, threshold=i/128),
            metrics=dict(quality=float(i % 13), risk=-float(i % 11)),
            evaluation_id=f"synthetic-{i}", context_id=ctx.identity,
            witness=AccessWitness("synthetic", "synthetic", 0, 100, 101),
            source_ref="synthetic", activity_count=i) for i in range(128)]
        durations, sizes, ids = [], [], set()
        for _ in range(repeats):
            start = time.perf_counter()
            report = owner.analyze(rows)
            payload, markdown = report.to_json(), report.to_markdown()
            durations.append(time.perf_counter() - start)
            sizes.append(len(payload.encode()) + len(markdown.encode()))
            ids.add(report.identity)
        assert len(ids) == 1
        results["outcome_blind" if outcome_blind else "adaptive"] = dict(
            repeats=repeats, wall_seconds=durations, p50_ms=statistics.median(durations)*1000,
            p95_ms=float(np.quantile(durations, .95))*1000, maximum_output_bytes=max(sizes),
            report_identity=next(iter(ids)), financial_calls=0,
            bootstrap_resamples=64 if outcome_blind else 0)
    return dict(schema="quantbt.shared_diagnostics_benchmark.v1", results=results,
        peak_process_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        observations=128, numeric_axes=2, metrics=2, global_cache=False,
        imports_excluded=True, cold_report_assembly_each_repeat=True,
        limitations="Five serial report repeats; RSS includes imported package. No WFO/native/meta on-off speed claim.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
