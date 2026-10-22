"""Remote installed package proof for exact wheel and sdist consumer lanes."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from tools.qms08_gate import ROOT, verify_pair


def validate_consumer(result, pair):
    cells = result.get("cells", [])
    if (result.get("core"), result.get("native")) != tuple(pair):
        raise ValueError("installed package release pair mismatch")
    if (result.get("schema") != "qms-e05-installed-package-v1" or len(cells) != 3
            or {c.get("kind") for c in cells} != {"basket", "basis", "stat_pair"}
            or not all(c.get("off_shadow_account_exact") and c.get("original_witness")
                       and c.get("observer_attempts", 0) > 0 for c in cells)
            or result.get("publication") is not False or result.get("empirical_promotion") is not False):
        raise ValueError("installed package account/witness proof incomplete")


def qualify(lane):
    lane = Path(lane).resolve()
    proof_path = lane / "proof.json"
    proof = json.loads(proof_path.read_text())
    verify_pair(proof)
    destination = lane / "installed-package-proof.json"
    if destination.exists():
        raise ValueError("sealed installed package proof exists; use a fresh lane")
    records = lane / "installed-package-proof"
    workspace = records / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    consumers = {}
    for name in ("pair", "sdist"):
        log = records / f"{name}.log"
        command = [str(lane / name / "bin/python"), "-I", str(ROOT / "tools/qms_e05_consumer.py"),
                   "--example", str(ROOT / "examples/wfo_meta_package.py")]
        process = subprocess.run(command, cwd=workspace, env=environment,
                                 text=True, capture_output=True, timeout=600, check=False)
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"installed package consumer failed; see {log}")
        result = json.loads(process.stdout.splitlines()[-1])
        validate_consumer(result, (proof["core"], proof["native"]))
        consumers[name] = dict(result=result, log_sha256=sha256(log.read_bytes()).hexdigest())
    receipt = dict(schema="qms-e05-installed-lane-v1", core=proof["core"], native=proof["native"],
        package_proof_sha256=sha256(proof_path.read_bytes()).hexdigest(), consumers=consumers,
        source_sha256={p: sha256((ROOT / p).read_bytes()).hexdigest() for p in
            ("tools/qms_e05_installed.py", "tools/qms_e05_consumer.py", "examples/wfo_meta_package.py")},
        publication=False, empirical_promotion=False)
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    result = qualify(parser.parse_args().lane)
    print(json.dumps(dict(core=result["core"], native=result["native"], installed_packages=list(result["consumers"]))))
