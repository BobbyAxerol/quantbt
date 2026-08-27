#!/usr/bin/env python3
"""Prove a released QuantBT core/native pair from a fresh Poetry consumer.

This is a release-owner tool, not a package builder.  It creates an isolated
temporary Poetry project, runs the same ``poetry add quantbt-engine`` command a
Linux user would run, and verifies that the resolved public artifacts provide
the governed Rust route.  It deliberately executes outside the repository and
uses a fresh Poetry cache so a local checkout, wheel, or cached source package
cannot satisfy the proof by accident.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
TESTPYPI_SIMPLE_URL = "https://test.pypi.org/simple/"


@dataclass(frozen=True)
class ConsumerProofSpec:
    """Immutable public-index proof inputs derived from the release ref."""

    index: str
    core_version: str
    native_version: str
    poetry: str
    python: Path
    timeout_seconds: int
    index_url: str | None = None


def declared_versions(root: Path = ROOT) -> tuple[str, str]:
    """Return the exact core/native pair declared by the product registry."""

    registry = json.loads(
        (root / "contracts" / "native_event_product_registry.json").read_text(encoding="utf-8")
    )
    versions = registry["versions"]
    return (
        str(versions["core_package"]["version"]),
        str(versions["native_package"]["version"]),
    )


def consumer_pyproject() -> str:
    """Return a deliberately empty Poetry consumer project definition."""

    return textwrap.dedent(
        """
        [project]
        name = "quantbt-public-consumer-proof"
        version = "0.0.0"
        description = "Temporary isolated QuantBT package consumer"
        requires-python = ">=3.11,<3.14"

        [tool.poetry]
        package-mode = false
        """
    ).lstrip()


def poetry_source_commands(spec: ConsumerProofSpec) -> tuple[tuple[str, ...], ...]:
    """Return index configuration commands without mutating user Poetry config."""

    if spec.index == "pypi":
        return ()
    if spec.index != "testpypi":
        raise ValueError("index must be 'pypi' or 'testpypi'")
    return (
        (
            spec.poetry,
            "source",
            "add",
            "--priority=primary",
            "testpypi",
            spec.index_url or TESTPYPI_SIMPLE_URL,
            "--no-interaction",
            "--no-ansi",
        ),
        # With a primary TestPyPI source, keep the normal PyPI index as a
        # supplemental dependency source. Poetry treats this reserved name
        # specially and intentionally accepts no URL for it.
        (
            spec.poetry,
            "source",
            "add",
            "--priority=supplemental",
            "PyPI",
            "--no-interaction",
            "--no-ansi",
        ),
    )


def poetry_install_commands(spec: ConsumerProofSpec) -> tuple[tuple[str, ...], ...]:
    """Return the fixed public-consumer Poetry command sequence.

    The unpinned public command is intentional: it proves that ordinary
    ``poetry add quantbt-engine`` resolves the current release.  The installed
    versions are asserted afterwards, so an accidental newer/older artifact is
    a hard failure rather than a silent false positive.
    """

    return (
        (spec.poetry, "env", "use", str(spec.python), "--no-interaction", "--no-ansi"),
        *poetry_source_commands(spec),
        (spec.poetry, "add", "quantbt-engine", "--no-interaction", "--no-ansi"),
    )


def public_probe_script(core_version: str, native_version: str) -> str:
    """Return an installed-artifact smoke that exercises route and fallback policy."""

    return textwrap.dedent(
        f"""
        import importlib.metadata as metadata
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd

        import _quantbt_native
        import quantbt
        from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint
        from quantbt.backends._native_event_rust import (
            NativeEventRustBackendError,
            probe_native_event_rust_extension,
            resolve_native_event_backend,
        )

        core_path = Path(quantbt.__file__).resolve()
        native_path = Path(_quantbt_native.__file__).resolve()
        assert "site-packages" in core_path.parts or "dist-packages" in core_path.parts, core_path
        assert "site-packages" in native_path.parts or "dist-packages" in native_path.parts, native_path
        assert metadata.version("quantbt-engine") == {core_version!r}
        assert metadata.version("quantbt-native") == {native_version!r}

        status = probe_native_event_rust_extension()
        assert status.available and status.compatible and status.executable, status.reason

        selection_kwargs = dict(
            workload_id="event_static_tape_v2_v3",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="static_commands",
            # ``event_driven(profile="optimize")`` normalizes to score at the
            # endpoint boundary. The direct policy probe must use a canonical
            # declared workload profile instead of the user-facing alias.
            profile="audit",
            account_model="linear_quote_settled_gross_cross",
            bars=10_000,
        )
        automatic = resolve_native_event_backend("auto", environment={{}}, **selection_kwargs)
        assert automatic.resolved == "rust", automatic
        assert automatic.promotion.reason == "auto_rust_certified", automatic.promotion

        forced_python = resolve_native_event_backend("python", environment={{}}, **selection_kwargs)
        assert forced_python.resolved == "python", forced_python

        disabled = resolve_native_event_backend(
            "auto", environment={{"QUANTBT_DISABLE_NATIVE": "1"}}, **selection_kwargs
        )
        assert disabled.resolved == "python", disabled
        assert disabled.promotion.reason == "emergency_native_disabled", disabled.promotion
        try:
            resolve_native_event_backend(
                "rust", environment={{"QUANTBT_DISABLE_NATIVE": "1"}}, **selection_kwargs
            )
        except NativeEventRustBackendError:
            explicit_disable_fails_closed = True
        else:
            raise AssertionError("explicit Rust unexpectedly fell back while native was disabled")

        bars = 10_000
        index = pd.date_range("2025-01-01", periods=bars, freq="1h", tz="UTC")
        close = 100.0 + 0.01 * np.arange(bars, dtype=np.float64)
        frame = pd.DataFrame(
            {{
                "open": np.r_[close[0], close[:-1]],
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(bars, 1_000.0),
            }},
            index=index,
        )
        result = QuantBTEndpoint.event_driven(
            input_mode="orders",
            profile="optimize",
            backend="auto",
            initial_capital=10_000.0,
            leverage=5.0,
            fee_rate=0.0002,
            use_funding=False,
        ).simulate(
            data=frame,
            order_commands=[
                OrderCommand(
                    timestamp=index[1],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=0.5,
                    order_id="public-consumer-static",
                )
            ],
            symbols=["BTC"],
        )
        execution = result.metadata["execution_plan_v1"]
        assert execution["backend"] == "rust", execution
        assert result.metadata["rust_audit_replay"] is False

        print(json.dumps(
            {{
                "schema": "quantbt-public-native-consumer-proof-v1",
                "core_version": metadata.version("quantbt-engine"),
                "native_version": metadata.version("quantbt-native"),
                "core_path": str(core_path),
                "native_path": str(native_path),
                "automatic_backend": execution["backend"],
                "automatic_reason": automatic.promotion.reason,
                "forced_python_backend": forced_python.resolved,
                "disabled_auto_backend": disabled.resolved,
                "disabled_auto_reason": disabled.promotion.reason,
                "explicit_disable_fails_closed": explicit_disable_fails_closed,
                "final_equity": float(result.equity.iloc[-1]),
            }},
            sort_keys=True,
        ))
        """
    ).strip()


def _clean_environment(workspace: Path) -> dict[str, str]:
    """Return a fresh Poetry/Python environment without source-tree leakage."""

    environment = dict(os.environ)
    for name in ("PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "POETRY_ACTIVE"):
        environment.pop(name, None)
    environment.update(
        {
            "POETRY_CACHE_DIR": str(workspace / "poetry-cache"),
            "POETRY_VIRTUALENVS_IN_PROJECT": "true",
            "PYTHONNOUSERSITE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    return environment


def _run(command: Sequence[str], *, cwd: Path, environment: Mapping[str, str], timeout_seconds: int) -> str:
    """Run one argv-safe external command and return its stdout on success."""

    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(environment),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if completed.returncode:
        rendered = " ".join(command)
        raise RuntimeError(
            f"consumer command failed ({rendered}):\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def run_consumer_proof(spec: ConsumerProofSpec) -> dict[str, Any]:
    """Install public artifacts through Poetry and return an auditable probe report."""

    with tempfile.TemporaryDirectory(prefix="quantbt-public-consumer-") as raw:
        workspace = Path(raw)
        environment = _clean_environment(workspace)
        (workspace / "pyproject.toml").write_text(consumer_pyproject(), encoding="utf-8")
        probe_path = workspace / "consumer_probe.py"
        probe_path.write_text(
            public_probe_script(spec.core_version, spec.native_version) + "\n", encoding="utf-8"
        )

        commands = poetry_install_commands(spec)
        for command in commands:
            _run(command, cwd=workspace, environment=environment, timeout_seconds=spec.timeout_seconds)
        show_core = _run(
            (spec.poetry, "show", "quantbt-engine", "--no-ansi"),
            cwd=workspace,
            environment=environment,
            timeout_seconds=spec.timeout_seconds,
        ).strip()
        show_native = _run(
            (spec.poetry, "show", "quantbt-native", "--no-ansi"),
            cwd=workspace,
            environment=environment,
            timeout_seconds=spec.timeout_seconds,
        ).strip()
        probe_stdout = _run(
            (spec.poetry, "run", "python", str(probe_path)),
            cwd=workspace,
            environment=environment,
            timeout_seconds=spec.timeout_seconds,
        )
        try:
            probe = json.loads(probe_stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"consumer probe did not emit one JSON object: {probe_stdout!r}") from exc
        if not isinstance(probe, dict):
            raise RuntimeError("consumer probe emitted a non-object JSON payload")

    return {
        "schema": "quantbt-public-native-consumer-report-v1",
        "index": spec.index,
        "requested_command": "poetry add quantbt-engine",
        "expected_core_version": spec.core_version,
        "expected_native_version": spec.native_version,
        "poetry_show_core": show_core,
        "poetry_show_native": show_native,
        "probe": probe,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the public release proof without importing QuantBT from this checkout."""

    core_version, native_version = declared_versions()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", choices=("testpypi", "pypi"), required=True)
    parser.add_argument(
        "--index-url",
        help="Optional TestPyPI-compatible simple index override for isolated release-tool tests.",
    )
    parser.add_argument("--poetry", default="poetry")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--core-version", default=core_version)
    parser.add_argument("--native-version", default=native_version)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.index_url and args.index != "testpypi":
        parser.error("--index-url is only valid with --index testpypi")

    spec = ConsumerProofSpec(
        index=args.index,
        core_version=str(args.core_version),
        native_version=str(args.native_version),
        poetry=str(args.poetry),
        python=args.python.resolve(),
        timeout_seconds=int(args.timeout_seconds),
        index_url=str(args.index_url) if args.index_url else None,
    )
    try:
        payload = run_consumer_proof(spec)
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"public Poetry consumer proof failed: {exc}", file=sys.stderr)
        return 1
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
