#!/usr/bin/env python3
"""Synchronize the explicit root/source compatibility mirror.

The direction is mandatory. The tool never merges both trees and never
deletes an unknown root-only file. An extra root file is reported by the final
check so it can be reviewed and removed or added intentionally.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

from source_mirror_manifest import (
    CANONICAL_ROOT,
    PROJECT_ROOT,
    canonical_files,
    format_differences,
    mirror_differences,
    mirror_files,
)


def _copy_files(source: dict[Path, Path], destination_root: Path) -> int:
    copied = 0
    for relative, path in sorted(source.items()):
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    directions = parser.add_mutually_exclusive_group(required=True)
    directions.add_argument("--src-to-root", action="store_true")
    directions.add_argument("--root-to-src", action="store_true")
    directions.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        differences = mirror_differences(PROJECT_ROOT)
        print(format_differences(differences))
        return 0 if not any(differences.values()) else 1

    if args.src_to_root:
        copied = _copy_files(
            canonical_files(PROJECT_ROOT),
            PROJECT_ROOT,
        )
        direction = "src/quantbt -> root"
    else:
        copied = _copy_files(
            mirror_files(PROJECT_ROOT),
            CANONICAL_ROOT,
        )
        direction = "root -> src/quantbt"

    differences = mirror_differences(PROJECT_ROOT)
    print(f"copied {copied} files ({direction})")
    print(format_differences(differences))
    if any(differences.values()):
        print(
            "mirror sync stopped with reviewed differences; no unknown files "
            "were deleted",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
