"""Fresh native build provenance, separate from historical artifact reuse."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

from tools.qms08_package import ROOT


def native_sources():
    names = subprocess.check_output(
        ["git", "ls-files", "rust"], cwd=ROOT, text=True,
    ).splitlines()
    return {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def verify_native_build(value, wheel, lane):
    if value.get("schema") == "quantbt.m5_12.reused_fresh_native_build.v1":
        ref = value["receipt"]
        origin = ROOT / ref["path"]
        if (origin.resolve() != origin or origin.is_symlink()
                or not origin.is_relative_to(ROOT / ".maturin/qms08")
                or origin.name != "native-build.json"
                or sha256(origin.read_bytes()).hexdigest() != ref["sha256"]
                or json.loads(origin.read_text()) != value.get("build")):
            raise ValueError("retained fresh native build receipt changed or outside ownership")
        # Reuse the actual approved build, not an ACC receipt or version match.
        return verify_native_build(value["build"], wheel, origin.parent)
    policies = {"FRESH_APPROVED_ACCEPTED_POSITION_PARITY", "FRESH_APPROVED_RELEASE120_PRODUCT_METADATA"}
    if (value.get("schema") != "quantbt.m5_12.fresh_native_build.v1"
            or value.get("policy") not in policies
            or value.get("sources") != native_sources()
            or value.get("source_after") != value.get("sources")
            or value.get("jobs") != 1 or value.get("features") != "cargo_default"
            or value.get("publication") is not False):
        raise ValueError("fresh native source/build policy differs")
    if value["policy"] == "FRESH_APPROVED_RELEASE120_PRODUCT_METADATA":
        from tools import portfolio_repair_source_guard as guard
        from tools.m5_12_release120_amendment import manifest, BASELINE_COMMIT, MANIFEST_SHA256
        amendment = manifest(guard)
        expected = guard._committed_source_hashes(BASELINE_COMMIT, ["rust"])
        name = "rust/crates/quantbt-domain/src/generated_product_contracts.rs"
        expected[name] = amendment["sources"][name]["after_sha256"]
        if (value.get("release_pair") != {"core": "1.2.0", "native": "0.4.3"}
                or value.get("metadata_amendment_sha256") != MANIFEST_SHA256
                or value["sources"] != expected):
            raise ValueError("native release120 metadata must match the exact sealed amendment")
    command = value.get("command", [])
    if (not command or Path(command[0]).name != "maturin"
            or command[1:6] != ["build", "--release", "--locked", "--offline", "--manifest-path"]
            or any(flag in command for flag in ("--features", "--all-features", "--no-default-features"))):
        raise ValueError("fresh native exact locked offline default-feature command required")
    if sha256(wheel.read_bytes()).hexdigest() != value.get("wheel_sha256"):
        raise ValueError("fresh native wheel bytes changed")
    with ZipFile(wheel) as archive:
        extensions = [name for name in archive.namelist() if name.endswith(".so")]
        if (len(extensions) != 1
                or sha256(archive.read(extensions[0])).hexdigest() != value.get("extension_sha256")):
            raise ValueError("fresh native extension bytes changed")
    log = ROOT / value["log"]
    if (log.resolve() != log or not log.is_relative_to(lane) or log.is_symlink()
            or sha256(log.read_bytes()).hexdigest() != value.get("log_sha256")
            or value.get("returncode") != 0):
        raise ValueError("fresh native successful build log required")
    if not value.get("rustc") or not value.get("maturin") or not value.get("python"):
        raise ValueError("fresh native toolchain identities required")
    return True
