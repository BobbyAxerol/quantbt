#!/usr/bin/env python3
"""Enforce the QuantBT dev/TestPyPI and main/PyPI release channels.

TestPyPI is reserved for an ``rc`` tag at the exact current ``origin/dev``
commit. Production PyPI is reserved for a final tag at the exact current
``origin/main`` commit. Keeping this check in CI prevents a final main release
from accidentally travelling through the research channel, or an RC from being
published as production.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Literal


ROOT = Path(__file__).resolve().parents[1]
Channel = Literal["testpypi", "pypi"]


def resolve_channel(channel: str, release_ref: str) -> Channel:
    """Resolve ``auto`` from an RC tag or validate an explicit channel."""

    normalized = str(channel).strip().lower()
    if normalized == "auto":
        normalized = "testpypi" if "rc" in release_ref.lower() else "pypi"
    if normalized not in {"testpypi", "pypi"}:
        raise ValueError("channel must be auto, testpypi, or pypi")
    return normalized  # type: ignore[return-value]


def validate_release_channel(
    channel: Channel,
    release_ref: str,
    *,
    release_commit: str,
    branch_commit: str,
) -> dict[str, str]:
    """Validate a channel's tag shape and exact branch-tip provenance."""

    reference = str(release_ref).strip()
    if not reference.startswith("v"):
        raise ValueError(f"release ref must be a version tag beginning with 'v', got {reference!r}")
    is_rc = "rc" in reference.lower()
    expected_branch = "dev" if channel == "testpypi" else "main"
    if channel == "testpypi" and not is_rc:
        raise ValueError("TestPyPI releases require an RC tag from dev, for example v1.1.0rc1")
    if channel == "pypi" and is_rc:
        raise ValueError("PyPI releases require a final non-RC tag from main")
    if release_commit != branch_commit:
        raise ValueError(
            f"{channel} release tag {reference} must point to the current origin/{expected_branch} tip: "
            f"tag={release_commit}, origin/{expected_branch}={branch_commit}"
        )
    return {
        "channel": channel,
        "release_ref": reference,
        "branch": expected_branch,
        "commit": release_commit,
    }


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(arguments)} failed")
    return completed.stdout.strip()


def _fetch_branch(branch: str) -> None:
    completed = subprocess.run(
        ["git", "fetch", "--no-tags", "origin", f"{branch}:refs/remotes/origin/{branch}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"could not fetch origin/{branch}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=("auto", "testpypi", "pypi"), required=True)
    parser.add_argument("--release-ref", required=True)
    args = parser.parse_args(argv)
    try:
        channel = resolve_channel(args.channel, args.release_ref)
        branch = "dev" if channel == "testpypi" else "main"
        _fetch_branch(branch)
        report = validate_release_channel(
            channel,
            args.release_ref,
            release_commit=_git("rev-parse", f"{args.release_ref}^{{commit}}"),
            branch_commit=_git("rev-parse", f"origin/{branch}"),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"release channel validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
