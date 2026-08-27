#!/usr/bin/env python3
"""Validate the wheel-only public artifact contract for ``quantbt-native``.

The native companion is intentionally published as pre-built manylinux wheels
only. This prevents a normal core installation from silently falling back to a
local Rust/Maturin build on an unsupported machine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NATIVE_PYPROJECT = ROOT / "rust" / "native_event" / "pyproject.toml"
CORE_PYPROJECT = ROOT / "pyproject.toml"
SUPPORTED_PYTHON_TAGS = frozenset({"cp311", "cp312", "cp313"})
MANYLINUX_X86_64_TAGS = frozenset({"manylinux2014_x86_64", "manylinux_2_17_x86_64"})


def _native_version() -> str:
    payload = tomllib.loads(NATIVE_PYPROJECT.read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def _core_version() -> str:
    payload = tomllib.loads(CORE_PYPROJECT.read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def _metadata_value(payload: bytes, key: str) -> str | None:
    prefix = f"{key}:".lower()
    for raw_line in payload.decode("utf-8", errors="replace").splitlines():
        if raw_line.lower().startswith(prefix):
            return raw_line.split(":", 1)[1].strip()
    return None


def _metadata_values(payload: bytes, key: str) -> list[str]:
    prefix = f"{key}:".lower()
    return [
        raw_line.split(":", 1)[1].strip()
        for raw_line in payload.decode("utf-8", errors="replace").splitlines()
        if raw_line.lower().startswith(prefix)
    ]


def _expected_tag(version: str) -> str:
    pieces = version.split(".")
    if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
        raise ValueError(f"expected CPython version like '3.12', got {version!r}")
    return f"cp{pieces[0]}{pieces[1]}"


def _wheel_parts(path: Path) -> tuple[str, str, str, str]:
    if path.suffix != ".whl":
        raise ValueError(f"not a wheel: {path.name}")
    parts = path.stem.rsplit("-", 3)
    if len(parts) != 4:
        raise ValueError(f"invalid wheel filename: {path.name}")
    return tuple(parts)  # type: ignore[return-value]


def inspect_core_native_dependency(core_wheel: Path) -> dict[str, object]:
    """Verify the public core wheel declares the exact native companion.

    This intentionally reads built wheel metadata rather than trusting the
    source ``pyproject.toml``. A staged pair can otherwise pass when the native
    wheel was preinstalled even if the core wheel silently lost its dependency.
    """

    wheel = core_wheel.resolve()
    if wheel.suffix != ".whl":
        raise ValueError(f"core artifact is not a wheel: {wheel.name}")
    expected_core = _core_version()
    expected_native = _native_version()
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            raise ValueError(f"{wheel.name}: missing core METADATA")
        metadata = archive.read(metadata_name)

    if _metadata_value(metadata, "Name") != "quantbt-engine":
        raise ValueError(f"{wheel.name}: METADATA Name must be quantbt-engine")
    if _metadata_value(metadata, "Version") != expected_core:
        raise ValueError(f"{wheel.name}: METADATA Version must be {expected_core}")

    native_requirements = [
        requirement
        for requirement in _metadata_values(metadata, "Requires-Dist")
        if requirement.lower().startswith("quantbt-native")
    ]
    if len(native_requirements) != 1:
        raise ValueError(
            f"{wheel.name}: expected exactly one quantbt-native Requires-Dist entry, got {native_requirements}"
        )
    requirement = native_requirements[0]
    normalized = requirement.lower().replace(" ", "").replace('"', "'")
    expected_prefix = f"quantbt-native=={expected_native};"
    if not normalized.startswith(expected_prefix):
        raise ValueError(f"{wheel.name}: native requirement must start with {expected_prefix!r}, got {requirement!r}")
    for marker in (
        "sys_platform=='linux'",
        "platform_machine=='x86_64'",
        "implementation_name=='cpython'",
        "python_version>='3.11'",
        "python_version<'3.14'",
    ):
        if marker not in normalized:
            raise ValueError(f"{wheel.name}: native requirement missing marker {marker!r}")
    return {
        "core_wheel": wheel.name,
        "core_version": expected_core,
        "native_version": expected_native,
        "requires_dist": requirement,
    }


def inspect_native_wheels(
    dist: Path,
    *,
    expected_python_version: str | None = None,
    require_full_matrix: bool = False,
    core_wheel: Path | None = None,
) -> dict[str, object]:
    """Validate native wheel names, tags, metadata, and extension members.

    ``dist`` must contain native wheels only. A native sdist is a release
    blocker because it could make a user compile Rust during installation.
    """

    directory = dist.resolve()
    expected_version = _native_version()
    expected_tag = _expected_tag(expected_python_version) if expected_python_version else None
    errors: list[str] = []
    source_artifacts = sorted(path.name for path in directory.glob("quantbt_native-*.tar.gz"))
    if source_artifacts:
        errors.append(f"native source distributions are forbidden: {source_artifacts}")

    wheels = sorted(path for path in directory.glob("quantbt_native-*.whl") if path.is_file())
    if not wheels:
        errors.append(f"no quantbt-native wheel found in {directory}")

    observed_python_tags: set[str] = set()
    reports: list[dict[str, object]] = []
    for wheel in wheels:
        distribution_version, python_tag, abi_tag, platform_tag = _wheel_parts(wheel)
        observed_python_tags.add(python_tag)
        if distribution_version != f"quantbt_native-{expected_version}":
            errors.append(
                f"{wheel.name}: expected quantbt_native-{expected_version}, got {distribution_version}"
            )
        if python_tag not in SUPPORTED_PYTHON_TAGS:
            errors.append(f"{wheel.name}: unsupported CPython tag {python_tag}")
        if abi_tag != python_tag:
            errors.append(f"{wheel.name}: ABI tag {abi_tag} must exactly match {python_tag}")
        if expected_tag is not None and python_tag != expected_tag:
            errors.append(f"{wheel.name}: expected {expected_tag}, got {python_tag}")
        platform_tags = set(platform_tag.split("."))
        if not MANYLINUX_X86_64_TAGS.intersection(platform_tags):
            errors.append(f"{wheel.name}: missing manylinux_2_17/manylinux2014 x86_64 tag")

        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
            wheel_name = next((name for name in names if name.endswith(".dist-info/WHEEL")), None)
            extension_names = [
                name
                for name in names
                if name.startswith("_quantbt_native/_quantbt_native") and name.endswith(".so")
            ]
            if "_quantbt_native/__init__.py" not in names:
                errors.append(f"{wheel.name}: missing _quantbt_native package initializer")
            if not extension_names:
                errors.append(f"{wheel.name}: missing compiled _quantbt_native extension")
            if metadata_name is None or wheel_name is None:
                errors.append(f"{wheel.name}: missing wheel metadata")
            else:
                metadata = archive.read(metadata_name)
                wheel_metadata = archive.read(wheel_name).decode("utf-8", errors="replace")
                if _metadata_value(metadata, "Name") != "quantbt-native":
                    errors.append(f"{wheel.name}: METADATA Name must be quantbt-native")
                if _metadata_value(metadata, "Version") != expected_version:
                    errors.append(f"{wheel.name}: METADATA Version must be {expected_version}")
                expected_wheel_prefix = f"Tag: {python_tag}-{abi_tag}-"
                if not any(line.startswith(expected_wheel_prefix) for line in wheel_metadata.splitlines()):
                    errors.append(f"{wheel.name}: WHEEL metadata lacks {expected_wheel_prefix} tag")
                if "manylinux" not in wheel_metadata:
                    errors.append(f"{wheel.name}: WHEEL metadata lacks a manylinux tag")

        reports.append(
            {
                "filename": wheel.name,
                "python_tag": python_tag,
                "abi_tag": abi_tag,
                "platform_tag": platform_tag,
            }
        )

    if require_full_matrix and observed_python_tags != SUPPORTED_PYTHON_TAGS:
        errors.append(
            "missing/extra native wheel Python tags: "
            f"expected={sorted(SUPPORTED_PYTHON_TAGS)}, observed={sorted(observed_python_tags)}"
        )
    if errors:
        raise ValueError("\n".join(errors))
    report: dict[str, object] = {
        "schema": "quantbt-native-wheel-contract-v1",
        "native_version": expected_version,
        "wheel_only": True,
        "manylinux_x86_64": True,
        "expected_python_version": expected_python_version,
        "observed_python_tags": sorted(observed_python_tags),
        "wheels": reports,
    }
    if core_wheel is not None:
        report["core_native_dependency"] = inspect_core_native_dependency(core_wheel)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--expected-python-version")
    parser.add_argument("--require-full-matrix", action="store_true")
    parser.add_argument("--core-wheel", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect_native_wheels(
            args.dist,
            expected_python_version=args.expected_python_version,
            require_full_matrix=args.require_full_matrix,
            core_wheel=args.core_wheel,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"native wheel contract failed: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
