"""Compare exact native wheels without replacing the user's installed package."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=7)
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error("pairs must be positive")
    payload = {"schema": "quantbt-followup-native-metrics-v1", "wheels": {}, "pairs": []}
    with tempfile.TemporaryDirectory(prefix="quantbt-wheel-ab-") as directory:
        paths = {}
        for lane in ("before", "after"):
            wheel = getattr(args, lane).resolve()
            paths[lane] = Path(directory) / lane
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(paths[lane])
            payload["wheels"][lane] = {"filename": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
        for pair in range(args.pairs):
            rows = {}
            for lane in (("before", "after") if pair % 2 == 0 else ("after", "before")):
                code = (
                    "import sys,json;sys.path[:0]=sys.argv[1:];"
                    "from benchmarks.native_event.benchmark_phase66_rust_target_vectorized import run;"
                    "print(json.dumps(run(bars=20000,repeats=21)))"
                )
                process = subprocess.run(
                    [sys.executable, "-c", code, str(paths[lane]), str(ROOT / "src"), str(ROOT)],
                    cwd=ROOT, text=True, capture_output=True, check=True,
                )
                rows[lane] = json.loads(process.stdout)
                assert rows[lane]["evidence"]["exact_accounting_parity"]
            payload["pairs"].append(rows)
            print(f"pair {pair + 1}: both wheels passed accounting parity", flush=True)
    payload["prepared_medians_seconds"] = {
        lane: statistics.median(row[lane]["timings_seconds"]["rust_prepared_score"] for row in payload["pairs"])
        for lane in ("before", "after")
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["prepared_medians_seconds"], indent=2))


if __name__ == "__main__":
    main()
