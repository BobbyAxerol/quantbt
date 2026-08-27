#!/usr/bin/env python3
"""Create a deterministic release evidence manifest for wheel/sdist artifacts."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REGISTRY = PROJECT_ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = PROJECT_ROOT / "contracts" / "native_event_contract_registry.json"


def _run_git(*args: str, required: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if required and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            completed.args,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def _project_metadata() -> dict:
    payload = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload["project"]
    return {
        "distribution": str(project["name"]),
        "version": str(project["version"]),
        "python_requires": str(project["requires-python"]),
    }


def _normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _product_distributions() -> tuple[dict, dict]:
    """Return the release core and its declared staged native companion.

    The core package metadata remains the public-release authority. The product
    registry supplies the separately versioned native companion, preserving an
    exact-pair check for both local evidence and public release artifacts.
    """

    core = _project_metadata()
    product = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    versions = product["versions"]
    declared_core = versions["core_package"]
    native = versions["native_package"]
    if (
        core["distribution"] != str(declared_core["distribution"])
        or core["version"] != str(declared_core["version"])
        or core["python_requires"] != str(declared_core["python_requires"])
    ):
        raise RuntimeError("core package metadata differs from the product registry")
    return core, {
        "distribution": str(native["distribution"]),
        "version": str(native["version"]),
        "published": bool(native.get("published", False)),
        "release_policy": str(native.get("release_policy", "unspecified")),
    }


def _native_product_surface(product: dict, native_metadata: dict) -> dict:
    """Summarize the generated native routing contract without over-claiming it.

    A deliberately core-only fallback still resolves ``auto`` to Python. A
    normal supported Linux installation resolves the direct native dependency
    and may auto-promote only the recorded Stage-B workload rows.
    """

    rules = {
        str(item["workload_id"]): item
        for item in product["promotion_policy"]["rules"]
        if bool(item["enabled"])
    }
    auto_rows: list[dict[str, object]] = []
    explicit_rows: list[str] = []
    for workload in sorted(product["workloads"], key=lambda item: str(item["id"])):
        identifier = str(workload["id"])
        if bool(workload["auto_promotion"]):
            rule = rules[identifier]
            auto_rows.append(
                {
                    "workload": identifier,
                    "stage": str(rule["stage"]),
                    "minimum_bars": int(rule["min_bars"]),
                }
            )
        elif str(workload["maturity"]) == "certified":
            explicit_rows.append(identifier)
    return {
        "core_only_auto_backend": "python",
        "supported_linux_auto_backend": "certified_rust_with_exact_companion",
        "native_companion_published": bool(native_metadata["published"]),
        "promotion_table_version": str(product["promotion_policy"]["table_version"]),
        "default_stage": str(product["promotion_policy"]["default_stage"]),
        "automatic_rust_workloads_with_exact_companion": auto_rows,
        "explicit_certified_native_workloads": explicit_rows,
        "rollback_controls": [
            "native_backend='python'",
            "QUANTBT_DISABLE_NATIVE=1",
            "QUANTBT_NATIVE_PROMOTION_MAX=explicit_only",
        ],
    }


def _artifact_kind(path: Path, distributions: tuple[dict, ...]) -> tuple[str, dict]:
    for metadata in distributions:
        normalized = _normalized_distribution(str(metadata["distribution"]))
        version = str(metadata["version"])
        if path.suffix == ".whl" and path.name.startswith(f"{normalized}-{version}-"):
            return "wheel", metadata
        if path.name == f"{normalized}-{version}.tar.gz":
            return "sdist", metadata
    raise RuntimeError(
        "artifact name does not match a declared product distribution/version: "
        f"{path.name}"
    )


def build_manifest(
    dist: Path,
    *,
    require_clean: bool = False,
    supply_chain_report: Path | None = None,
    sbom: Path | None = None,
) -> dict:
    metadata, native_metadata = _product_distributions()
    product = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    distributions = (metadata, native_metadata)
    status = _run_git("status", "--porcelain")
    if require_clean and status:
        raise RuntimeError("release manifest requires a clean Git worktree")

    artifacts = []
    kinds_by_distribution: dict[str, set[str]] = defaultdict(set)
    for path in sorted((*dist.glob("*.whl"), *dist.glob("*.tar.gz"))):
        kind, artifact_metadata = _artifact_kind(path, distributions)
        distribution = str(artifact_metadata["distribution"])
        kinds_by_distribution[distribution].add(kind)
        artifacts.append(
            {
                "name": path.name,
                "kind": kind,
                "distribution": distribution,
                "version": str(artifact_metadata["version"]),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not artifacts:
        raise RuntimeError(f"no release artifacts found in {dist}")
    if not {"wheel", "sdist"}.issubset(kinds_by_distribution[metadata["distribution"]]):
        raise RuntimeError("release manifest requires both a core wheel and a core sdist")
    if native_metadata["distribution"] in kinds_by_distribution and "wheel" not in kinds_by_distribution[native_metadata["distribution"]]:
        raise RuntimeError("a staged native artifact set requires at least one native wheel")

    supply_chain_evidence = None
    if supply_chain_report is not None:
        report_path = supply_chain_report.resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("schema") != "quantbt-supply-chain-report-v1":
            raise RuntimeError("supply-chain report has an unsupported schema")
        supply_chain_evidence = {
            "path": _display_path(report_path),
            "sha256": _sha256(report_path),
            "schema": str(report["schema"]),
            "unsafe_code_policy": str(report["rust_workspace"]["unsafe_code_policy"]),
            "unsafe_inventory_count": len(report["rust_workspace"]["unsafe_inventory"]),
            "build_provenance": dict(report["build_provenance"]),
        }

    sbom_evidence = None
    if sbom is not None:
        sbom_path = sbom.resolve()
        sbom_payload = json.loads(sbom_path.read_text(encoding="utf-8"))
        if sbom_payload.get("bomFormat") != "CycloneDX":
            raise RuntimeError("SBOM does not declare CycloneDX format")
        sbom_evidence = {
            "path": _display_path(sbom_path),
            "sha256": _sha256(sbom_path),
            "bom_format": str(sbom_payload["bomFormat"]),
            "spec_version": str(sbom_payload.get("specVersion", "")),
        }

    benchmark_files = []
    for relative in (
        "benchmarks/native_event/results/phase48e1/after.json",
        "benchmarks/native_event/results/phase48e1/after.md",
        "benchmarks/native_event/results/phase54a5/exit_gate.json",
        "benchmarks/native_event/results/phase54b2/public_routes.json",
        "benchmarks/native_event/results/phase54b3/portfolio_package.json",
    ):
        path = PROJECT_ROOT / relative
        if path.is_file():
            benchmark_files.append({"path": relative, "sha256": _sha256(path)})

    return {
        "schema": "quantbt-release-manifest-v1",
        **metadata,
        "git_sha": _run_git("rev-parse", "HEAD"),
        "git_ref": _run_git(
            "symbolic-ref", "--short", "-q", "HEAD", required=False
        ) or None,
        "release_ref": os.environ.get("GITHUB_REF_NAME") or None,
        "working_tree_clean": not bool(status),
        "backend_policy": {
            "auto": "certified_rust_with_exact_linux_companion; python_fallback_elsewhere",
            "native_extra": "compatibility_alias; direct_platform_dependency",
            "rust": "explicit_capability_gated",
        },
        "native_product_surface": _native_product_surface(product, native_metadata),
        "product_contract": {
            "registry": str(PRODUCT_REGISTRY.relative_to(PROJECT_ROOT)),
            "product_registry_fingerprint": _canonical_json_fingerprint(PRODUCT_REGISTRY),
            "lifecycle_registry": str(LIFECYCLE_REGISTRY.relative_to(PROJECT_ROOT)),
            "lifecycle_registry_fingerprint": _canonical_json_fingerprint(LIFECYCLE_REGISTRY),
            "declared_core_native_pair": {
                "core_distribution": metadata["distribution"],
                "core_version": metadata["version"],
                "native_distribution": native_metadata["distribution"],
                "native_version": native_metadata["version"],
                "native_published": native_metadata["published"],
                "native_release_policy": native_metadata["release_policy"],
            },
        },
        "artifact_sets": {
            distribution: {
                "version": str(next(item["version"] for item in distributions if item["distribution"] == distribution)),
                "kinds": sorted(kinds),
                "artifact_count": sum(1 for item in artifacts if item["distribution"] == distribution),
                "published": bool(next(item.get("published", True) for item in distributions if item["distribution"] == distribution)),
            }
            for distribution, kinds in sorted(kinds_by_distribution.items())
        },
        "artifacts": artifacts,
        "benchmark_evidence": benchmark_files,
        "supply_chain_evidence": supply_chain_evidence,
        "sbom_evidence": sbom_evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--supply-chain-report", type=Path)
    parser.add_argument("--sbom", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(
            args.dist.resolve(),
            require_clean=args.require_clean,
            supply_chain_report=args.supply_chain_report,
            sbom=args.sbom,
        )
    except (OSError, RuntimeError, json.JSONDecodeError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"release manifest failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"release manifest written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
