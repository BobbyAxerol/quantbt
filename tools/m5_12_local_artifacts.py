"""Current-source local artifact provenance; not historical QMS or publication."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

from tools.qms08_package import ROOT, declared_pair
from tools.m5_12_source_guard import verify_current_source

SCHEMA = "quantbt.m5_12.local_artifacts.v1"
FRESH_SCHEMA = "quantbt.m5_12.local_artifacts.v2"
ACC_COMMIT = "70fe9f7c9b14469e6ea935e75f180f26ca1c175e"
ACC_RECEIPT = "docs/portfolio_review/evidence/acc01-qualification.json"
ACC_RECEIPT_SHA256 = "599bc38bdbd4545f27712741a471f453ed1430432c1c7b288ed6758c6845b8d4"
PACKAGING_INPUTS = ("pyproject.toml", "MANIFEST.in", "README.md", "CHANGELOG.md", "LICENSE")


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def native_reuse(wheel):
    """Require exact previously executed artifact and unchanged full Rust tree."""
    receipt = ROOT / ACC_RECEIPT
    if digest(receipt) != ACC_RECEIPT_SHA256:
        raise ValueError("ACC native receipt changed")
    native = json.loads(receipt.read_text())["native"]
    if digest(wheel) != native["wheel_sha256"]:
        raise ValueError("native wheel differs from the actually executed ACC artifact")
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", ACC_COMMIT, "rust"],cwd=ROOT,text=True).splitlines()
    current = subprocess.check_output(["git", "ls-files", "rust"],cwd=ROOT,text=True).splitlines()
    if current != names:
        raise ValueError("native source inventory differs from ACC")
    for name in names:
        previous = subprocess.check_output(["git","show",ACC_COMMIT+":"+name],cwd=ROOT)
        if (ROOT/name).read_bytes() != previous:
            raise ValueError("native source/lock/config changed: " + name)
    with ZipFile(wheel) as archive:
        extensions = [name for name in archive.namelist() if name.endswith(".so")]
        if len(extensions)!=1 or sha256(archive.read(extensions[0])).hexdigest()!=native["extension_sha256"]:
            raise ValueError("native extension does not match executed ACC bytes")
    return dict(policy="EXACT_ACC_ARTIFACT_UNCHANGED_NATIVE_SOURCE",source_commit=ACC_COMMIT,
        source_files=len(names),receipt=ACC_RECEIPT,receipt_sha256=ACC_RECEIPT_SHA256,
        wheel_sha256=native["wheel_sha256"],extension_sha256=native["extension_sha256"],
        remote_public_qualified=False)


def verify_local_artifacts(proof):
    if (proof.get("schema") not in (SCHEMA, FRESH_SCHEMA) or proof.get("publication") is not False
            or proof.get("release_authorized") is not False or proof.get("source_differences")!={}):
        raise ValueError("unknown, adapted or promoted local artifact proof")
    if (proof.get("core"),proof.get("native"))!=declared_pair():
        raise ValueError("local artifact pair mismatch")
    if proof.get("source")!=verify_current_source():
        raise ValueError("local artifact source is not exact current qualified source")
    if proof.get("packaging_inputs")!={name:digest(ROOT/name) for name in PACKAGING_INPUTS}:
        raise ValueError("local packaging metadata/readme changed")
    lane=Path(proof["lane"])
    if not lane.is_absolute() or lane.resolve()!=lane or not lane.is_relative_to(ROOT/".maturin/qms08"):
        raise ValueError("unsafe local artifact lane")
    refs=proof.get("artifact_refs",[])
    if len(refs)!=3:
        raise ValueError("exact artifact trio required")
    natives=[]
    for ref in refs:
        path=ROOT/ref["path"]
        if (path.resolve()!=path or path.parent!=lane/"dist" or path.is_symlink()
                or digest(path)!=ref["sha256"] or path.stat().st_size!=ref["bytes"]):
            raise ValueError("local artifact path/hash/size mismatch")
        if path.name.startswith("quantbt_native-"):
            natives.append(path)
    if len(natives)!=1:
        raise ValueError("exactly one native artifact required")
    if proof["schema"] == SCHEMA:
        if proof.get("native_reuse")!=native_reuse(natives[0]):
            raise ValueError("native reuse provenance mismatch")
    else:
        from tools.m5_12_native_build import verify_native_build
        if "native_reuse" in proof:
            raise ValueError("fresh native must not borrow historical reuse provenance")
        verify_native_build(proof["native_build"], natives[0], lane)
    if not proof.get("logs"):
        raise ValueError("actual build logs required")
    for name,expected in proof["logs"].items():
        path=ROOT/name
        if path.resolve()!=path or not path.is_relative_to(lane) or digest(path)!=expected:
            raise ValueError("build log changed or outside lane")
    return True
