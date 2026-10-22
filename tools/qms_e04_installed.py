"""Bind portfolio consumer evidence to exact wheel/sdist qualification lanes."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from tools.qms08_gate import ROOT, verify_pair


def validate_consumer(result, pair):
    if (result.get("core"), result.get("native")) != tuple(pair):
        raise ValueError("installed portfolio release pair mismatch")
    cells = result.get("cells", [])
    if len(cells) != 2 or {c.get("sizing") for c in cells} != {"target_units", "%_equity"}:
        raise ValueError("installed portfolio proof has missing or duplicate cells")
    if (result.get("schema") != "qms-e04-installed-portfolio-v1"
            or not all(c.get("off_shadow_account_exact") and c.get("active_original_witness")
                       and c.get("observer_attempts", 0) > 0 for c in cells)
            or result.get("publication") is not False or result.get("empirical_promotion") is not False):
        raise ValueError("installed portfolio account/witness proof failed")


def qualify(lane):
    lane = Path(lane).resolve()
    proof_path = lane / "proof.json"
    proof = json.loads(proof_path.read_text())
    verify_pair(proof)
    destination = lane / "installed-portfolio-proof.json"
    if destination.exists():
        raise ValueError("sealed installed portfolio proof exists; use a fresh lane")
    records = lane / "installed-portfolio-proof"
    workspace = records / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    consumers = {}
    for name in ("pair", "sdist"):
        log = records / f"{name}.log"
        command = [str(lane / name / "bin/python"), "-I", str(ROOT / "tools/qms_e04_consumer.py"),
                   "--example", str(ROOT / "examples/wfo_meta_portfolio.py")]
        process = subprocess.run(command, cwd=workspace, env=environment,
                                 text=True, capture_output=True, timeout=600, check=False)
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"installed portfolio consumer failed; see {log}")
        result = json.loads(process.stdout.splitlines()[-1])
        validate_consumer(result, (proof["core"], proof["native"]))
        consumers[name] = dict(result=result, log_sha256=sha256(log.read_bytes()).hexdigest())
    receipt = dict(schema="qms-e04-installed-lane-v1", core=proof["core"], native=proof["native"],
        package_proof_sha256=sha256(proof_path.read_bytes()).hexdigest(), consumers=consumers,
        source_sha256={p: sha256((ROOT / p).read_bytes()).hexdigest() for p in
            ("tools/qms_e04_installed.py", "tools/qms_e04_consumer.py", "examples/wfo_meta_portfolio.py")},
        publication=False, empirical_promotion=False)
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    result = qualify(parser.parse_args().lane)
    print(json.dumps(dict(core=result["core"], native=result["native"],
                          installed_portfolio=list(result["consumers"]), publication=False)))
