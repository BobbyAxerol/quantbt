"""Local integrated sampler, continuation and domain consumers, never publishing."""

import argparse
import json
import os
from pathlib import Path
import subprocess

from tools.qms_e08_package import LANE
from tools.qms_installed_execution import ROOT, artifact_manifest, digest, verify_proof_custody
from tools.qms_installed_consumers import source_hashes
from tools.qms_release_consumers import CONSUMERS, consumer_arguments, validate_consumers

EXTRA = {
    "qms_e03_consumer.py": "wfo_meta_scalar.py",
    "qms_e04_consumer.py": "wfo_meta_portfolio.py",
    "qms_e05_consumer.py": "wfo_meta_package.py",
    "qms_g01_consumer.py": None,
}


def consumer_command(lane, kind, request, name, arguments):
    return [str(lane/kind/"bin/python"), "-I", "-B", str(ROOT/"tools/qms_e08_related_consumer.py"),
        "--root", str(ROOT), "--manifest", str(request), "--kind", kind,
        "--consumer", name, "--", *arguments]


def validate_related(row, *, manifest, kind, name, request_hash):
    package = row.get("identity", {})
    prefix = manifest["prefixes"][kind]
    abi = manifest["interpreter"]
    site = Path(prefix)/"lib"/("python"+abi[2]+"."+abi[3:])/"site-packages"
    binary = Path(package.get("native_origin", ""))
    if (row.get("schema") != "qms-e08-related-installed-v1" or row.get("kind") != kind
            or row.get("consumer") != name or row.get("manifest_sha256") != request_hash
            or row.get("publication") is not False
            or package.get("prefix") != prefix or package.get("interpreter") != abi
            or package.get("isolated") is not True or package.get("dont_write_bytecode") is not True
            or package.get("core_origin") != str(site/"quantbt")
            or package.get("native_package_origin") != str(site/"_quantbt_native")
            or not binary.is_relative_to(site/"_quantbt_native")
            or manifest["native_inventory"].get(binary.relative_to(site/"_quantbt_native").as_posix())
                != manifest["native_extension_sha256"]
            or (package.get("core"), package.get("native"), package.get("native_sha256"))
                != (manifest["core"], manifest["native"], manifest["native_extension_sha256"])
            or package.get("modules") != len(manifest["core_inventory"])
            or package.get("native_files") != len(manifest["native_inventory"])
            or row.get("threads", {}).get("mismatches") != []
            or row.get("threads", {}).get("inspection_limits") != []):
        raise ValueError("related proof is not the selected exact isolated consumer")


