"""Before/after native execution identities for the approved metadata-only repair."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import optuna

from tools.qms_c01_audit import native_identity, run_trace
from tools.qms01_baseline import ROUTES, GUIDE, ROOT


def snapshot():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    lanes = []
    for mode, schedule in ROUTES:
        payload, result, _engine, rng = run_trace(mode, schedule)
        off, off_result, _engine, off_rng = run_trace(mode, schedule, explicit_off=True)
        import numpy as np

        assert native_identity(payload) == native_identity(off)
        assert rng == off_rng
        np.testing.assert_array_equal(result.returns, off_result.returns)
        lanes.append(dict(mode=mode, schedule=schedule, identity=native_identity(payload),
                          rng=rng, off_exact=True,
                          oos_used_for_selection=payload["summary"]["oos_used_for_selection"]))
    historical = sorted((ROOT / "benchmarks/optimization/meta_selection").glob("*.json"))
    return dict(schema="qms-e01-native-identity-v1", lanes=lanes,
        source_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        walkforward_sha256=sha256((ROOT / "src/quantbt/walkforward.py").read_bytes()).hexdigest(),
        guide_sha256=sha256((ROOT / GUIDE).read_bytes()).hexdigest(),
        historical_receipts={str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in historical},
        publication=False, economic_claim=False)


def compare(before, after):
    assert before["guide_sha256"] == after["guide_sha256"]
    for name, digest in before["historical_receipts"].items():
        assert after["historical_receipts"].get(name) == digest, name
    assert len(before["lanes"]) == len(after["lanes"]) == len(ROUTES)
    for old, new in zip(before["lanes"], after["lanes"], strict=True):
        assert {k: v for k, v in old.items() if k != "oos_used_for_selection"} == {
            k: v for k, v in new.items() if k != "oos_used_for_selection"}
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("sealed E01 snapshot exists; use a fresh path")
    result = snapshot()
    if args.baseline:
        result["native_account_rng_exact"] = compare(json.loads(args.baseline.read_text()), result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(routes=len(result["lanes"]), parity=result.get("native_account_rng_exact"),
                          publication=False)))
