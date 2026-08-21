#!/usr/bin/env python3
"""Fail CI when repository-relative Markdown links in documentation drift."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def _target(raw: str) -> str:
    value = raw.strip().strip("<>")
    return value.split("#", maxsplit=1)[0]


def validate_links(root: Path) -> list[str]:
    """Return deterministic missing local link findings for ``root`` Markdown."""

    violations: list[str] = []
    for path in sorted(root.rglob("*.md")):
        for raw in LINK.findall(path.read_text(encoding="utf-8")):
            target = _target(raw)
            if not target or target.startswith(EXTERNAL_PREFIXES):
                continue
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                violations.append(f"{path.relative_to(ROOT)}: missing link target {raw!r}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", type=Path, default=ROOT / "docs")
    args = parser.parse_args(argv)
    try:
        violations = validate_links(args.docs_root.resolve())
    except OSError as exc:
        print(f"documentation link check failed: {exc}", file=sys.stderr)
        return 1
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("documentation link gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
