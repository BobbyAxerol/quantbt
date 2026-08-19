#!/usr/bin/env python3
"""Verify staged core/native wheels without importing source-tree QuantBT.

The verifier has two layers.  It first compares Python production modules in a
core wheel with ``src/quantbt``.  It then creates isolated virtual environments
and imports only the staged artifacts from a temporary working directory.  A
native pair must be an exact pair declared by the generated product registry;
this tool never turns native availability into automatic backend promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = ROOT / "src" / "quantbt"
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _normalized_distribution(name: str) -> str:
    return name.replace("-", "_").replace(".", "_").lower()


def find_artifact(dist: Path, distribution: str, suffix: str) -> Path:
    """Find exactly one staged artifact for the declared distribution."""

    normalized = _normalized_distribution(distribution)
    candidates = sorted(path for path in dist.glob(f"{normalized}-*{suffix}") if path.is_file())
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one {suffix} artifact for {distribution} in {dist}, found {candidates}")
    return candidates[0]


def core_wheel_source_differences(wheel: Path, source: Path = SOURCE_PACKAGE) -> dict[str, list[str]]:
    """Compare every shipped Python module against canonical ``src`` source."""

    expected = {path.relative_to(source).as_posix(): _sha256_bytes(path.read_bytes()) for path in source.rglob("*.py")}
    with zipfile.ZipFile(wheel) as archive:
        actual = {
            name.removeprefix("quantbt/"): _sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.startswith("quantbt/") and name.endswith(".py")
        }
    return {
        "missing": sorted(set(expected) - set(actual)),
        "extra": sorted(set(actual) - set(expected)),
        "drift": sorted(name for name in set(expected) & set(actual) if expected[name] != actual[name]),
    }


def _registry_pair(core_version: str, native_version: str) -> dict[str, Any] | None:
    payload = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    for item in payload["compatibility"]:
        if str(item["core_version"]) == str(core_version) and str(item["native_version"]) == str(native_version):
            return dict(item)
    return None


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({' '.join(command)}):\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def _installed_script(core_version: str, expect_native: bool) -> str:
    native_check = ""
    if expect_native:
        native_check = """
import _quantbt_native
from quantbt.core.product_contracts import require_native_package_pair
pair = require_native_package_pair(
    metadata.version("quantbt-engine"),
    _quantbt_native.version(),
)
assert pair.status == "exact_staged_pair"
assert _quantbt_native.api_version() == "0.4"
"""
    return f"""
import importlib.metadata as metadata
import pathlib
import quantbt

path = pathlib.Path(quantbt.__file__).resolve()
assert "site-packages" in path.parts or "dist-packages" in path.parts, path
assert metadata.version("quantbt-engine") == {core_version!r}
{native_check}
print(path)
"""


def clean_install_smoke(core_artifact: Path, *, core_version: str, native_wheel: Path | None = None) -> None:
    """Install artifacts in a fresh venv and assert imports cannot leak from the repo."""

    with tempfile.TemporaryDirectory(prefix="quantbt-wheel-") as raw:
        root = Path(raw)
        venv = root / "venv"
        env = _clean_env()
        _run([sys.executable, "-m", "venv", str(venv)], cwd=root, env=env)
        python = _venv_python(venv)
        _run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=root, env=env)
        install = [str(python), "-m", "pip", "install", str(core_artifact)]
        if native_wheel is not None:
            install.append(str(native_wheel))
        _run(install, cwd=root, env=env)
        _run([str(python), "-m", "pip", "check"], cwd=root, env=env)
        _run([str(python), "-c", _installed_script(core_version, native_wheel is not None)], cwd=root, env=env)


def verify_staged_wheels(dist: Path, *, require_native: bool, install: bool) -> dict[str, Any]:
    """Return an auditable wheel verification result or raise on a release blocker."""

    registry = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    core_metadata = registry["versions"]["core_package"]
    native_metadata = registry["versions"]["native_package"]
    core_wheel = find_artifact(dist, core_metadata["distribution"], ".whl")
    differences = core_wheel_source_differences(core_wheel)
    if any(differences.values()):
        raise RuntimeError(f"core wheel source hash mismatch: {differences}")
    native_wheel = None
    native_candidates = sorted(dist.glob("quantbt_native-*.whl"))
    if native_candidates:
        if len(native_candidates) != 1:
            raise RuntimeError(f"expected at most one staged native wheel, found {native_candidates}")
        native_wheel = native_candidates[0]
    if require_native and native_wheel is None:
        raise RuntimeError("native wheel required but absent from staged directory")
    pair = None
    if native_wheel is not None:
        pair = _registry_pair(str(core_metadata["version"]), str(native_metadata["version"]))
        if pair is None:
            raise RuntimeError("staged core/native versions are not declared by the product registry")
    if install:
        clean_install_smoke(core_wheel, core_version=str(core_metadata["version"]), native_wheel=native_wheel)
        sdist = find_artifact(dist, core_metadata["distribution"], ".tar.gz")
        clean_install_smoke(sdist, core_version=str(core_metadata["version"]))
    return {
        "schema": "quantbt-staged-wheel-verification-v1",
        "core_wheel": core_wheel.name,
        "native_wheel": native_wheel.name if native_wheel else None,
        "source_hash_parity": not any(differences.values()),
        "native_pair": pair,
        "clean_install": bool(install),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--require-native", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_staged_wheels(
            args.dist.resolve(), require_native=args.require_native, install=not args.skip_install
        )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"staged wheel verification failed: {exc}", file=sys.stderr)
        return 1
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
