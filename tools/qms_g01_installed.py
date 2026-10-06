"""Remote wheel/sdist proof for the exact zero-base compatibility artifact."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from tools.qms08_gate import ROOT, verify_pair


def qualify(lane):
    lane = Path(lane).resolve()
    proof_path = lane/"proof.json"
    proof = json.loads(proof_path.read_text())
    verify_pair(proof)
    destination = lane/"installed-g01-proof.json"
    if destination.exists():
        raise ValueError("sealed G01 proof exists; use a fresh lane")
    workspace = lane/"installed-g01-proof/workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    rows = {}
    for name in ("pair", "sdist"):
        command = [str(lane/name/"bin/python"), "-I", str(ROOT/"tools/qms_g01_consumer.py")]
        process = subprocess.run(command, cwd=workspace, env=env, text=True, capture_output=True,
                                 timeout=120, check=False)
        log = workspace.parent/f"{name}.log"
        log.write_text("$ "+" ".join(command)+"\n"+process.stdout+process.stderr)
        if process.returncode:
            raise ValueError(f"installed G01 consumer failed; see {log}")
        row = json.loads(process.stdout.splitlines()[-1])
        if row.get("schema") != "qms-g01-installed-metric-v1" or not row.get("financial_profile_parity"):
            raise ValueError("invalid G01 consumer proof")
        rows[name] = dict(result=row, log_sha256=sha256(log.read_bytes()).hexdigest())
    result = dict(schema="qms-g01-installed-lane-v1", consumers=rows,
        package_proof_sha256=sha256(proof_path.read_bytes()).hexdigest(),
        consumer_source_sha256=sha256((ROOT/"tools/qms_g01_consumer.py").read_bytes()).hexdigest(),
        publication=False, empirical_promotion=False)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    print(json.dumps(qualify(parser.parse_args().lane), sort_keys=True))
