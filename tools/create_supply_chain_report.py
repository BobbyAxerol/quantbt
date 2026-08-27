#!/usr/bin/env python3
"""Create a deterministic local supply-chain and Rust-safety release artifact.

This is intentionally evidence, not a replacement for upstream vulnerability
feeds.  It pins the lockfile fingerprints, enumerates first-party package
metadata, and records the repository-wide unsafe-code policy.  A release CI
job may attach it beside wheel checksums and provenance.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
UNSAFE_BLOCK = re.compile(r"\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)")
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


def _canonical_json_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


def _optional_command(*arguments: str) -> str | None:
    completed = subprocess.run(
        list(arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _build_provenance() -> dict[str, object]:
    """Return local or CI build context without requiring Rust to be installed."""

    rustc_verbose = _optional_command("rustc", "-Vv")
    rustc_fields = {
        key: value.strip()
        for line in (rustc_verbose or "").splitlines()
        if ":" in line
        for key, value in [line.split(":", maxsplit=1)]
    }
    dirty = _optional_command("git", "status", "--porcelain")
    return {
        "git_sha": _optional_command("git", "rev-parse", "HEAD"),
        "git_dirty": bool(dirty) if dirty is not None else None,
        "release_ref": os.environ.get("GITHUB_REF_NAME") or None,
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "rustc": rustc_fields.get("release"),
        "rust_host": rustc_fields.get("host"),
        "native_target": os.environ.get("TARGET") or rustc_fields.get("host"),
        "native_profile": os.environ.get("QUANTBT_NATIVE_BUILD_PROFILE", "release"),
        "native_features": os.environ.get("QUANTBT_NATIVE_FEATURES", ""),
        "cargo_lock_sha256": _sha256(ROOT / "rust" / "Cargo.lock"),
        "product_registry_fingerprint": _canonical_json_fingerprint(PRODUCT_REGISTRY),
        "lifecycle_registry_fingerprint": _canonical_json_fingerprint(LIFECYCLE_REGISTRY),
    }


def _rust_workspace_packages() -> list[dict[str, str]]:
    packages: list[dict[str, str]] = []
    for path in sorted((ROOT / "rust").glob("**/Cargo.toml")):
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        package = payload.get("package")
        if package:
            packages.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "name": str(package["name"]),
                    "version": str(package["version"]),
                    "publish": str(package.get("publish", True)).lower(),
                }
            )
    return packages


def _unsafe_inventory() -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for path in sorted((ROOT / "rust").rglob("*.rs")):
        matches = [index + 1 for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()) if UNSAFE_BLOCK.search(line)]
        if matches:
            inventory.append({"path": str(path.relative_to(ROOT)), "lines": matches})
    return inventory


def build_supply_chain_report() -> dict[str, object]:
    """Return serializable source, lockfile, license, and unsafe-policy evidence."""

    core = _project(ROOT / "pyproject.toml")
    native = _project(ROOT / "rust" / "native_event" / "pyproject.toml")
    product = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    native_release = product["versions"]["native_package"]
    cargo_workspace = tomllib.loads((ROOT / "rust" / "Cargo.toml").read_text(encoding="utf-8"))
    lockfiles = [ROOT / "uv.lock", ROOT / "rust" / "Cargo.lock"]
    unsafe_inventory = _unsafe_inventory()
    unsafe_policy = cargo_workspace["workspace"]["lints"]["rust"]["unsafe_code"]
    if isinstance(unsafe_policy, dict):
        unsafe_policy = unsafe_policy.get("level")
    return {
        "schema": "quantbt-supply-chain-report-v1",
        "core": {
            "distribution": str(core["name"]),
            "version": str(core["version"]),
            "license": str(core["license"]),
            "dependencies": list(core.get("dependencies", [])),
        },
        "native": {
            "distribution": str(native["name"]),
            "version": str(native["version"]),
            "license": str(native["license"]),
            "published": bool(native_release["published"]),
            "release_policy": str(native_release["release_policy"]),
        },
        "lockfiles": [
            {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
            for path in lockfiles
        ],
        "contract_registry": {
            "product_path": str(PRODUCT_REGISTRY.relative_to(ROOT)),
            "product_fingerprint": _canonical_json_fingerprint(PRODUCT_REGISTRY),
            "lifecycle_path": str(LIFECYCLE_REGISTRY.relative_to(ROOT)),
            "lifecycle_fingerprint": _canonical_json_fingerprint(LIFECYCLE_REGISTRY),
        },
        "build_provenance": _build_provenance(),
        "rust_workspace": {
            "license": str(cargo_workspace["workspace"]["package"]["license"]),
            "unsafe_code_policy": str(unsafe_policy),
            "packages": _rust_workspace_packages(),
            "unsafe_inventory": unsafe_inventory,
        },
        "vulnerability_scan": {
            "status": "external_tool_required",
            "recommended_command": "cargo audit --manifest-path rust/Cargo.toml",
            "release_policy": "attach a passing cargo-audit result or an approved exception before publishing quantbt-native",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_supply_chain_report()
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"supply-chain report failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"supply-chain report written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
