#!/usr/bin/env python3
"""Inspect wheel/sdist members before a public package upload."""

from __future__ import annotations

import argparse
from hashlib import sha256
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
PRIVATE_ARCHIVE_PATH = re.compile(
    r"(^|/)(upgrade/(private|local|drafts|alphas)|data/(raw|private|local)|"
    r"benchmarks/(local|tmp|profiles)|artifacts/(local|tmp)|\.git|\.venv|"
    r"__pycache__|\.pytest_cache)(/|$)",
    re.IGNORECASE,
)
BUILD_ARTIFACT = re.compile(
    r"(\.py[cod]|\.pyo|\.prof|\.lprof|\.memray|\.flamegraph\.svg|"
    r"\.so|\.pyd|\.dylib)$",
    re.IGNORECASE,
)
CORE_WHEEL_MEMBER = re.compile(r"^quantbt_engine-[^/]+\.dist-info/")
NATIVE_WHEEL_MEMBER = re.compile(r"^quantbt_native-[^/]+\.dist-info/")
NATIVE_EXTENSION_MEMBER = re.compile(
    r"^_quantbt_native/_quantbt_native(?:\.[^/]+)?\.(?:so|pyd|dylib)$",
    re.IGNORECASE,
)
NATIVE_PACKAGE_INIT = re.compile(r"^_quantbt_native/__init__\.py$", re.IGNORECASE)
SECRET_CONTENT = re.compile(
    r"pypi-[A-Za-z0-9_-]{32,}|"
    r"ghp_[A-Za-z0-9]{36,}|"
    r"github_pat_[A-Za-z0-9_]{50,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE,
)


def _path_findings(name: str) -> list[str]:
    normalized = name.replace("\\", "/")
    findings: list[str] = []
    if normalized.startswith("/") or ".." in posixpath.normpath(normalized).split("/"):
        findings.append(f"unsafe archive path: {name}")
    if SUSPICIOUS_PATH.search(normalized):
        findings.append(f"secret-like archive path: {name}")
    if PRIVATE_ARCHIVE_PATH.search(normalized):
        findings.append(f"private/local archive path: {name}")
    if BUILD_ARTIFACT.search(normalized):
        findings.append(f"build/profiling artifact: {name}")
    return findings


def _content_findings(path: Path, name: str, payload: bytes, private_payload_hashes=frozenset()) -> list[str]:
    if not payload:
        return []
    if sha256(payload).hexdigest() in private_payload_hashes:
        return [f"{path.name}: private research payload in {name}"]
    match = SECRET_CONTENT.search(payload.decode("utf-8", errors="ignore"))
    if match is None:
        return []
    return [f"{path.name}: credential-like content in {name}: {match.group(0)[:24]}..."]


def _wheel_kind(path: Path) -> str | None:
    name = path.name.lower()
    if name.startswith("quantbt_engine-"):
        return "core"
    if name.startswith("quantbt_native-"):
        return "native"
    return None


def inspect_artifact(path: Path, *, private_payload_hashes=frozenset()) -> list[str]:
    """Return allowlist/secret findings for one core or native artifact."""

    findings: list[str] = []
    if path.suffix == ".whl":
        kind = _wheel_kind(path)
        if kind is None:
            return [f"unsupported wheel distribution: {path.name}"]
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                path_findings = _path_findings(name)
                normalized = name.replace("\\", "/")
                if kind == "native" and NATIVE_EXTENSION_MEMBER.match(normalized):
                    path_findings = [item for item in path_findings if "build/profiling artifact" not in item]
                findings.extend(f"{path.name}: {item}" for item in path_findings)
                if kind == "core":
                    allowed = normalized.startswith("quantbt/") or CORE_WHEEL_MEMBER.match(normalized)
                    label = "non-core wheel member"
                else:
                    allowed = bool(
                        NATIVE_EXTENSION_MEMBER.match(normalized)
                        or NATIVE_PACKAGE_INIT.match(normalized)
                        or NATIVE_WHEEL_MEMBER.match(normalized)
                    )
                    label = "non-native wheel member"
                if not allowed:
                    findings.append(f"{path.name}: {label}: {name}")
                item = archive.getinfo(name)
                if not item.is_dir() and item.file_size <= 4 * 1024 * 1024:
                    findings.extend(_content_findings(path, name, archive.read(name), private_payload_hashes))
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                findings.extend(f"{path.name}: {item}" for item in _path_findings(member.name))
                if member.isfile() and member.size <= 4 * 1024 * 1024:
                    extracted = archive.extractfile(member)
                    if extracted is not None:
                        findings.extend(_content_findings(path, member.name, extracted.read(), private_payload_hashes))
    else:
        findings.append(f"unsupported artifact type: {path}")
    return findings


def inspect_dist(dist: Path, *, private_payload_hashes=frozenset()) -> list[str]:
    artifacts = sorted((*dist.glob("*.whl"), *dist.glob("*.tar.gz")))
    if not artifacts:
        return [f"no wheel or sdist artifacts found in {dist}"]
    findings: list[str] = []
    for artifact in artifacts:
        findings.extend(inspect_artifact(artifact, private_payload_hashes=private_payload_hashes))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--private-source-root", type=Path,
                        help="Optional local-only exact-payload denylist; never emits private code")
    args = parser.parse_args(argv)
    private_hashes = frozenset()
    if args.private_source_root is not None:
        root = args.private_source_root
        if not root.is_dir() or root.is_symlink():
            parser.error("private source root must be an existing regular directory")
        sources = list(root.rglob("*.py"))
        if not sources or any(path.is_symlink() for path in sources):
            parser.error("private source inventory must contain regular Python files")
        private_hashes = frozenset(sha256(path.read_bytes()).hexdigest() for path in sources)
    findings = inspect_dist(args.dist.resolve(), private_payload_hashes=private_hashes)
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("release artifact allowlist/secret-path gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
