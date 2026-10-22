"""Capture unchanged tracked production bytes before MET-01 qualification."""

from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs/metrics/evidence/met01/baseline.json"


def main():
    if OUTPUT.exists():
        raise FileExistsError("baseline is immutable; register a new lane for a new source")
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    protected = [p for p in paths if p.startswith(("src/quantbt/", "quantbt/", "rust/")) or p in {"pyproject.toml", "poetry.lock"}]
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in protected if (ROOT / p).is_file()}
    qs_root = Path(metadata.distribution("quantstats").locate_file("quantstats"))
    sources = {p: hashlib.sha256((qs_root / p).read_bytes()).hexdigest() for p in ("stats.py", "reports.py", "utils.py")}
    disk = shutil.disk_usage(ROOT)
    evidence = {
        "schema": "quantbt.metrics.baseline.v1", "phase": "MET-01",
        "parent_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT).decode().strip(),
        "protected_sources": hashes,
        "quantstats": {"version": metadata.version("quantstats"), "sources": sources},
        "disk_before": {"total_bytes": disk.total, "free_bytes": disk.free},
        "incremental_disk_budget_bytes": 64 * 1024 ** 2,
        "scratch_policy": "phase-owned /tmp pytest/matplotlib caches only",
        "scope": "spec/oracle only; no production reducers, raw accounting, scientific metrics or release changes",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps({"protected_files": len(hashes), "quantstats": evidence["quantstats"], "free_bytes": disk.free}))


if __name__ == "__main__":
    main()
