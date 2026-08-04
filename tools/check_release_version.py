from __future__ import annotations

import os
from pathlib import Path
import sys
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    payload = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def main() -> int:
    version = _project_version()
    ref_name = os.environ.get("GITHUB_REF_NAME", "")

    if ref_name:
        expected_tag = f"v{version}"
        if ref_name != expected_tag:
            print(
                f"release tag mismatch: GITHUB_REF_NAME={ref_name!r}, "
                f"expected {expected_tag!r} from pyproject.toml",
                file=sys.stderr,
            )
            return 1

    print(f"quantbt-engine version check passed: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
