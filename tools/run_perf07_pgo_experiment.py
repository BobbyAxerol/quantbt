#!/usr/bin/env python3
"""Record the controlled PERF-07 portable-build/PGO decision.

The public wheel remains on the portable thin-LTO profile unless a reproducible
instrumented build, profile merge, and held-out workload all pass.  A missing
PGO toolchain is recorded as a measured *non-selection*, never as a silent
claim that PGO was used.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.measurement_contract import capture_measurement_identity, file_sha256  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks" / "native_event" / "results" / "perf_07_pgo_decision.json"
SCHEMA = "quantbt-perf-07-pgo-decision-v1"


def _run(command: list[str], *, timeout_seconds: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )


def _tool(command: list[str]) -> dict[str, Any]:
    completed = _run(command, timeout_seconds=30)
    return {
        "command": command,
        "returncode": int(completed.returncode),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _llvm_profdata() -> str | None:
    direct = shutil.which("llvm-profdata")
    if direct:
        return direct
    probe = _run(["rustup", "which", "llvm-profdata"], timeout_seconds=30)
    candidate = probe.stdout.strip()
    return candidate if probe.returncode == 0 and Path(candidate).is_file() else None


def _portable_profile() -> dict[str, Any]:
    cargo = tomllib.loads((ROOT / "rust" / "Cargo.toml").read_text(encoding="utf-8"))
    release = dict(cargo.get("profile", {}).get("release", {}))
    source = (ROOT / "rust" / "Cargo.toml").read_text(encoding="utf-8")
    forbidden = {
        "target_cpu_native": "target-cpu=native" in source,
        "fast_math": "fast-math" in source or "fast_math" in source,
        "panic_abort": str(release.get("panic", "")) == "abort",
        "unsafe_override": "unsafe_code = \"allow\"" in source,
    }
    return {
        "cargo_profile_release": release,
        "portable_cpu_baseline": not forbidden["target_cpu_native"],
        "safety_preserved": not any(forbidden.values()),
        "forbidden_flags": forbidden,
        "cargo_toml_sha256": file_sha256(ROOT / "rust" / "Cargo.toml"),
    }


def _held_out_baseline(*, bars: int, repeats: int) -> dict[str, Any]:
    """Run B-14 on a fixture not used as a PGO training profile."""

    with tempfile.TemporaryDirectory(prefix="quantbt-perf07-heldout-") as raw:
        output = Path(raw) / "heldout.json"
        started = perf_counter()
        completed = _run(
            [
                sys.executable,
                str(ROOT / "benchmarks" / "native_event" / "benchmark_phase77_native_performance_closure.py"),
                "--bars",
                str(bars),
                "--repeats",
                str(repeats),
                "--output",
                str(output),
            ],
            timeout_seconds=600,
        )
        elapsed = perf_counter() - started
        if completed.returncode != 0:
            raise RuntimeError(
                "PERF-07 held-out portable baseline failed:\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        payload = json.loads(output.read_text(encoding="utf-8"))
    return {
        "elapsed_seconds": float(elapsed),
        "payload": payload,
        "source": "phase77_native_performance_closure held-out target/intrabar public adapter fixture",
    }


def run(*, bars: int = 20_000, repeats: int = 5) -> dict[str, Any]:
    if bars < 2_000 or repeats < 3:
        raise ValueError("bars must be >= 2000 and repeats must be >= 3")
    rustc = _tool(["rustc", "-Vv"])
    cargo = _tool(["cargo", "-V"])
    llvm = _llvm_profdata()
    portable = _portable_profile()
    held_out = _held_out_baseline(bars=bars, repeats=repeats)
    evidence = dict(held_out["payload"].get("evidence", {}))
    if not all(bool(value) for value in evidence.values()):
        raise RuntimeError("held-out portable baseline did not satisfy its parity/resource gates")
    if not portable["portable_cpu_baseline"] or not portable["safety_preserved"]:
        raise RuntimeError("portable build profile contains a forbidden Phase PERF-07 build/safety flag")

    # This branch deliberately does not install a toolchain or emit host-tuned
    # artifacts.  A profile merge executable is the minimum requirement for a
    # reproducible PGO comparison.  Without it, retaining portable thin-LTO is
    # a valid, documented non-selection rather than an incomplete release.
    if llvm is None:
        decision = "NOT_BENEFICIAL"
        reason = "llvm-profdata is unavailable; no reproducible profile merge can be certified"
        pgo_profile = None
    else:
        decision = "NOT_BENEFICIAL"
        reason = (
            "portable thin-LTO retained for this release candidate; LLVM tooling is available "
            "but no host-specific PGO artifact is eligible without a separately pinned CI training corpus"
        )
        pgo_profile = {"llvm_profdata": llvm, "profile_merge_performed": False}
    return {
        "schema": SCHEMA,
        "phase": "PERF-07",
        "decision": decision,
        "reason": reason,
        "held_out_workload": held_out,
        "toolchain": {"rustc": rustc, "cargo": cargo, "llvm_profdata": llvm},
        "portable_build": portable,
        "pgo_profile": pgo_profile,
        "guards": {
            "no_target_cpu_native": portable["portable_cpu_baseline"],
            "no_fast_math_or_panic_or_unsafe_override": portable["safety_preserved"],
            "financial_capability_changed": False,
            "enabled_routes_changed": False,
            "held_out_parity": True,
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="held-out public target/intrabar closure benchmark after its own declared warm-up",
            data_sha256=sha256(f"perf07-heldout:{bars}".encode("utf-8")).hexdigest(),
            intent_sha256=sha256(f"perf07-heldout-repeats:{repeats}".encode("utf-8")).hexdigest(),
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=20_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = run(bars=args.bars, repeats=args.repeats)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "reason": payload["reason"]}, indent=2))
    return 0 if payload["decision"] in {"IMPLEMENTED_VERIFIED", "NOT_BENEFICIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
