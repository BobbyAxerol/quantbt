"""Bind scalar consumers to the exact installed wheel/sdist qualification lane."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from tools.qms08_gate import ROOT, verify_pair


def qualify(lane):
    lane = Path(lane).resolve()
    proof_path = lane / "proof.json"
    proof = json.loads(proof_path.read_text())
    verify_pair(proof)
    destination = lane / "installed-scalar-proof.json"
    if destination.exists():
        raise ValueError("sealed installed scalar proof exists; use a fresh lane")
    records = lane / "installed-scalar-proof"
    workspace = records / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    consumers = {}
    expected = {(r, b) for b in ("native_vectorized", "native_event")
                for r in ("signal_notional", "notional", "unit")}
    expected.update({("pct_equity", "legacy"), ("dca_ladder", "legacy")})
    for name in ("pair", "sdist"):
        log = records / f"{name}.log"
        command = [str(lane / name / "bin/python"), "-I", str(ROOT / "tools/qms_e03_consumer.py"),
                   "--example", str(ROOT / "examples/wfo_meta_scalar.py")]
        process = subprocess.run(command, cwd=workspace, env=environment,
                                 text=True, capture_output=True, timeout=600, check=False)
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"installed scalar consumer failed; see {log}")
        result = json.loads(process.stdout.splitlines()[-1])
        if (result.get("core"), result.get("native")) != (proof["core"], proof["native"]):
            raise ValueError("installed scalar release pair mismatch")
        cells = result.get("cells", [])
        if len(cells) != 8 or {(c["target"], c["backend"]) for c in cells} != expected:
            raise ValueError("installed scalar proof has missing or duplicate cells")
        if not all(c.get("off_shadow_account_exact") and c.get("active_original_witness") for c in cells):
            raise ValueError("installed scalar account/witness proof failed")
        consumers[name] = dict(result=result, log_sha256=sha256(log.read_bytes()).hexdigest())
    receipt = dict(schema="qms-e03-installed-lane-v1", core=proof["core"], native=proof["native"],
        package_proof_sha256=sha256(proof_path.read_bytes()).hexdigest(), consumers=consumers,
        source_sha256={p: sha256((ROOT / p).read_bytes()).hexdigest() for p in
            ("tools/qms_e03_installed.py", "tools/qms_e03_consumer.py", "examples/wfo_meta_scalar.py")},
        publication=False, empirical_promotion=False)
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    result = qualify(parser.parse_args().lane)
    print(json.dumps(dict(core=result["core"], native=result["native"],
                          installed_scalar=list(result["consumers"]), publication=False)))
