"""Isolated local native candidate, never overwrite the published/installed 0.4.2."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".maturin/qms04"
CANDIDATE = "0.4.3.dev1"


def load_candidate(path, *, candidate=CANDIDATE):
    # A private tool namespace avoids replacing the installed financial module.
    spec = importlib.util.spec_from_file_location(
        "_quantbt_qms_candidate._quantbt_native", path
    )
    if spec is None or spec.loader is None:
        raise ValueError("candidate extension path is not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        module.version() != candidate
        or module.qms_numeric_descriptor_v1()["abi"] != "qms-numeric-v1"
    ):
        raise ValueError("candidate version/ABI mismatch")
    return module


def build(output=OUTPUT, *, candidate=CANDIDATE, features="qms-numeric-candidate"):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    maturin = Path(sys.executable).parent / "maturin"
    if not maturin.is_file():
        raise RuntimeError("Install maturin>=1.9,<2 in the QuantBT environment")
    with tempfile.TemporaryDirectory(prefix="quantbt-qms04-candidate-") as raw:
        stage = Path(raw) / "rust"
        shutil.copytree(
            ROOT / "rust", stage, ignore=shutil.ignore_patterns("target", "__pycache__")
        )
        # Mechanical build-only version rewrite. Source registry and lockfile in
        # the checkout stay untouched; released financial compatibility stays exact.
        cargo = stage / "native_event/Cargo.toml"
        source_version = tomllib.loads(cargo.read_text())["package"]["version"]
        cargo.write_text(
            cargo.read_text().replace(
                f'version = "{source_version}"',
                f'version = "{candidate.replace(".dev", "-dev.")}"',
                1,
            )
        )
        project = stage / "native_event/pyproject.toml"
        project.write_text(
            project.read_text().replace(
                f'version = "{source_version}"', f'version = "{candidate}"', 1
            )
        )
        generated = stage / "crates/quantbt-domain/src/generated_product_contracts.rs"
        text = generated.read_text()
        old = f'pub const NATIVE_PACKAGE_VERSION: &str = "{source_version}";'
        if text.count(old) != 1:
            raise RuntimeError(
                "candidate generator constant changed; explicit version migration required"
            )
        generated.write_text(
            text.replace(
                old, f'pub const NATIVE_PACKAGE_VERSION: &str = "{candidate}";'
            )
        )
        env = dict(os.environ)
        env["CARGO_TARGET_DIR"] = str(ROOT / "rust/target/qms04-candidate")
        command = [
            str(maturin),
            "build",
            "--offline",
            "--release",
            "--no-default-features",
            "--features",
            features,
            "--manifest-path",
            str(cargo),
            "--interpreter",
            sys.executable,
            "--out",
            str(output),
        ]
        subprocess.run(command, cwd=stage, env=env, check=True)
    wheels = list(output.glob(f"quantbt_native-{candidate}-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("candidate wheel must be unambiguous for this interpreter")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        members = [
            n
            for n in archive.namelist()
            if n.endswith(".so") and "/_quantbt_native." in n
        ]
        if len(members) != 1:
            raise RuntimeError("candidate wheel extension missing/ambiguous")
        extension = output / Path(members[0]).name
        extension.write_bytes(archive.read(members[0]))
    module = load_candidate(extension, candidate=candidate)
    proof = {
        "candidate": candidate,
        "api": module.api_version(),
        "descriptor": module.qms_numeric_descriptor_v1(),
        "prepared_metric_witness": getattr(
            module, "QMS_PREPARED_METRIC_SUPPORT_V1", None
        ),
        "wheel": wheel.name,
        "wheel_sha256": sha256(wheel.read_bytes()).hexdigest(),
        "extension": extension.name,
        "extension_sha256": sha256(extension.read_bytes()).hexdigest(),
        "installed_baseline_untouched": True,
        "scope": "local Linux CPython candidate, not public release/matrix",
    }
    (output / "build_receipt.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n"
    )
    return extension, proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    extension, proof = build(args.output)
    print(json.dumps(proof, indent=2))
    print(f"QMS04_NATIVE_EXTENSION={extension}")


if __name__ == "__main__":
    main()
