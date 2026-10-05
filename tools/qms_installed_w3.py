"""Bind installed W3 consumers to one actual interpreter's exact wheel proof."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

from tools.qms08_gate import ROOT, verify_pair
from tools.qms_installed_consumers import qualify as qualify_consumers


def qualify(lane: Path, *, receipt_name="installed-w3-proof.json") -> dict:
    lane = lane.resolve()
    proof_path = lane / "proof.json"
    proof = json.loads(proof_path.read_text())
    verify_pair(proof)
    if Path(receipt_name).name != receipt_name or not receipt_name.endswith(".json"):
        raise ValueError("receipt name must be a JSON basename inside the artifact lane")
    output = lane / receipt_name
    if output.exists():
        raise ValueError("sealed installed W3 proof exists; choose a fresh lane")
    records_directory = lane / output.stem
    workspace = records_directory / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    records = {}
    for name in ("pair", "sdist"):
        bundle = qualify_consumers([lane / name / "bin/python"], root=ROOT,
            core=proof["core"], native=proof["native"], workspace=workspace,
            logs=records_directory / name, environment=environment)
        records[name] = dict(consumer=bundle["consumers"]["qms_local_consumer.py"], **bundle)
    result = dict(schema="qms-installed-w3-v2", core=proof["core"], native=proof["native"],
        package_proof_sha256=sha256(proof_path.read_bytes()).hexdigest(),
        consumer_source_sha256=sha256((ROOT / "tools/qms_local_consumer.py").read_bytes()).hexdigest(),
        consumers=records, publication=False)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    parser.add_argument("--receipt-name", default="installed-w3-proof.json")
    args = parser.parse_args()
    result = qualify(args.lane, receipt_name=args.receipt_name)
    print(json.dumps(dict(core=result["core"], native=result["native"],
                          installed_w3=list(result["consumers"]), publication=False)))
