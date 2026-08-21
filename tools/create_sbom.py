#!/usr/bin/env python3
"""Create a deterministic CycloneDX-style SBOM for QuantBT release evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _python_dependency_component(requirement: str) -> dict[str, Any]:
    name = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip()
    return {
        "type": "library",
        "name": name,
        "version": "declared-range",
        "properties": [{"name": "quantbt:declared_requirement", "value": requirement}],
    }


def build_sbom() -> dict[str, Any]:
    """Return a deterministic SBOM from package manifests and lockfiles."""

    core = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    native = tomllib.loads((ROOT / "rust" / "native_event" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    cargo_lock = tomllib.loads((ROOT / "rust" / "Cargo.lock").read_text(encoding="utf-8"))
    components: list[dict[str, Any]] = [
        {
            "type": "library",
            "name": str(core["name"]),
            "version": str(core["version"]),
            "licenses": [{"license": {"id": str(core["license"])}}],
        },
        {
            "type": "library",
            "name": str(native["name"]),
            "version": str(native["version"]),
            "licenses": [{"license": {"id": str(native["license"])}}],
            "properties": [{"name": "quantbt:published", "value": "false"}],
        },
    ]
    components.extend(_python_dependency_component(str(item)) for item in core.get("dependencies", []))
    for package in cargo_lock.get("package", []):
        name = str(package["name"])
        version = str(package["version"])
        if name.startswith("quantbt-"):
            continue
        component: dict[str, Any] = {"type": "library", "name": name, "version": version}
        if package.get("source"):
            component["purl"] = f"pkg:cargo/{name}@{version}"
        components.append(component)
    components.sort(key=lambda item: (str(item["name"]), str(item["version"])))

    identity = f"{core['name']}@{core['version']}|{native['name']}@{native['version']}"
    digest = sha256(identity.encode("utf-8")).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": (
            "urn:uuid:"
            f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"
        ),
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": str(core["name"]),
                "version": str(core["version"]),
            }
        },
        "components": components,
        "properties": [
            {"name": "quantbt:product_registry_fingerprint", "value": _canonical_fingerprint(PRODUCT_REGISTRY)},
            {"name": "quantbt:uv_lock_sha256", "value": _sha256(ROOT / "uv.lock")},
            {"name": "quantbt:cargo_lock_sha256", "value": _sha256(ROOT / "rust" / "Cargo.lock")},
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = build_sbom()
    except (OSError, KeyError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"SBOM generation failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"SBOM written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
