"""Generate descriptive tables from retained artifacts, never run financial work."""

from hashlib import sha256
import json
import pstats

from tools.qms_pre05_workloads import ROOT
from tools.qms_pre05_benchmark import write_once


def main():
    lane = ROOT / ".maturin/qms08/pre-e06-05"
    cost_path = ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_05_cost.json"
    cost = json.loads(cost_path.read_text())
    rows = cost["rows"]
    lines = [
        "# PRE-E06-05 Generated Cost Tables",
        "",
        "Source: `qms_pre_e06_05_cost.json`; 21 paired warm samples/cell.",
        "Small synthetic source-level workload, not economic or installed/public certification.",
        "",
        "## Domain, Prepared And Nested Public Calls",
        "",
        "| Group/Route | Off p50 ms | Shadow p50 ms | Active Before/After ms | Active Change | Active/Off | Labels/Aux |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for off in (
        r
        for r in rows
        if r["mode"] == "off" and r["group"] in ("domain", "prepared", "nested")
    ):
        matched = {
            r["mode"]: r
            for r in rows
            if r["group"] == off["group"] and r["route"] == off["route"]
        }
        active, shadow = matched["active"], matched["shadow"]
        before, after = (active["p50_ms"][a] for a in ("reference", "optimized"))
        lines.append(
            f"| {off['group']}/{off['route']} | {off['p50_ms']['optimized']:.2f} | "
            f"{shadow['p50_ms']['optimized']:.2f} | {before:.2f} / {after:.2f} | "
            f"{active['p50_change_pct']:+.2f}% | {after / off['p50_ms']['optimized']:.3f}x | "
            f"{active['original_label_calls']}/{active['auxiliary_outer_is_calls']} |"
        )
    lines += [
        "",
        "On/off changes logical work; that ratio is cost, not a speedup comparison.",
        "W3 is prepared `backtest`, with constructor/history preparation recorded separately.",
        "",
        "## Disabled Point Budgets",
        "",
        "| Cell | Before/After p50 ms | p50 Change | Before/After p95 ms | p95 Change | Point Budget |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in (r for r in rows if r["mode"] == "off"):
        lines.append(
            f"| {r['cell']} | {r['p50_ms']['reference']:.2f} / {r['p50_ms']['optimized']:.2f} | "
            f"{r['p50_change_pct']:+.2f}% | {r['p95_ms']['reference']:.2f} / {r['p95_ms']['optimized']:.2f} | "
            f"{r['p95_change_pct']:+.2f}% | {r['disabled_point_budget']} |"
        )
    lines += [
        "",
        "Budgets +3% p50 / +5% p95 are unchanged. NOT_MET does not become PASS due to dispersion.",
        "",
        "## Instrumented Profiles",
        "",
        "| Cell/Arm | Instrumented ms | wire Calls/Cumulative ms | N/d/Origins/P |",
        "|---|---:|---:|---|",
    ]
    profiles = []
    for name in json.loads((lane / "isolated-profiles.json").read_text()):
        path = ROOT / name
        value = json.loads(path.read_text())
        stats = pstats.Stats(str(path.with_suffix(".pstats")))
        wire = [
            v
            for k, v in stats.stats.items()
            if "meta_selection/common.py" in k[0] and k[2] == "wire"
        ]
        calls, seconds = sum(v[1] for v in wire), sum(v[3] for v in wire)
        row = dict(
            file=name,
            source_sha256=sha256(path.read_bytes()).hexdigest(),
            wire_calls=calls,
            wire_cumulative_seconds=seconds,
            **value,
        )
        profiles.append(row)
        shapes = (
            ", ".join(
                f"{m['N']}/{m['d']}/{m['origins']}/{m['P']}"
                for m in value["model_shapes"]
            )
            or "N/A"
        )
        lines.append(
            f"| {path.stem} | {value['instrumented_wall_seconds'] * 1000:.2f} | "
            f"{calls}/{seconds * 1000:.2f} | {shapes} |"
        )
    lines += [
        "",
        "Profile spans are instrumented diagnostics, not latency gate samples.",
        "Full profiles preserve exclusive/inclusive components and observed backend/thread/FFI telemetry.",
        "",
        "## Memory",
        "",
        "| Cell | Worker Peak MiB | Warm Reference/Optimized Retained MiB | First-to-Last Drift MiB |",
        "|---|---:|---:|---:|",
    ]
    for r in rows:
        memory = r["warm_retained_rss_median_mib"]
        lines.append(
            f"| {r['cell']} | {r['worker_peak_rss_mib']:.3f} | "
            f"{memory['reference']:.3f}/{memory['optimized']:.3f} | {r['rss_delta_mib']:+.3f} |"
        )
    lines += [
        "",
        "Peak covers the whole shared worker/harness. Independent arm peaks are not certified.",
    ]
    target = ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_05_cost.md"
    with target.open("x") as f:
        f.write("\n".join(lines) + "\n")
    write_once(
        lane / "profile-summary.json", dict(profiles=profiles, economic_claim=False)
    )
    print(
        json.dumps(
            dict(generated=str(target.relative_to(ROOT)), profiles=len(profiles))
        )
    )


if __name__ == "__main__":
    main()
