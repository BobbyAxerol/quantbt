"""Pin the installed CI extension to the preceding workflow-built native wheel."""

import argparse
from email.parser import BytesParser
from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path
import sys
import tomllib
import zipfile

from tools.check_release_artifacts import inspect_artifact


def verify(wheel, *, loaded_path, loaded_version, expected_version, prefix):
    if Path(loaded_path).is_symlink():
        raise ValueError("native extension must not be a symlink")
    wheel, loaded_path, prefix = Path(wheel), Path(loaded_path).resolve(), Path(prefix).resolve()
    if inspect_artifact(wheel):
        raise ValueError("native wheel allowlist/privacy failed")
    with zipfile.ZipFile(wheel) as archive:
        extensions = [name for name in archive.namelist() if name.endswith((".so", ".pyd", ".dylib"))]
        descriptors = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(extensions) != 1 or len(descriptors) != 1:
            raise ValueError("exactly one native extension and distribution metadata required")
        package = BytesParser().parsebytes(archive.read(descriptors[0]))
        if (package["Name"] != "quantbt-native" or package["Version"] != expected_version
                or loaded_version != expected_version):
            raise ValueError("native wheel/installed version differs from source declaration")
        expected = sha256(archive.read(extensions[0])).hexdigest()
    if prefix not in loaded_path.parents:
        raise ValueError("native extension is outside the selected CI environment")
    if sha256(loaded_path.read_bytes()).hexdigest() != expected:
        raise ValueError("installed native extension differs from workflow-built wheel")
    return dict(schema="quantbt.ci.native_wheel_identity.v1", wheel=wheel.as_posix(),
        wheel_sha256=sha256(wheel.read_bytes()).hexdigest(), extension_sha256=expected,
        installed_extension=loaded_path.as_posix(), native_version=loaded_version,
        scope="installed bytes match supplied wheel; source lineage belongs to preceding workflow build",
        publication=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wheels = list(args.wheel_dir.glob("quantbt_native-*.whl"))
    if len(wheels) != 1:
        raise ValueError("one freshly built native wheel is required")
    import _quantbt_native as native
    origin = Path(native.__file__).resolve()
    if origin.suffix not in {".so", ".pyd", ".dylib"}:
        files = list(origin.parent.glob("*.so")) + list(origin.parent.glob("*.pyd")) + list(origin.parent.glob("*.dylib"))
        if len(files) != 1:
            raise ValueError("one installed native extension is required")
        origin = files[0]
    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "rust/native_event/pyproject.toml").read_text())["project"]["version"]
    receipt = verify(wheels[0], loaded_path=origin, loaded_version=metadata.version("quantbt-native"),
                     expected_version=declared, prefix=sys.prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
    with args.github_env.open("a") as stream:
        stream.write("QUANTBT_REPAIR_NATIVE_SHA256=" + receipt["extension_sha256"] + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
