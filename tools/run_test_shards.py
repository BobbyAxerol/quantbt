#!/usr/bin/env python3
"""Run QuantBT tests in isolated pytest processes to bound peak RSS.

Numba, pandas, plotting, and optional backend imports retain memory for the
life of a pytest process. This release helper keeps test selection explicit but
starts a fresh interpreter after each bounded shard. It does not alter test
order inside a shard or production package behavior.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = PROJECT_ROOT / "tests"
REAL_DATA_TESTS = {"test_real.py", "test_real_endpoints.py"}
GRID_EXTERNAL_TESTS = {
    "test_phase47a_grid_adapter.py",
    "test_phase47c_grid_parity.py",
    "test_phase47d_grid_optimizer.py",
}


def _chunks(values: list[Path], size: int) -> Iterable[list[Path]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _collect(profile: str) -> list[list[Path]]:
    files = sorted(TEST_ROOT.rglob("test_*.py"))
    files = [path for path in files if path.name not in REAL_DATA_TESTS]
    if profile == "ci-core":
        files = [
            path
            for path in files
            if "native_event" not in path.parts and path.name not in GRID_EXTERNAL_TESTS
        ]
    elif profile == "native":
        files = [path for path in files if "native_event" in path.parts]
    elif profile != "release":  # pragma: no cover - argparse guards this
        raise ValueError(f"unsupported profile={profile!r}")

    grouped: dict[str, list[Path]] = {"core": [], "options": [], "native": []}
    for path in files:
        if "native_event" in path.parts:
            grouped["native"].append(path)
        elif "options" in path.parts:
            grouped["options"].append(path)
        else:
            grouped["core"].append(path)
    return [grouped[name] for name in ("core", "options", "native") if grouped[name]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("release", "ci-core", "native"), default="release")
    parser.add_argument("--max-files-per-shard", type=int, default=8)
    parser.add_argument("--list", action="store_true", help="print the commands without running pytest")
    args = parser.parse_args(argv)
    if args.max_files_per_shard <= 0:
        parser.error("--max-files-per-shard must be > 0")

    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp")
    shard_number = 0
    for group in _collect(args.profile):
        for shard in _chunks(group, args.max_files_per_shard):
            shard_number += 1
            command = [sys.executable, "-m", "pytest", "-q", *[str(path.relative_to(PROJECT_ROOT)) for path in shard]]
            print(f"[{shard_number}] {' '.join(command)}", flush=True)
            if args.list:
                continue
            completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
            if completed.returncode:
                return completed.returncode
    print(f"completed {shard_number} isolated pytest shard(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
