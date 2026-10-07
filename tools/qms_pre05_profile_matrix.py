"""Fixed paired instrumented diagnostics, run only after unprofiled timing."""

import json
import argparse
import subprocess
import sys

from tools.qms_pre05_workloads import ROOT, Cell, cells
from tools.qms_pre05_benchmark import write_once
from tools.qms_pre05_analysis import collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=("final", "isolated"), default="final")
    prefix = parser.parse_args().label
    lane = ROOT / ".maturin/qms08/pre-e06-05"
    if not (lane / "matched-v3-matrix.json").exists():
        raise ValueError("complete uninstrumented matrix before profile diagnostics")
    selected = [
        Cell("legacy", "signal_notional"),
        Cell("domain", "pct_equity"),
        Cell("domain", "pct_equity", "active"),
        Cell("domain", "intrabar", "active"),
        Cell("domain", "event_driven", "active"),
        Cell("domain", "reactive_reset", "active"),
        Cell("domain", "portfolio", "active"),
        Cell("nested", "pct_equity", "active", optimization="mode_1_decay"),
    ]
    missed = {
        r["cell"]
        for r in collect(lane, "matched-v3")["rows"]
        if r["disabled_point_budget"] == "NOT_MET"
    }
    selected.extend(c for c in cells() if c.identity in missed and c not in selected)
    outputs = []
    for cell in selected:
        index = cells().index(cell)
        for reference in (True, False):
            label = prefix + ("-reference" if reference else "-optimized")
            path = lane / "profiles" / (label + "-" + cell.identity + ".json")
            if path.exists():
                outputs.append(str(path.relative_to(ROOT)))
                continue
            command = [
                sys.executable,
                "-m",
                "tools.qms_pre05_benchmark",
                "profile",
                "--cell",
                str(index),
                "--label",
                label,
                "--warm",
            ]
            if reference:
                command.append("--reference")
            completed = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True
            )
            log = lane / "logs" / (label + "-" + cell.identity + ".log")
            with log.open("x") as f:
                f.write(completed.stdout + completed.stderr)
            if completed.returncode:
                raise RuntimeError("profile diagnostic failed: " + str(log))
            outputs.append(str(path.relative_to(ROOT)))
            value = json.loads(path.read_text())
            print(
                json.dumps(
                    dict(
                        cell=cell.identity,
                        arm=label,
                        instrumented_seconds=value["instrumented_wall_seconds"],
                    )
                ),
                flush=True,
            )
    write_once(lane / (prefix + "-profiles.json"), outputs)


if __name__ == "__main__":
    main()
