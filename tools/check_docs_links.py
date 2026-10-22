#!/usr/bin/env python3
"""Fail CI when repository-relative Markdown links in documentation drift."""

from __future__ import annotations

import argparse
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:")


def _target(raw: str) -> str:
    value = raw.strip().strip("<>")
    return value.split("#", maxsplit=1)[0]


def visible_markdown(text: str) -> str:
    """Exclude fenced examples and HTML comments from repository link checks."""
    visible, fence = [], None
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match:
            fence = match[1]
        else:
            visible.append(line)
    return "\n".join(visible)


class ExplicitAnchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and (key == "id" or tag == "a" and key == "name"):
                self.ids.add(value)


def markdown_anchors(text: str) -> set[str]:
    text = visible_markdown(text)
    parser = ExplicitAnchors()
    parser.feed(text)
    anchors, counts = set(parser.ids), {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        title = heading[1] if heading else None
        if title is None and i + 1 < len(lines) and line.strip() and re.match(r"^ {0,3}(=+|-+)\s*$", lines[i + 1]):
            title = line.strip()
        if title is None:
            continue
        title = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", title)
        title = unescape(re.sub(r"<[^>]+>", "", title)).replace("`", "")
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        candidate = slug
        while candidate in counts:
            counts[slug] = counts.get(slug, 0) + 1
            candidate = f"{slug}-{counts[slug]}"
        counts[candidate] = 0
        anchors.add(candidate)
    return anchors


def validate_links(root: Path, *, check_anchors: bool = False, files=None) -> list[str]:
    """Return deterministic missing local link findings for ``root`` Markdown."""

    violations: list[str] = []
    targets = sorted(root.rglob("*.md")) if files is None else sorted(set(files))
    cache = {}
    for path in targets:
        label = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        for raw in LINK.findall(visible_markdown(path.read_text(encoding="utf-8"))):
            target = _target(raw)
            if raw.startswith(EXTERNAL_PREFIXES):
                continue
            if not target and not check_anchors:
                continue
            candidate = (path.parent / unquote(target)).resolve() if target else path.resolve()
            if not candidate.exists():
                violations.append(f"{label}: missing link target {raw!r}")
            elif check_anchors and candidate.suffix == ".md" and "#" in raw:
                fragment = unquote(urlsplit(raw).fragment)
                if candidate not in cache:
                    cache[candidate] = markdown_anchors(candidate.read_text(encoding="utf-8"))
                if fragment and fragment not in cache[candidate]:
                    violations.append(f"{label}: missing Markdown anchor {raw!r}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", type=Path, default=ROOT / "docs")
    parser.add_argument("--check-anchors", action="store_true", help="Also validate local Markdown fragments")
    parser.add_argument("--file", type=Path, action="append", help="Scope to named Markdown files (repeatable)")
    args = parser.parse_args(argv)
    try:
        violations = validate_links(args.docs_root.resolve(), check_anchors=args.check_anchors,
                                    files=None if args.file is None else [p.resolve() for p in args.file])
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