def qualify(lane=None, *, kind=None):
    if kind not in (None, "pair", "sdist"):
        raise ValueError("unknown artifact consumer kind")
    kinds = (kind,) if kind else ("pair", "sdist")
    lane = Path(LANE if lane is None else lane).resolve()
    if not lane.is_relative_to(ROOT/".maturin/qms08"):
        raise ValueError("unsafe integrated artifact lane")
    proof_path = lane/"proof.json"
    proof = json.loads(proof_path.read_text())
    proof_hash = verify_proof_custody(proof_path, proof)
    basename = "integrated" + ("-"+kind if kind else "") + "-proof"
    directory, destination = lane/basename, lane/(basename+".json")
    if directory.exists() or destination.exists():
        raise ValueError("refuse sealed integrated proof overwrite")
    directory.mkdir()
    artifacts = artifact_manifest(proof)
    manifest = dict(**artifacts, interpreter=lane.name, prefixes={k: str(lane/k) for k in kinds},
        package_proof_schema=proof["schema"], package_proof_sha256=proof_hash)
    manifest["fixture_sha256"] = dict(artifacts["fixture_sha256"])
    manifest["allowed_consumers"] = [*CONSUMERS, *EXTRA]
    names = ["tools/qms_e08_integrated.py", "tools/qms_e08_related_consumer.py",
        "tools/qms_e08_consumer.py", "tools/qms_release_consumers.py",
        *("tools/"+n for n in (*CONSUMERS, *EXTRA)),
        *("examples/"+n for n in EXTRA.values() if n)]
    manifest["fixture_sha256"].update(source_hashes(ROOT))
    manifest["fixture_sha256"].update({n: digest(ROOT/n) for n in names})
    request = directory/"manifest.json"
    request.write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n")
    request_hash = digest(request)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    all_rows = {}
    for kind in kinds:
        rows = {}
        for name in (*CONSUMERS, *EXTRA):
            arguments = (consumer_arguments(name, core=proof["core"], native=proof["native"],
                examples=ROOT/"examples") if name in CONSUMERS else
                ["--example", str(ROOT/"examples"/EXTRA[name])] if EXTRA[name] else [])
            command = consumer_command(lane, kind, request, name, arguments)
            log = directory/(kind+"-"+name.removesuffix(".py")+".log")
            try:
                process = subprocess.run(command, cwd=directory, env=environment,
                    text=True, capture_output=True, timeout=900, check=False)
            except subprocess.TimeoutExpired as error:
                def text(value):
                    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                log.write_text(text(error.stdout)+text(error.stderr)+"\nTIMEOUT\n")
                raise ValueError(f"consumer timed out; preserved {log}") from error
            log.write_text("$ "+" ".join(command)+"\n"+process.stdout+process.stderr)
            if process.returncode:
                raise ValueError(f"integrated consumer failed; preserved {log}")
            row = json.loads(process.stdout.splitlines()[-1])
            validate_related(row, manifest=manifest, kind=kind, name=name, request_hash=request_hash)
            if digest(request) != request_hash:
                raise ValueError("integrated request changed during execution")
            rows[name] = row
            print(f"{kind}/{name}: PASS", flush=True)
        validate_consumers({n: rows[n]["result"] for n in CONSUMERS}, core=proof["core"], native=proof["native"])
        from tools.qms_e04_installed import validate_consumer as portfolio
        from tools.qms_e05_installed import validate_consumer as package
        from tools.qms_g01_installed import validate_consumer as metric
        pair = (proof["core"], proof["native"])
        scalar = rows["qms_e03_consumer.py"]["result"]
        expected = {(r, b) for b in ("native_vectorized", "native_event") for r in ("signal_notional", "notional", "unit")}
        expected.update({("pct_equity", "legacy"), ("dca_ladder", "legacy")})
        cells = scalar.get("cells", [])
        if ((scalar.get("core"), scalar.get("native")) != pair or len(cells) != 8
                or {(c["target"], c["backend"]) for c in cells} != expected
                or not all(c.get("off_shadow_account_exact") and c.get("active_original_witness") for c in cells)):
            raise ValueError("incomplete original scalar consumer proof")
        portfolio(rows["qms_e04_consumer.py"]["result"], pair)
        package(rows["qms_e05_consumer.py"]["result"], pair)
        metric(rows["qms_g01_consumer.py"]["result"], proof)
        all_rows[kind] = rows
    for name, expected in manifest["fixture_sha256"].items():
        if digest(ROOT/name) != expected:
            raise ValueError("source drift during integrated proof")
    verify_proof_custody(proof_path, proof, expected_sha256=proof_hash)
    if artifact_manifest(proof) != artifacts or digest(request) != request_hash:
        raise ValueError("source/artifact/request drift during integrated proof")
    receipt = dict(schema="qms-e08-integrated-installed-v1", rows=all_rows,
        kinds=list(kinds), complete_pair=len(kinds)==2,
        package_proof_schema=proof["schema"], package_proof_sha256=proof_hash,
        artifact_refs=proof["artifact_refs"], manifest_sha256=request_hash,
        retained_sha256={p.name: digest(p) for p in directory.iterdir() if p.is_file()},
        remote=False, publication=False, empirical_promotion=False)
    with destination.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, help="explicit current artifact lane; legacy default is not current qualification")
    parser.add_argument("--kind", choices=("pair", "sdist"), help="one partial consumer; default requires both")
    args = parser.parse_args()
    result = qualify(args.lane, kind=args.kind)
    print(json.dumps(dict(schema=result["schema"], consumers=sum(len(r) for r in result["rows"].values()), publication=False)))
