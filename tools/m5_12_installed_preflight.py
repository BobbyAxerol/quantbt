"""Qualify fresh staged Mode5/ReportingV1/ACC consumers; never build or install."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

from tools.m5_12_consumer_artifacts import artifact_manifest
from tools.m5_12_consumer_matrix import (
    FEATURES, FIXTURES, REQUIRED_FIXTURE_MODULES, REQUIRED_MODULES, execution_bytes,
    validate_execution, validate_outcomes,
)
from tools.m5_12_consumer_runtime import digest
from tools.qms08_package import ROOT


def fixture_manifest():
    return {destination: digest(ROOT / source) for source, destination in FIXTURES.items()}


def verifier_manifest():
    return {name: digest(ROOT / name) for name in
            ("tools/m5_12_installed_preflight.py", "tools/m5_12_consumer_artifacts.py",
             "tools/m5_12_source_guard.py", "tools/m5_12_extraction_contract.py",
             "tools/m5_12_pct_source_amendment.py",
             "tools/m5_12_pct_alias_amendment.py",
             "tools/m5_12_local_artifacts.py", "tools/m5_12_native_build.py",
             "tools/portfolio_repair_source_guard.py", "tools/account_metrics_source_guard.py",
             "tools/public_inventory_source_amendment.py")}


def source_manifest():
    from tools.m5_12_source_guard import verify_current_source
    provenance = verify_current_source()
    if (not isinstance(provenance, dict) or provenance.get("financial_source_changed") is not True
            or provenance.get("current_source_qualified") is not True
            or provenance.get("historical_receipts_unchanged") is not True
            or provenance.get("native_artifacts_qualified") is not False
            or provenance.get("publication") is not False):
        raise ValueError("current source provenance must disclose changed finance and unqualified artifacts")
    provenance = json.loads(json.dumps(provenance, sort_keys=True, allow_nan=False))
    qualified_commit = provenance.get("source_commit", "")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if any(not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value)
           for value in (commit, qualified_commit)):
        raise ValueError("exact current source commit required")
    return dict(current_commit=commit, artifacts_qualified=False, provenance=provenance)


def source_digest(source):
    return sha256(json.dumps(source, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_row(row, manifest, kind, request_hash):
    if (row.get("schema") != "m5-12-installed-consumer-v1" or row.get("kind") != kind
            or row.get("run_id") != manifest["run_id"] or row.get("manifest_sha256") != request_hash
            or row.get("source_commit") != manifest["source"]["current_commit"]
            or row.get("source_provenance_sha256") != source_digest(manifest["source"])
            or type(row.get("skipped")) is not int or row["skipped"] != 0
            or any(row.get(key) is not False for key in
                   ("publication", "empirical_promotion", "defaults_activated"))):
        raise ValueError("missing, stale or promoted installed feature proof")
    features = validate_outcomes(row["collected"], row["reports"])
    validate_execution(row.get("execution"), row.get("optimizer"))
    if row.get("execution_sha256") != sha256(execution_bytes(row["execution"])).hexdigest():
        raise ValueError("bounded execution receipt/summary digest mismatch")
    if row.get("features") != features:
        raise ValueError("feature receipt does not match actual complete execution")
    if (row.get("cwd") != str(Path(manifest["stages"][kind]).parent)
            or row.get("harness") != manifest["stages"][kind]
            or row.get("fixture_modules") != {name: str(Path(manifest["stages"][kind]) / relative)
                for name, relative in REQUIRED_FIXTURE_MODULES.items()}):
        raise ValueError("consumer did not execute the fresh staged harness")
    identity = row["identity"]
    resources = {n: h for n, h in manifest["core_inventory"].items() if not n.endswith(".py")}
    if (identity.get("core") != manifest["core"] or identity.get("native") != manifest["native"]
            or identity.get("interpreter") != manifest["interpreter"]
            or identity.get("prefix") != manifest["prefixes"][kind]
            or identity.get("native_sha256") != manifest["native_extension_sha256"]
            or identity.get("resources") != resources
            or identity.get("core_files") != len(manifest["core_inventory"])
            or identity.get("native_files") != len(manifest["native_inventory"])):
        raise ValueError("consumer identity differs from exact archives")
    site = Path(manifest["prefixes"][kind]) / "lib" / ("python" + manifest["python_version"]) / "site-packages"
    if Path(identity["core_origin"]) != site / "quantbt":
        raise ValueError("core origin outside exact installed environment")
    native_origin = Path(identity["native_origin"])
    if (not native_origin.is_relative_to(site / "_quantbt_native")
            or digest(native_origin) != manifest["native_extension_sha256"]):
        raise ValueError("wrong actual native extension origin/bytes")
    loaded = identity["loaded_modules"]
    if not set(REQUIRED_MODULES).issubset(loaded):
        raise ValueError("missing actual installed feature modules")
    for name, origin in loaded.items():
        package = name.split(".", 1)[0]
        if package not in {"quantbt", "_quantbt_native"}:
            raise ValueError("unknown loaded package identity")
        root, path = site / package, Path(origin)
        inventory = manifest["core_inventory" if package == "quantbt" else "native_inventory"]
        if (not path.is_relative_to(root) or path.resolve() != path
                or inventory.get(path.relative_to(root).as_posix()) != digest(path)):
            raise ValueError("actual loaded path/source differs from manifest")


def qualify(lane, *, kind=None, attempt=1):
    if kind not in (None, "pair", "sdist"):
        raise ValueError("unknown installed consumer kind")
    kinds = (kind,) if kind is not None else ("pair", "sdist")
    if type(attempt) is not int or not 1 <= attempt <= 16:
        raise ValueError("explicit bounded attempt number required")
    lane = Path(lane).resolve()
    interpreter = "cp" + "".join(map(str, sys.version_info[:2]))
    if not lane.is_relative_to(ROOT / ".maturin/qms08") or lane.name != interpreter:
        raise ValueError("exact current CPython QMS artifact lane required")
    basename = "installed-m5-12" + ("-" + kind if kind is not None else "") + "-proof"
    if attempt != 1:
        basename = basename.removesuffix("-proof") + "-attempt-" + str(attempt) + "-proof"
    destination = lane / (basename + ".json")
    records = lane / basename
    if destination.exists() or records.exists():
        raise ValueError("prior proof or failed scratch exists; use a fresh lane, never reuse PASS")
    source_state = source_manifest()
    proof_path = lane / "proof.json"
    proof_hash = digest(proof_path)
    proof = json.loads(proof_path.read_text())
    artifacts = artifact_manifest(proof, lane)
    fixture_hashes = fixture_manifest()
    verifier_hashes = verifier_manifest()
    records.mkdir()
    workspace = Path(tempfile.mkdtemp(prefix="quantbt-m5-12-")).resolve()
    (records / "scratch.json").write_text(json.dumps(dict(workspace=str(workspace),
        retained="Logs, request, XML and result receipts remain in this artifact lane",
        cleanup="Caller must review inactivity and exact scratch path; no automatic deletion"), indent=2) + "\n")
    if workspace.is_relative_to(ROOT):
        raise ValueError("temporary consumer workspace must be outside checkout")
    manifest = dict(schema="m5-12-installed-request-v1", run_id=secrets.token_hex(24),
        **artifacts, checkout=str(ROOT), interpreter=interpreter,
        source=source_state, kinds=list(kinds),
        python_version=".".join(map(str, sys.version_info[:2])), features=FEATURES,
        fixtures=fixture_hashes, prefixes={}, stages={})
    for kind in kinds:
        prefix = lane / kind
        if not (prefix / "pyvenv.cfg").is_file() or not (prefix / "bin/python").is_file():
            raise ValueError("freshly installed exact-pair environment required; consumer never installs")
        manifest["prefixes"][kind] = str(prefix)
        stage = workspace / kind / "harness"
        stage.mkdir(parents=True)
        manifest["stages"][kind] = str(stage)
        for source_name, target in FIXTURES.items():
            output = stage / target
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source_name, output)
            if digest(output) != fixture_hashes[target]:
                raise ValueError("source fixture changed while staging")
    request = records / "manifest.json"
    request.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(name, None)
    rows = {}
    for kind in kinds:
        stage = Path(manifest["stages"][kind])
        environment["NUMBA_CACHE_DIR"] = str(stage.parent / "numba-cache")
        output = records / (kind + ".json")
        command = [str(lane / kind / "bin/python"), "-I", "-B",
            "-X", "pycache_prefix=" + str(stage.parent / "bytecode"),
            str(stage / "tools/m5_12_consumer_runtime.py"), "--manifest", str(request),
            "--kind", kind, "--output", str(output)]
        log = records / (kind + ".log")
        try:
            process = subprocess.run(command, cwd=stage.parent, env=environment,
                text=True, capture_output=True, timeout=1200, check=False)
        except (subprocess.TimeoutExpired, OSError) as error:
            def decoded(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            log.write_text("$ " + " ".join(command) + "\n" + decoded(getattr(error, "stdout", None))
                + decoded(getattr(error, "stderr", None)) + "\nFAILED: " + str(error) + "\n")
            raise ValueError(f"installed consumer could not complete; retained {log}") from error
        log.write_text("$ " + " ".join(command) + "\n" + process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"installed consumer failed; retained {log}")
        row = json.loads(output.read_text())
        validate_row(row, manifest, kind, digest(request))
        execution_output = records / (kind + "-execution.json")
        if (digest(execution_output) != row["execution_sha256"]
                or json.loads(execution_output.read_text()) != row["execution"]):
            raise ValueError("retained actual execution summary differs from child receipt")
        rows[kind] = row
        print(f"{kind}: installed synthetic roster complete for this artifact kind only", flush=True)
    if (digest(proof_path) != proof_hash or fixture_manifest() != fixture_hashes
            or verifier_manifest() != verifier_hashes
            or source_manifest() != source_state
            or artifact_manifest(proof, lane) != artifacts):
        raise ValueError("source, artifacts, fixtures or package proof changed during execution")
    if json.loads(request.read_text()) != manifest:
        raise ValueError("installed request changed during execution")
    receipt = dict(schema="m5-12-installed-lane-v1", run_id=manifest["run_id"], consumers=rows,
        kinds=list(kinds), complete_pair=len(kinds) == 2,
        proof_scope="wheel_and_sdist_consumers" if len(kinds) == 2 else "single_artifact_consumer",
        source=source_state, source_provenance_sha256=source_digest(source_state),
        package_proof_sha256=proof_hash, manifest_sha256=digest(request),
        verifier_sha256=verifier_hashes, fixture_sha256=fixture_hashes,
        retained_sha256={p.name: digest(p) for p in records.iterdir() if p.is_file()},
        scratch=str(workspace), publication=False, empirical_promotion=False,
        defaults_activated=False, remote=os.environ.get("GITHUB_ACTIONS") == "true")
    with destination.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    parser.add_argument("--kind", choices=("pair", "sdist"), help="one artifact consumer only; default requires both")
    parser.add_argument("--attempt", type=int, default=1, help="fresh append-only proof attempt; never replaces a prior receipt")
    args = parser.parse_args()
    result = qualify(args.lane, kind=args.kind, attempt=args.attempt)
    print(json.dumps(dict(schema=result["schema"], run_id=result["run_id"], kinds=result["kinds"],
        proof_scope=result["proof_scope"], complete_pair=result["complete_pair"],
        consumers=list(result["consumers"]))))
