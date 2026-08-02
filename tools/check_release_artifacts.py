#!/usr/bin/env python3
"""Inspect wheel/sdist members before a public package upload."""

from __future__ import annotations

import argparse
from pathlib import Path
import posixpath
import re
import sys
import tarfile
import zipfile


SUSPICIOUS_PATH = re.compile(
    r"(^|/)(\.env($|\.)|\.pypirc$|credentials|secrets?)(/|$)|"
    r"\.(pem|key|p12|pfx|jks)$",
    re.IGNORECASE,
)
CORE_WHEEL_MEMBER = re.compile(r"^quantbt_engine-[^/]+\.dist-info/")


def _path_findings(name: str) -> list[str]:
    normalized = name.replace("\\", "/")
    findings: list[str] = []
    if normalized.startswith("/") or ".." in posixpath.normpath(normalized).split("/"):
        findings.append(f"unsafe archive path: {name}")
    if SUSPICIOUS_PATH.search(normalized):
        findings.append(f"secret-like archive path: {name}")
    return findings


def inspect_artifact(path: Path) -> list[str]:
    """Return findings for one core wheel or source distribution."""

    findings: list[str] = []
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                findings.extend(f"{path.name}: {item}" for item in _path_findings(name))
                normalized = name.replace("\\", "/")
                if not (normalized.startswith("quantbt/") or CORE_WHEEL_MEMBER.match(normalized)):
                    findings.append(f"{path.name}: non-core wheel member: {name}")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                findings.extend(f"{path.name}: {item}" for item in _path_findings(member.name))
    else:
        findings.append(f"unsupported artifact type: {path}")
    return findings


def inspect_dist(dist: Path) -> list[str]:
    artifacts = sorted((*dist.glob("*.whl"), *dist.glob("*.tar.gz")))
    if not artifacts:
        return [f"no wheel or sdist artifacts found in {dist}"]
    findings: list[str] = []
    for artifact in artifacts:
        findings.extend(inspect_artifact(artifact))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args(argv)
    findings = inspect_dist(args.dist.resolve())
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("release artifact allowlist/secret-path gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
