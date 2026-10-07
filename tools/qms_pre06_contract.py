"""Fail-closed local artifact checks; no runtime or scientific policy changes."""

from hashlib import sha256
import json
import subprocess
import tarfile
import zipfile

from tools.check_release_artifacts import inspect_artifact
from tools.qms08_package import ROOT, file_hash

ENTRY = "d1d1b4394e388b9336cf57af9b5dccb65338ae78"
PRE05 = ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_05_closure.json"
OWNER = ROOT / "benchmarks/optimization/meta_selection/qms_pre_e06_05_owner_acceptance.json"
GUIDE = "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md"
NATIVE_SHA = "f5fe1ec4d9268752733ba2c7023cc0e2548215986a8cd73fb6fafb285422a3b6"
EXTENSION_SHA = "e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba"
LANE = ROOT / ".maturin/qms08/pre-e06-06"
CLEANABLE = ("package-v1/build-env", "package-v1/wheel-consumer",
             "package-v1/sdist-consumer", "package-v1/stage/build")


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def checked_hashes(mapping):
    for name, expected in mapping.items():
        path = ROOT / name
        if not path.is_file() or file_hash(path) != expected:
            raise ValueError(f"sealed source/evidence drift: {name}")


def source_inventory(*, historical=False):
    names = subprocess.check_output(
        ["git", "ls-files", "src/quantbt", "rust", "pyproject.toml", "MANIFEST.in"],
        cwd=ROOT, text=True).splitlines()
    result = {n: file_hash(ROOT / n) for n in names}
    for n in names:
        old = subprocess.check_output(["git", "show", f"{ENTRY}:{n}"], cwd=ROOT)
        if historical:
            result[n] = sha256(old).hexdigest()
        elif sha256(old).hexdigest() != result[n]:
            raise ValueError(f"unapproved runtime/build change: {n}")
    return result


def prerequisites(*, historical=False):
    from tools.qms_pre05_source_guard import verify
    guard = verify()
    def checked(mapping):
        if not historical:
            return checked_hashes(mapping)
        for name, expected in mapping.items():
            original = subprocess.run(["git", "show", f"{ENTRY}:{name}"], cwd=ROOT,
                                      capture_output=True, check=False)
            if original.returncode == 0:
                if sha256(original.stdout).hexdigest() != expected:
                    raise ValueError(f"historical PRE05 source identity drift: {name}")
            else:
                checked_hashes({name: expected})
    prior, owner = json.loads(PRE05.read_text()), json.loads(OWNER.read_text())
    for key in ("runtime_source_sha256", "verification_source_sha256",
                "historical_preserved_sha256", "primary_artifacts_sha256"):
        checked(prior[key])
    checked_hashes({f".maturin/qms08/pre-e06-05/samples/matched-v3-{identity}.json": value
                    for identity, value in prior["samples_sha256"].items()})
    checked_hashes(owner["sealed_evidence_sha256"])
    checked(owner["runtime_source_sha256"])
    if (owner["status"] != "COMPLETE_LOCAL_OWNER_ACCEPTED_COST_EXCEPTION"
            or owner["correctness_rng_accounting_tolerances_waived"] is not False
            or owner["original_budget_pct"] != {"p50": 3, "p95": 5}
            or owner["original_disabled_not_met"] != 7
            or len(owner["accepted_exceptions"]) != 7
            or file_hash(ROOT / GUIDE) != prior["guide_sha256"]):
        raise ValueError("prerequisite/owner contract mismatch")
    return dict(source_guard=guard, runtime_sha256=source_inventory(historical=historical),
                historical=historical,
                predecessor_sha256=file_hash(PRE05), owner_sha256=file_hash(OWNER),
                guide_sha256=file_hash(ROOT / GUIDE))


def native_reuse(wheel):
    if file_hash(wheel) != NATIVE_SHA or inspect_artifact(wheel):
        raise ValueError("native artifact identity/privacy mismatch")
    baseline = ROOT / ".maturin/qms08/g01-package-v1/stage"
    names = subprocess.check_output(["git", "ls-files", "rust"], cwd=ROOT, text=True).splitlines()
    for name in names:
        if file_hash(ROOT / name) != file_hash(baseline / name):
            raise ValueError(f"native source drift: {name}")
    with zipfile.ZipFile(wheel) as archive:
        extensions = [n for n in archive.namelist() if n.endswith(".so")]
        if len(extensions) != 1 or sha256(archive.read(extensions[0])).hexdigest() != EXTENSION_SHA:
            raise ValueError("native extension mismatch")
    build_log = ROOT / ".maturin/qms08/g01-package-v1-native/build.log"
    text = build_log.read_text()
    if "--features" in text or "--release" not in text or "--locked" not in text:
        raise ValueError("native default build lineage mismatch")
    return dict(wheel_sha256=NATIVE_SHA, extension_sha256=EXTENSION_SHA,
                source_sha256={n: file_hash(ROOT / n) for n in names},
                build_log_sha256=file_hash(build_log), rebuilt=False)


def core_inventory(directory):
    return {p.relative_to(directory).as_posix(): file_hash(p)
            for p in directory.rglob("*") if p.is_file()
            and (p.suffix == ".py" or p.name == "py.typed")}


def artifact_source(path, expected):
    if inspect_artifact(path):
        raise ValueError("artifact privacy/allowlist failed")
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            actual = {n.removeprefix("quantbt/"): sha256(archive.read(n)).hexdigest()
                      for n in archive.namelist() if n.startswith("quantbt/")}
    else:
        with tarfile.open(path) as archive:
            actual = {}
            for member in archive.getmembers():
                if not member.isfile():
                    if not member.isdir():
                        raise ValueError("nonregular sdist member")
                    continue
                name = member.name.partition("/")[2]
                if name.startswith("src/quantbt/"):
                    actual[name.removeprefix("src/quantbt/")] = sha256(
                        archive.extractfile(member).read()).hexdigest()
                elif not (name in {"README.md", "CHANGELOG.md", "LICENSE", "MANIFEST.in",
                                   "pyproject.toml", "PKG-INFO", "setup.cfg"}
                          or name.startswith("src/quantbt_engine.egg-info/")):
                    raise ValueError(f"non-core sdist member: {name}")
    if actual != expected:
        raise ValueError("complete canonical package inventory mismatch")
    return dict(modules=len(actual), sha256=file_hash(path), bytes=path.stat().st_size)


def validate_matrix(records, required):
    if set(records) != set(required):
        raise ValueError("missing/extra installed workload")
    for identity, row in records.items():
        if row["expected_sha256"] != required[identity] or row["semantic_sha256"] != required[identity]:
            raise ValueError(f"full-work parity failed: {identity}")
        if row["mode"] != "off" and (row["models"] < 1 or row["minimum_origins"] < 12):
            raise ValueError(f"cold fallback cannot qualify: {identity}")
        if row["observer_failures"] or row["skipped"]:
            raise ValueError(f"missing installed capability: {identity}")


def cleanup_path(relative):
    if relative not in CLEANABLE:
        raise ValueError("unreviewed cleanup path")
    path = LANE / relative
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("symlinked cleanup root")
    subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=ROOT, check=True)
    return path
