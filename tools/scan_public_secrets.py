#!/usr/bin/env python3
"""Scan tracked files for high-confidence credentials and secret paths.

Generic words such as ``token`` or ``password`` are intentionally not treated
as leaks: they occur in documentation and domain schemas. Matches must be
reviewed before release, even when a scanner reports a false positive.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


SECRET_PATH = re.compile(
    r"(^|/)(\.env($|\.)|\.pypirc$|credentials|secrets?)(/|$)|"
    r"\.(pem|key|p12|pfx|jks)$",
    re.IGNORECASE,
)
SECRET_CONTENT = re.compile(
    r"pypi-[A-Za-z0-9_-]{32,}|"
    r"ghp_[A-Za-z0-9]{36,}|"
    r"github_pat_[A-Za-z0-9_]{50,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE,
)


def content_matches(path: str, payload: bytes) -> list[str]:
    """Return high-confidence content/path findings for one tracked file."""

    findings: list[str] = []
    if SECRET_PATH.search(path):
        findings.append(f"secret-like tracked path: {path}")
    text = payload.decode("utf-8", errors="ignore")
    for match in SECRET_CONTENT.finditer(text):
        findings.append(f"credential-like content in {path}: {match.group(0)[:24]}...")
    return findings


def tracked_paths(project_root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    return [
        project_root / raw.decode("utf-8")
        for raw in completed.stdout.split(b"\0")
        if raw
    ]


def scan_tracked_files(project_root: Path) -> list[str]:
    """Scan the current Git index without treating ignored files as public."""

    findings: list[str] = []
    for path in tracked_paths(project_root):
        if path.is_file():
            findings.extend(content_matches(str(path.relative_to(project_root)), path.read_bytes()))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    findings = scan_tracked_files(args.root.resolve())
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("tracked secret scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
