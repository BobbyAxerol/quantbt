"""Isolated numeric optimization candidate; installed native remains unchanged."""

import json
import subprocess
from time import perf_counter

from tools.build_qms04_candidate import ROOT, build, load_candidate

CANDIDATE = "0.4.3.dev3"
OUTPUT = ROOT / ".maturin/qms07"


def load(path):
    return load_candidate(path, candidate=CANDIDATE)


if __name__ == "__main__":
    started = perf_counter()
    extension, receipt = build(
        OUTPUT,
        candidate=CANDIDATE,
        features="qms-numeric-candidate,qms-prepared-witness-candidate",
    )
    receipt["build_wall_seconds"] = perf_counter() - started
    receipt["rustc"] = subprocess.check_output(
        ["rustc", "--version"], text=True
    ).strip()
    (OUTPUT / "build_receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    )
    print(receipt)
    print(f"QMS07_NATIVE_EXTENSION={extension}")
