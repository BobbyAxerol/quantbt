"""Remote wheel/sdist proof for the exact zero-base compatibility artifact."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

from tools.qms08_gate import ROOT, verify_pair


def validate_consumer(row, proof):
    if (row.get("schema") != "qms-g01-installed-metric-v1" or row.get("checks") != 3 or
            row.get("skipped") != 0 or row.get("financial_profile_parity") is not True or
            row.get("sample_policy") != "legacy_zero_base_v1" or row.get("publication") is not False or
            row.get("core_version") != proof["core"] or row.get("native_version") != proof["native"] or
            any("site-packages" not in Path(row.get(key, "")).parts for key in ("core_origin", "native_origin"))):
        raise ValueError("invalid G01 consumer proof")
    artifacts = [r for r in proof["artifact_refs"] if Path(r["path"]).name.startswith("quantbt_native-")]
    if len(artifacts) != 1:
        raise ValueError("G01 native artifact absent or ambiguous")
    with ZipFile(ROOT/artifacts[0]["path"]) as wheel:
        extensions = [n for n in wheel.namelist() if n.endswith(".so")]
        if len(extensions) != 1 or sha256(wheel.read(extensions[0])).hexdigest() != row["native_sha256"]:
            raise ValueError("G01 consumer did not load the exact native wheel")


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
        log = workspace.parent/f"{name}.log"
        try:
            process = subprocess.run(command, cwd=workspace, env=env, text=True, capture_output=True,
                                     timeout=120, check=False)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            log.write_text("$ "+" ".join(command)+"\n"+decoded(error.stdout)+decoded(error.stderr)+"\nTIMEOUT\n")
            raise ValueError(f"installed G01 consumer timed out; preserved {log}") from error
        log.write_text("$ "+" ".join(command)+"\n"+process.stdout+process.stderr)
        if process.returncode:
            raise ValueError(f"installed G01 consumer failed; see {log}")
        row = json.loads(process.stdout.splitlines()[-1])
        validate_consumer(row, proof)
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
