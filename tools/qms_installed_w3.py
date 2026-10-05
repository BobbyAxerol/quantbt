"""Bind installed W3 consumers to one actual interpreter's exact wheel proof."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from tools.qms08_gate import ROOT, verify_pair


def qualify(lane: Path) -> dict:
    lane = lane.resolve()
    proof_path = lane / "proof.json"
    proof = json.loads(proof_path.read_text())
    verify_pair(proof)
    output = lane / "installed-w3-proof.json"
    if output.exists():
        raise ValueError("sealed installed W3 proof exists; choose a fresh lane")
    workspace = lane / "w3-workspace"
    workspace.mkdir(exist_ok=True)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    records = {}
    for name in ("pair", "sdist"):
        command = [str(lane / name / "bin/python"), "-I",
                   str(ROOT / "tools/qms_local_consumer.py"),
                   "--core-version", proof["core"], "--native-version", proof["native"]]
        process = subprocess.run(command, cwd=workspace, env=environment,
                                 capture_output=True, text=True, timeout=180)
        log = lane / f"{name}-w3-consumer.log"
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"installed W3 consumer failed; see {log}")
        record = json.loads(process.stdout.splitlines()[-1])
        required = ("off_shadow_exact", "same_pass", "selected_lineage", "closed")
        if (any(record.get(k) is not True for k in required)
                or record.get("observer_failures") != 0
                or (record.get("core_version"), record.get("native_version"))
                != (proof["core"], proof["native"])):
            raise ValueError("installed W3 consumer contract mismatch")
        records[name] = dict(consumer=record, log_sha256=sha256(log.read_bytes()).hexdigest())
    result = dict(schema="qms-installed-w3-v1", core=proof["core"], native=proof["native"],
        package_proof_sha256=sha256(proof_path.read_bytes()).hexdigest(),
        consumer_source_sha256=sha256((ROOT / "tools/qms_local_consumer.py").read_bytes()).hexdigest(),
        consumers=records, publication=False)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    result = qualify(parser.parse_args().lane)
    print(json.dumps(dict(core=result["core"], native=result["native"],
                          installed_w3=list(result["consumers"]), publication=False)))
