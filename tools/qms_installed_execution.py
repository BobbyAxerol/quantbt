"""Portable E06/E07/E08 wheel/sdist gate; runner-local hashes, no publication."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tarfile
from zipfile import ZipFile

from tools.qms08_package import ROOT, build_tool, declared_pair
from tools.qms_e08_consumer import EXPECTED, GROUPS, inventory


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def verify_proof_custody(path, proof, *, expected_sha256=None):
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    observed = sha256(raw).hexdigest()
    if snapshot != proof or expected_sha256 is not None and observed != expected_sha256:
        raise ValueError("package proof changed from the admitted snapshot")
    if proof.get("schema") == "qms-release-installed-pair-v1":
        from tools.qms08_gate import verify_pair
        verify_pair(proof)
    elif proof.get("schema") in ("quantbt.m5_12.local_artifacts.v1", "quantbt.m5_12.local_artifacts.v2"):
        from tools.m5_12_local_artifacts import verify_local_artifacts
        verify_local_artifacts(proof)
    elif proof.get("schema") != "qms-e08-local-artifacts-v1" or proof.get("publication") is not False:
        raise ValueError("unknown/unapproved artifact provenance")
    if path.read_bytes() != raw or proof != snapshot:
        raise ValueError("package proof changed during provenance verification")
    return observed


def native_inventory(archive):
    names = [name for name in archive.namelist() if name.startswith("_quantbt_native/") and not name.endswith("/")]
    if (len(names) != len(set(names)) or any(".." in Path(name).parts for name in names)
            or "_quantbt_native/__init__.py" not in names):
        raise ValueError("complete unique native namespace and wrapper required")
    result = {name.removeprefix("_quantbt_native/"): sha256(archive.read(name)).hexdigest() for name in names}
    if len([name for name in result if name.endswith(".so")]) != 1:
        raise ValueError("ambiguous native extension")
    return result


def artifact_manifest(proof):
    core, native = declared_pair()
    if (proof["core"], proof["native"]) != (core, native):
        raise ValueError("unapproved exact pair")
    paths = {}
    for ref in proof["artifact_refs"]:
        p = (ROOT/ref["path"]).resolve()
        if not p.is_relative_to(ROOT/".maturin/qms08") or digest(p) != ref["sha256"] or p.stat().st_size != ref["bytes"]:
            raise ValueError("changed/unsafe artifact")
        key = "native" if p.name.startswith("quantbt_native-") else "wheel" if p.suffix == ".whl" else "sdist"
        if key in paths:
            raise ValueError("duplicate artifact kind")
        paths[key] = p
    if set(paths) != {"wheel", "sdist", "native"}:
        raise ValueError("complete artifact trio required")
    from tools.check_release_artifacts import inspect_artifact
    if any(inspect_artifact(p) for p in paths.values()):
        raise ValueError("artifact privacy/allowlist failed")
    expected = inventory(ROOT/"src/quantbt")
    with ZipFile(paths["wheel"]) as archive:
        actual = {n.removeprefix("quantbt/"): sha256(archive.read(n)).hexdigest()
            for n in archive.namelist() if n.startswith("quantbt/") and not n.endswith("/")}
    with tarfile.open(paths["sdist"]) as archive:
        source = {m.name.split("/src/quantbt/", 1)[1]: sha256(archive.extractfile(m).read()).hexdigest()
            for m in archive.getmembers() if m.isfile() and "/src/quantbt/" in m.name}
    if actual != expected or source != expected:
        raise ValueError("wheel/sdist not exact final canonical source")
    with ZipFile(paths["native"]) as archive:
        native_files = native_inventory(archive)
        native_hash = next(value for name, value in native_files.items() if name.endswith(".so"))
    return dict(schema="qms-e08-installed-manifest-v1", core=core, native=native,
        core_inventory=expected, native_inventory=native_files, native_extension_sha256=native_hash,
        artifact_refs=proof["artifact_refs"], publication=False,
        fixture_sha256={str(p.relative_to(ROOT)): digest(p) for p in (
            *(ROOT/"tests/meta_selection"/n for names in GROUPS.values() for n in names),
            *(ROOT/"tests/meta_selection"/n for n in ("e07_support.py", "e08_support.py",
                "pre_e06_02_support.py", "test_pre_e06_02_conformance.py")),
            *(ROOT/"examples"/n for n in ("wfo_meta_execution.py", "wfo_meta_reactive_grid.py",
                "wfo_meta_scalar.py", "wfo_meta_portfolio.py", "wfo_meta_package.py", "intrabar_bracket_diagnostic.py")),
            ROOT/"tools/qms_e08_consumer.py", ROOT/"tools/qms_installed_execution.py")})


def validate_row(row, group, manifest, *, kind=None):
    if (row.get("schema") != "qms-e08-installed-execution-v1" or row.get("group") != group
            or row.get("counts") != dict(tests=EXPECTED[group], failures=0, errors=0, skipped=0)
            or row.get("publication") is not False or row.get("empirical_promotion") is not False):
        raise ValueError("missing/incomplete installed execution proof")
    identity = row["identity"]
    if (identity["core"], identity["native"], identity["native_sha256"], identity["modules"]) != (
            manifest["core"], manifest["native"], manifest["native_extension_sha256"], len(manifest["core_inventory"])):
        raise ValueError("consumer identity differs from artifacts")
    if any("site-packages" not in Path(identity[k]).parts for k in ("core_origin", "native_origin")):
        raise ValueError("checkout origin")
    # Historical row-only readers keep their recorded contract. Every newly
    # generated request below includes exact prefix/interpreter bindings.
    if "prefixes" in manifest:
        selected = row.get("kind") if kind is None else kind
        if selected not in manifest["prefixes"] or row.get("kind") != selected:
            raise ValueError("wrong selected artifact consumer")
        prefix = Path(manifest["prefixes"][selected])
        abi = manifest["interpreter"]
        site = prefix / "lib" / ("python" + abi[2] + "." + abi[3:]) / "site-packages"
        binary = Path(identity["native_origin"])
        if (identity.get("prefix") != str(prefix) or identity.get("interpreter") != abi
                or identity.get("isolated") is not True or identity.get("dont_write_bytecode") is not True
                or Path(identity["core_origin"]) != site / "quantbt"
                or identity.get("native_package_origin") != str(site / "_quantbt_native")
                or not binary.is_relative_to(site / "_quantbt_native")
                or manifest["native_inventory"].get(binary.relative_to(site / "_quantbt_native").as_posix())
                    != manifest["native_extension_sha256"]
                or identity.get("native_files") != len(manifest["native_inventory"])):
            raise ValueError("consumer is not the selected isolated prefix/interpreter/native package")
    if row["threads"]["mismatches"] or row["threads"]["inspection_limits"]:
        raise ValueError("unresolved thread budget")
    if row["source_sha256"] != {name: digest(ROOT/"tests/meta_selection"/name) for name in GROUPS[group]}:
        raise ValueError("test source drift")


def qualify(lane, *, offline=False, kind=None):
    if kind not in (None, "pair", "sdist"):
        raise ValueError("unknown artifact consumer kind")
    kinds = (kind,) if kind else ("pair", "sdist")
    lane = Path(lane).resolve()
    if not lane.is_relative_to(ROOT/".maturin/qms08"):
        raise ValueError("unsafe artifact lane")
    proof_path = lane/"proof.json"
    proof = json.loads(proof_path.read_text())
    proof_hash = verify_proof_custody(proof_path, proof)
    artifacts = artifact_manifest(proof)
    manifest = dict(**artifacts, interpreter=lane.name, prefixes={k: str(lane/k) for k in kinds})
    basename = "installed-execution" + ("-"+kind if kind else "") + "-proof"
    dest = lane/(basename+".json")
    directory = lane/basename
    if dest.exists() or directory.exists():
        raise ValueError("sealed proof/scratch exists; choose fresh lane")
    directory.mkdir()
    request = directory/"manifest.json"
    request.write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n")
    request_hash = digest(request)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    uv = build_tool("uv")
    rows = {}
    for kind in kinds:
        python = lane/kind/"bin/python"
        from tools.qms08_package import run
        run([uv, "pip", "install", *(["--offline"] if offline else []), "--python", python, "pytest>=9.1,<10"],
            cwd=directory, log=directory/(kind+"-test-dependencies.log"))
        for group in GROUPS:
            output = directory/(kind+"-"+group+".json")
            command = [str(python), "-I", "-B", str(ROOT/"tools/qms_e08_consumer.py"),
                "--root", str(ROOT), "--manifest", str(request), "--output", str(output), "--group", group, "--kind", kind]
            log = output.with_suffix(".log")
            try:
                process = subprocess.run(command, cwd=directory, env=environment,
                    text=True, capture_output=True, timeout=1200, check=False)
            except subprocess.TimeoutExpired as error:
                def text(value):
                    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                log.write_text(text(error.stdout)+text(error.stderr)+"\nTIMEOUT\n")
                raise ValueError("installed execution proof timed out; log retained") from error
            log.write_text("$ "+" ".join(command)+"\n"+process.stdout+process.stderr)
            if process.returncode:
                raise ValueError(f"installed execution failure; see {log}")
            row = json.loads(output.read_text())
            validate_row(row, group, manifest, kind=kind)
            if row["manifest_sha256"] != request_hash or digest(request) != request_hash:
                raise ValueError("consumer manifest mismatch")
            rows[kind+"-"+group] = row
            print(f"{kind}/{group}: {row['counts']['tests']} installed PASS", flush=True)
    verify_proof_custody(proof_path, proof, expected_sha256=proof_hash)
    if artifact_manifest(proof) != artifacts or digest(request) != request_hash:
        raise ValueError("source/artifacts changed during proof")
    receipt = dict(schema="qms-e08-installed-execution-lane-v1", rows=rows,
        kinds=list(kinds), complete_pair=len(kinds)==2,
        package_proof_sha256=proof_hash, manifest_sha256=request_hash,
        consumer_source_sha256=digest(ROOT/"tools/qms_e08_consumer.py"),
        retained_sha256={p.name: digest(p) for p in directory.iterdir() if p.is_file()},
        publication=False, remote=os.environ.get("GITHUB_ACTIONS") == "true")
    with dest.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--kind", choices=("pair", "sdist"), help="one partial artifact consumer; default requires both")
    args = parser.parse_args()
    print(json.dumps(qualify(args.lane, offline=args.offline, kind=args.kind), sort_keys=True))
