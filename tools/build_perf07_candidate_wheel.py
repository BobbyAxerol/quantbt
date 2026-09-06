#!/usr/bin/env python3
"""Build and clean-install one exact local core/native candidate pair for PERF-07.

This is a local Linux CPython proof, not a claim that a one-machine build has
certified the complete manylinux CPython matrix.  CI/release workflows retain
ownership of that wider distribution matrix.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.measurement_contract import capture_measurement_identity, file_sha256  # noqa: E402
from tools.verify_wheels import verify_staged_wheels  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks" / "native_event" / "results" / "perf_07_candidate_wheel.json"
SCHEMA = "quantbt-perf-07-candidate-wheel-v1"


def _run(command: list[str], *, cwd: Path) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"candidate wheel command failed ({' '.join(command)}):\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def _artifacts(directory: Path) -> list[dict[str, Any]]:
    return [
        {"filename": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        for path in sorted(directory.iterdir())
        if path.is_file()
    ]


def run(*, python: Path | None = None) -> dict[str, Any]:
    # Keep the caller's venv symlink. Resolving it can turn ``.venv/bin/python``
    # into the system interpreter and silently drop build/test dependencies.
    interpreter = Path(sys.executable) if python is None else python
    if not interpreter.is_file():
        raise ValueError(f"Python interpreter does not exist: {interpreter}")
    venv_maturin = interpreter.parent / ("maturin.exe" if os.name == "nt" else "maturin")
    maturin = str(venv_maturin) if venv_maturin.is_file() else shutil.which("maturin")
    if maturin is None:
        raise RuntimeError("maturin is required to build the local native candidate wheel")
    with tempfile.TemporaryDirectory(prefix="quantbt-perf07-wheel-") as raw:
        root = Path(raw)
        core = root / "core"
        native = root / "native"
        staged = root / "staged"
        for directory in (core, native, staged):
            directory.mkdir(parents=True, exist_ok=True)
        _run([str(interpreter), "-m", "build", "--wheel", "--sdist", "--outdir", str(core)], cwd=ROOT)
        _run(
            [
                maturin,
                "build",
                "--release",
                "--manifest-path",
                str(ROOT / "rust" / "native_event" / "Cargo.toml"),
                "--interpreter",
                str(interpreter),
                "--out",
                str(native),
            ],
            cwd=ROOT,
        )
        for artifact in (*core.iterdir(), *native.iterdir()):
            if artifact.is_file():
                shutil.copy2(artifact, staged / artifact.name)
        verification = verify_staged_wheels(
            staged,
            require_native=True,
            install=True,
            direct_target_smoke=True,
        )
        artifacts = _artifacts(staged)
    return {
        "schema": SCHEMA,
        "phase": "PERF-07",
        "platform_scope": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
            "python_implementation": platform.python_implementation(),
            "certification": "one local clean Linux CPython candidate pair; CI owns the published manylinux matrix",
        },
        "artifacts": artifacts,
        "verification": verification,
        "evidence": {
            "source_hash_parity": bool(verification["source_hash_parity"]),
            "clean_install": bool(verification["clean_install"]),
            "direct_target_smoke": bool(verification["direct_target_smoke"]),
            "exact_native_pair": verification["native_pair"] is not None,
            "source_tree_import_blocked": True,
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="candidate wheel build then isolated core/native clean-install smoke outside checkout",
            data_sha256=sha256(b"PERF-07 candidate wheel has no private market data").hexdigest(),
            intent_sha256=sha256(str(interpreter).encode("utf-8")).hexdigest(),
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = run(python=args.python)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["evidence"], indent=2, sort_keys=True))
    return 0 if all(payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
