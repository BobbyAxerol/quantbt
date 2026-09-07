#!/usr/bin/env python3
"""Capture the Phase 56 clean core/native installed-wheel baseline.

The heavy lifting remains in ``tools/certify_native_release.py``.  This thin
wrapper writes a stable, V1.1-scoped record so later Rust-primary phases can
compare their installed-wheel route selection and packaging behavior against a
known pair without reinterpreting an older release certificate.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"
PYPROJECT = ROOT / "pyproject.toml"
ENDPOINT_SOURCE = ROOT / "src" / "quantbt" / "endpoint.py"
MEASUREMENT_MODULE = ROOT / "src" / "quantbt" / "benchmarks" / "v1_1_measurement.py"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "baselines" / "v1_1_installed_wheel_baseline.json"


def _canonical_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _source_fingerprint(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def capture_installed_wheel_baseline(dist: Path, *, python: Path) -> dict[str, Any]:
    """Run the existing clean-wheel certifier and normalize V1.1 evidence."""

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.certify_native_release import certify_release

    certificate = certify_release(dist.resolve(), python=python.resolve())
    product = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    lifecycle = json.loads(LIFECYCLE_REGISTRY.read_text(encoding="utf-8"))
    versions = product["versions"]
    return {
        "schema": "quantbt-rust-primary-v1_1-installed-wheel-baseline-v1",
        "baseline_id": "rust_primary_v1_1_phase0",
        "core_distribution": {
            "name": versions["core_package"]["distribution"],
            "version": str(versions["core_package"]["version"]),
        },
        "native_distribution": {
            "name": versions["native_package"]["distribution"],
            "version": str(versions["native_package"]["version"]),
        },
        "product_registry_fingerprint": _canonical_fingerprint(product),
        "lifecycle_registry_fingerprint": _canonical_fingerprint(lifecycle),
        "source_fingerprints": {
            "pyproject": _source_fingerprint(PYPROJECT),
            "endpoint": _source_fingerprint(ENDPOINT_SOURCE),
            "measurement_contract_module": _source_fingerprint(MEASUREMENT_MODULE),
            "product_registry": _source_fingerprint(PRODUCT_REGISTRY),
            "lifecycle_registry": _source_fingerprint(LIFECYCLE_REGISTRY),
        },
        "host": certificate["host"],
        "source_revision": {
            "git_sha": certificate["git_sha"],
            "git_ref": certificate["git_ref"],
        },
        "artifacts": certificate["artifacts"],
        "wheel_verification": certificate["wheel_verification"],
        "installed_wheel": certificate["installed_wheel"],
        "route_observations": {
            "core_only_auto_backend": certificate["installed_wheel"]["core_only"]["auto_reason_without_native"],
            "core_only_disabled_backend": certificate["installed_wheel"]["core_only"]["disabled_reason"],
            "exact_pair_static_auto_backend": certificate["installed_wheel"]["exact_pair"]["static_auto_reason"],
            "exact_pair_native_api": str(product["runtime_descriptor"]["native_api"]),
        },
        "tested_contract": {
            "certifier": "tools/certify_native_release.py",
            "source_test_subset": "tools/run_test_shards.py --profile release",
            "import_boundary": "fresh venvs without repository PYTHONPATH or active Poetry environment",
            "claims": [
                "core-only fallback imports from site-packages and resolves auto to Python",
                "the exact core/native pair imports from site-packages and completes the governed public route probes",
                "this record is a V1.1 baseline, not a new endpoint promotion",
            ],
        },
        "certificate_fingerprint": _canonical_fingerprint(certificate),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True, help="staged core wheel, sdist, and native wheel directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args(argv)
    try:
        payload = capture_installed_wheel_baseline(args.dist, python=args.python)
    except (KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"V1.1 installed-wheel baseline failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"V1.1 installed-wheel baseline written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
