#!/usr/bin/env python3
"""Create a deterministic release evidence manifest for wheel/sdist artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _artifact_kind(path: Path, metadata: dict) -> str:
    normalized = _normalized_distribution(metadata["distribution"])
    version = metadata["version"]
    if path.suffix == ".whl" and path.name.startswith(f"{normalized}-{version}-"):
        return "wheel"
    if path.name == f"{normalized}-{version}.tar.gz":
        return "sdist"
    raise RuntimeError(
        "artifact name does not match the current distribution/version: "
        f"{path.name}"
    )


def build_manifest(dist: Path, *, require_clean: bool = False) -> dict:
    metadata = _project_metadata()
    status = _run_git("status", "--porcelain")
    if require_clean and status:
        raise RuntimeError("release manifest requires a clean Git worktree")

    artifacts = []
    for path in sorted((*dist.glob("*.whl"), *dist.glob("*.tar.gz"))):
        kind = _artifact_kind(path, metadata)
        artifacts.append(
            {
                "name": path.name,
                "kind": kind,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not artifacts:
        raise RuntimeError(f"no release artifacts found in {dist}")
    kinds = {item["kind"] for item in artifacts}
    if not {"wheel", "sdist"}.issubset(kinds):
        raise RuntimeError("release manifest requires both a wheel and an sdist")

    benchmark_files = []
    for relative in (
        "benchmarks/native_event/results/phase48e1/after.json",
        "benchmarks/native_event/results/phase48e1/after.md",
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
            "auto": "python",
            "native_extra": "empty",
            "rust": "explicit_experimental",
        },
        "artifacts": artifacts,
        "benchmark_evidence": benchmark_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(args.dist.resolve(), require_clean=args.require_clean)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"release manifest failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"release manifest written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
