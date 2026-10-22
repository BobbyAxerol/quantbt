"""Exact final-source archive manifest, layered on the QMS release-pair proof."""

from email.parser import BytesParser
from hashlib import sha256
from pathlib import Path, PurePosixPath
import tarfile
from zipfile import ZipFile

from tools.check_release_artifacts import inspect_artifact
from tools.m5_12_consumer_runtime import digest, inventory
from tools.qms08_gate import verify_pair
from tools.qms08_package import ROOT, declared_pair


def unique_members(rows):
    result = {}
    for name, payload in rows:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in result:
            raise ValueError("unsafe or duplicate archive member")
        result[name] = payload
    return result


def metadata_identity(members, suffix, name, version):
    records = [payload for path, payload in members.items() if path.endswith(suffix)]
    if len(records) != 1:
        raise ValueError("ambiguous distribution metadata")
    metadata = BytesParser().parsebytes(records[0])
    if metadata.get_all("Name") != [name] or metadata.get_all("Version") != [version]:
        raise ValueError("archive metadata identity mismatch")


def package_members(members, prefix):
    return {name.removeprefix(prefix): sha256(payload).hexdigest()
            for name, payload in members.items() if name.startswith(prefix)}


def artifact_manifest(proof, lane):
    if proof.get("schema") in ("quantbt.m5_12.local_artifacts.v1", "quantbt.m5_12.local_artifacts.v2"):
        from tools.m5_12_local_artifacts import verify_local_artifacts
        verify_local_artifacts(proof)
    elif proof.get("schema") == "qms-release-installed-pair-v1":
        verify_pair(proof)
    else:
        raise ValueError("ordinary exact release-pair proof required; no historical adaptation")
    core, native = declared_pair()
    paths = {}
    for ref in proof["artifact_refs"]:
        original = ROOT / ref["path"]
        path = original.resolve()
        if (path.parent != lane / "dist" or original.is_symlink()
                or digest(path) != ref["sha256"] or path.stat().st_size != ref["bytes"]):
            raise ValueError("artifact outside this exact lane or changed bytes")
        if path.name.startswith("quantbt_native-") and path.suffix == ".whl":
            kind = "native"
        elif path.name.startswith("quantbt_engine-") and path.suffix == ".whl":
            kind = "wheel"
        elif path.name.startswith("quantbt_engine-") and path.name.endswith(".tar.gz"):
            kind = "sdist"
        else:
            raise ValueError("unapproved artifact kind")
        if kind in paths or inspect_artifact(path):
            raise ValueError("duplicate artifact or privacy/member/content failure")
        paths[kind] = path
    if set(paths) != {"wheel", "sdist", "native"}:
        raise ValueError("wheel/sdist/native trio required")
    with ZipFile(paths["wheel"]) as archive:
        wheel = unique_members((name, archive.read(name)) for name in archive.namelist() if not name.endswith("/"))
    with ZipFile(paths["native"]) as archive:
        companion = unique_members((name, archive.read(name)) for name in archive.namelist() if not name.endswith("/"))
    with tarfile.open(paths["sdist"]) as archive:
        members = archive.getmembers()
        if any(member.issym() or member.islnk() for member in members):
            raise ValueError("sdist links forbidden")
        source = unique_members((m.name, archive.extractfile(m).read()) for m in members if m.isfile())
    metadata_identity(wheel, ".dist-info/METADATA", "quantbt-engine", core)
    metadata_identity(companion, ".dist-info/METADATA", "quantbt-native", native)
    top = {PurePosixPath(name).parts[0] for name in source}
    if len(top) != 1:
        raise ValueError("ambiguous sdist root")
    sdist_prefix = next(iter(top)) + "/"
    metadata_identity({name: data for name, data in source.items() if name == sdist_prefix + "PKG-INFO"},
                      "PKG-INFO", "quantbt-engine", core)
    expected = inventory(ROOT / "src/quantbt")
    if (not expected or "py.typed" not in expected
            or package_members(wheel, "quantbt/") != expected
            or package_members(source, sdist_prefix + "src/quantbt/") != expected):
        raise ValueError("wheel/sdist source or resources are not exact final canonical bytes")
    native_inventory = package_members(companion, "_quantbt_native/")
    extensions = [name for name in native_inventory if name.endswith(".so")]
    if len(extensions) != 1 or "__init__.py" not in native_inventory:
        raise ValueError("complete native package with one extension required")
    return dict(core=core, native=native, core_inventory=expected, native_inventory=native_inventory,
        native_extension_sha256=native_inventory[extensions[0]], artifact_refs=proof["artifact_refs"])
