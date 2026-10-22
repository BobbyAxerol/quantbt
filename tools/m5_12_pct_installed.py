"""Additional installed pct proof; no builds, installs or roster changes."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MODULES = {"tests/test_phase77_2_pct_equity_native.py": 16, "tests/test_m5_12_pct_alias.py": 3}
SCHEMA = "quantbt.m5_12.installed_pct.v1"
PROOF_SCHEMA = "quantbt.m5_12.local_artifacts.v2"
RELEASE_PROOF_SCHEMA = "qms-release-installed-pair-v1"
PROOF_SCHEMAS = frozenset((PROOF_SCHEMA, RELEASE_PROOF_SCHEMA))
CAPABILITY = "PCT_EQUITY_ACCEPTED_QTY_ACTIVITY_V1"
ACTIVITY = "accepted_qty_position_states_v1"
COUNTS = dict(tests=19, failures=0, errors=0, skipped=0)
NUMERIC_THREADS = dict(blas_threads=1, openmp_threads=1, numba_threads=1)
PINNED_FILES = (*MODULES, "tools/m5_12_pct_installed.py", "tools/qms_e08_consumer.py",
    "tools/qms08_gate.py", "tools/qms08_package.py",
    "tools/qms_installed_execution.py", "tools/m5_12_consumer_artifacts.py",
    "tools/m5_12_local_artifacts.py", "tools/m5_12_native_build.py",
    "tools/m5_12_source_guard.py", "tools/m5_12_pct_source_amendment.py",
    "tools/m5_12_pct_alias_amendment.py",
    "tools/m5_12_snapshot_amendment.py", "tools/m5_12_release120_amendment.py",
    "tools/m5_12_ci_format_amendment.py",
    "tools/m5_12_ci_rust_amendment.py",
    "tools/portfolio_repair_source_guard.py", "tools/account_metrics_source_guard.py",
    "tools/public_inventory_source_amendment.py", "tools/m5_12_extraction_contract.py")


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def source_pins():
    result = {}
    for name in PINNED_FILES:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing/linked public proof source: " + name)
        result[name] = digest(path)
    return result


def qualified_source(proof):
    if proof["schema"] == PROOF_SCHEMA:
        return proof["source"]
    from tools.m5_12_source_guard import verify_current_source
    return verify_current_source()


def validate_proof_binding(manifest, proof, proof_hash):
    schema = proof.get("schema")
    if (schema not in PROOF_SCHEMAS or manifest.get("package_proof_schema") != schema
            or manifest.get("package_proof_sha256") != proof_hash
            or not isinstance(manifest.get("source"), dict) or not manifest["source"]
            or schema == PROOF_SCHEMA and manifest["source"] != proof.get("source")):
        raise ValueError("unknown, stale or mismatched pct package-proof binding")


def counts_from_xml(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    cases = list(root.iter("testcase"))
    counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in COUNTS}
    if (counts != COUNTS or len(cases) != 19 or any(
            case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped"))):
        raise ValueError("pct installed proof requires exactly 19 passing JUnit cases and no skips")
    return counts


class Outcomes:
    def __init__(self):
        self.collected, self.reports, self.modules, self.xfail = [], {}, {}, False

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]
        for item in session.items:
            path = str(Path(item.path).resolve())
            self.modules[path] = self.modules.get(path, 0) + 1

    def pytest_runtest_logreport(self, report):
        self.reports.setdefault(report.nodeid, {})[report.when] = report.outcome
        self.xfail |= hasattr(report, "wasxfail")


def validate_outcomes(collected, reports, modules, xfail):
    if (len(collected) != 19 or len(set(collected)) != 19 or set(reports) != set(collected)
            or modules != {str(ROOT / name): count for name, count in MODULES.items()} or xfail
            or any(phases != dict(setup="passed", call="passed", teardown="passed")
                   for phases in reports.values())):
        raise ValueError("pct collection or actual setup/call/teardown is incomplete")


def check_capability(native):
    if getattr(native, CAPABILITY, None) != ACTIVITY:
        raise ValueError("installed native lacks accepted-quantity pct activity capability")


def installed_identity(manifest, kind):
    import _quantbt_native as native
    from tools.qms_e08_consumer import identity
    check_capability(native)
    return identity(manifest, kind)


def validate_identity(identity, manifest, kind):
    prefix = Path(manifest["prefixes"][kind])
    abi = manifest["interpreter"]
    site = prefix / "lib" / ("python" + abi[2] + "." + abi[3:]) / "site-packages"
    expected = dict(prefix=str(prefix), interpreter=abi, isolated=True, dont_write_bytecode=True,
        core=manifest["core"], native=manifest["native"], core_origin=str(site / "quantbt"),
        native_package_origin=str(site / "_quantbt_native"),
        modules=len(manifest["core_inventory"]), native_files=len(manifest["native_inventory"]),
        native_sha256=manifest["native_extension_sha256"])
    binary = Path(identity.get("native_origin", "/missing"))
    root = site / "_quantbt_native"
    if (any(identity.get(key) != value for key, value in expected.items())
            or not binary.is_relative_to(root)
            or manifest["native_inventory"].get(binary.relative_to(root).as_posix())
                != manifest["native_extension_sha256"]
            or digest(binary) != manifest["native_extension_sha256"]):
        raise ValueError("pct proof did not use the exact selected isolated consumer/native bytes")


def preload_installed():
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode:
        raise ValueError("pct child requires -I -B")
    if any(Path(value).resolve().is_relative_to(ROOT / "src") for value in sys.path):
        raise ValueError("source bootstrap forbidden in installed pct proof")
    import quantbt
    if "site-packages" not in Path(quantbt.__file__).resolve().parts:
        raise ValueError("pct child must preload installed QuantBT before checkout fixtures")
    sys.path.append(str(ROOT))


def consume(lane, kind, request):
    directory = lane / ("installed-pct-" + kind + "-proof")
    if request != directory / "manifest.json" or request.is_symlink():
        raise ValueError("pct child request outside its exact per-kind proof directory")
    raw = request.read_bytes()
    manifest = json.loads(raw)
    proof_raw = (lane / "proof.json").read_bytes()
    proof = json.loads(proof_raw)
    output = directory / (kind + ".json")
    scratch = directory / (kind + "-fixtures")
    if any(path.exists() or path.is_symlink() for path in (output, output.with_suffix(".xml"), scratch)):
        raise ValueError("pct output/fixture scratch already exists")
    validate_proof_binding(manifest, proof, sha256(proof_raw).hexdigest())
    if (manifest.get("schema") != SCHEMA or manifest.get("kind") != kind
            or manifest.get("prefixes") != {kind: str(lane / kind)}
            or manifest.get("source_sha256") != source_pins()):
        raise ValueError("changed/unbound pct execution request")
    preload_installed()
    before = installed_identity(manifest, kind)
    validate_identity(before, manifest, kind)
    import pytest
    from quantbt.optimization.meta_selection.telemetry import observed_threads
    outcomes = Outcomes()
    code = pytest.main(["-q", "--tb=short", "--noconftest", "--import-mode=importlib",
        "-p", "no:cacheprovider", "--basetemp", str(scratch),
        f"--junitxml={output.with_suffix('.xml')}", *[str(ROOT / name) for name in MODULES]], plugins=[outcomes])
    after = installed_identity(manifest, kind)
    if (after != before or request.read_bytes() != raw
            or (lane / "proof.json").read_bytes() != proof_raw
            or source_pins() != manifest["source_sha256"]):
        raise ValueError("pct installed identity, request or fixture source changed")
    counts = counts_from_xml(output.with_suffix(".xml"))
    validate_outcomes(outcomes.collected, outcomes.reports, outcomes.modules, outcomes.xfail)
    if code:
        raise ValueError("pct pytest did not exit successfully")
    threads = observed_threads(configured=NUMERIC_THREADS)
    if threads["mismatches"] or threads["inspection_limits"]:
        raise ValueError("pct numeric thread budget unresolved")
    row = dict(schema=SCHEMA, kind=kind, identity=after, capability=ACTIVITY, counts=counts,
        collected=outcomes.collected, reports=outcomes.reports, modules=outcomes.modules, xfail=False,
        manifest_sha256=sha256(raw).hexdigest(), package_proof_sha256=manifest["package_proof_sha256"],
        package_proof_schema=manifest["package_proof_schema"],
        source=manifest["source"], source_sha256=manifest["source_sha256"], threads=threads,
        native_worker_scope="existing module includes explicit two-worker parity; numeric pools fixed at one",
        junit_sha256=digest(output.with_suffix(".xml")), publication=False, complete_pair=False)
    write_json(output, row)
    return row


def qualify(lane, *, kind):
    lane = Path(lane)
    if (kind not in {"pair", "sdist"} or not lane.is_absolute() or lane.resolve() != lane
            or not lane.is_relative_to(ROOT / ".maturin/qms08")
            or lane.name not in {"cp311", "cp312", "cp313"}):
        raise ValueError("absolute canonical QMS lane and explicit pair/sdist kind required")
    directory = lane / ("installed-pct-" + kind + "-proof")
    destination = directory.with_suffix(".json")
    if any(path.exists() or path.is_symlink() for path in (directory, destination)):
        raise ValueError("pct proof/scratch exists; refuse overwrite")
    prefix = lane / kind
    if prefix.resolve() != prefix or not (prefix / "pyvenv.cfg").is_file() or not (prefix / "bin/python").is_file():
        raise ValueError("selected installed consumer must already exist; no installation is performed")
    from tools.qms_installed_execution import verify_proof_custody
    from tools.m5_12_consumer_artifacts import artifact_manifest
    proof_path = lane / "proof.json"
    proof = json.loads(proof_path.read_bytes())
    if proof.get("schema") not in PROOF_SCHEMAS:
        raise ValueError("ordinary release-pair or fresh-native v2 provenance required; no historical proof overlay")
    proof_hash = verify_proof_custody(proof_path, proof)
    artifacts = artifact_manifest(proof, lane)
    source = qualified_source(proof)
    pins = source_pins()
    manifest = dict(schema=SCHEMA, kind=kind, **artifacts, prefixes={kind: str(prefix)},
        interpreter=lane.name, source=source, source_sha256=pins,
        package_proof_schema=proof["schema"], package_proof_sha256=proof_hash)
    directory.mkdir()
    request = directory / "manifest.json"
    write_json(request, manifest)
    request_hash = digest(request)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
        OMP_NUM_THREADS="1", NUMBA_NUM_THREADS="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        NUMBA_CACHE_DIR=str(directory / "numba-cache"))
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(name, None)
    command = [str(prefix / "bin/python"), "-I", "-B", str(ROOT / "tools/m5_12_pct_installed.py"),
        "--lane", str(lane), "--kind", kind, "--child-request", str(request)]
    record = dict(command=command, cwd=str(directory), returncode=None, error=None)
    stdout = stderr = ""
    try:
        process = subprocess.run(command, cwd=directory, env=environment,
            text=True, capture_output=True, timeout=1200, check=False)
        record["returncode"], stdout, stderr = process.returncode, process.stdout, process.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        record["error"] = str(exc)
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        stdout, stderr = decoded(getattr(exc, "stdout", None)), decoded(getattr(exc, "stderr", None))
    with (directory / "consumer.log").open("x") as stream:
        stream.write("$ " + " ".join(command) + "\n" + stdout + stderr + "\n" + (record["error"] or ""))
    write_json(directory / "process.json", record)
    try:
        if record["returncode"] != 0:
            raise ValueError("pct installed child failed; command/exit/log retained")
        output = directory / (kind + ".json")
        row = json.loads(output.read_bytes())
        validate_identity(row["identity"], manifest, kind)
        validate_outcomes(row["collected"], row["reports"], row["modules"], row["xfail"])
        if (row.get("schema") != SCHEMA or row.get("kind") != kind or row.get("capability") != ACTIVITY
                or row.get("manifest_sha256") != request_hash or row.get("package_proof_sha256") != proof_hash
                or row.get("package_proof_schema") != proof["schema"]
                or row.get("source") != source or row.get("source_sha256") != pins
                or row.get("counts") != counts_from_xml(output.with_suffix(".xml"))
                or row.get("junit_sha256") != digest(output.with_suffix(".xml"))
                or row.get("publication") is not False or row.get("complete_pair") is not False
                or row["threads"]["configured"] != NUMERIC_THREADS
                or row["threads"]["mismatches"] or row["threads"]["inspection_limits"]):
            raise ValueError("pct child receipt, JUnit or custody mismatch")
    finally:
        try:
            verify_proof_custody(proof_path, proof, expected_sha256=proof_hash)
            if (artifact_manifest(proof, lane) != artifacts or source_pins() != pins
                    or qualified_source(proof) != source or digest(request) != request_hash):
                raise ValueError("pct source/artifacts/request changed during proof")
        except Exception as exc:
            write_json(directory / "custody.json", dict(status="FAIL_RETAINED", error=str(exc)))
            raise
        write_json(directory / "custody.json", dict(status="PASS", package_proof_sha256=proof_hash,
            manifest_sha256=request_hash, source_sha256=pins))
    receipt = dict(schema=SCHEMA, kind=kind, consumer=row, source=source,
        package_proof_schema=proof["schema"],
        source_sha256=pins, package_proof_sha256=proof_hash, manifest_sha256=request_hash,
        retained_sha256={p.name: digest(p) for p in directory.iterdir() if p.is_file()},
        complete_pair=False, publication=False, remote=os.environ.get("GITHUB_ACTIONS") == "true")
    write_json(destination, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", type=Path, required=True)
    parser.add_argument("--kind", choices=("pair", "sdist"), required=True)
    parser.add_argument("--child-request", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    value = consume(args.lane, args.kind, args.child_request) if args.child_request else qualify(args.lane, kind=args.kind)
    print(json.dumps(dict(schema=value["schema"], kind=args.kind, complete_pair=False, publication=False)))


if __name__ == "__main__":
    main()
