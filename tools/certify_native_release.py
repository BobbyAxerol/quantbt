#!/usr/bin/env python3
"""Certify a staged QuantBT core/native wheel pair from installed artifacts.

This is a release-candidate gate, not a publisher.  It never imports QuantBT
from the repository in its child environments: every behavioral check runs in
a fresh virtual environment containing only the staged wheels and resolved
runtime dependencies.  The certificate is deliberately narrow about what is
promoted: Stage-B static/IR/batch routes are automatic only with the matching
native companion; the two B3 portfolio/package helpers are explicit certified
contracts, not generic endpoint promotion.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import textwrap
import tomllib
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"
MIGRATION_AUDIT = ROOT / "contracts" / "native_event_deletion_manifest.json"
CORE_PYPROJECT = ROOT / "pyproject.toml"
BENCHMARK_EVIDENCE = (
    "benchmarks/native_event/results/phase54a5/exit_gate.json",
    "benchmarks/native_event/results/phase54b2/public_routes.json",
    "benchmarks/native_event/results/phase54b3/portfolio_package.json",
)


def _release_dependencies():
    """Load repository tools only after the CLI has established project root.

    Keeping these imports inside one helper avoids a module-level import-order
    exception while preserving direct ``python tools/...`` invocation from any
    working directory.
    """

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.check_native_release_handoff import validate_migration_audit
    from tools.create_sbom import build_sbom
    from tools.create_supply_chain_report import build_supply_chain_report
    from tools.verify_wheels import find_artifact, verify_staged_wheels

    return (
        validate_migration_audit,
        build_sbom,
        build_supply_chain_report,
        find_artifact,
        verify_staged_wheels,
    )


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_json_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "POETRY_ACTIVE"):
        environment.pop(name, None)
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _core_non_native_dependencies() -> tuple[str, ...]:
    """Return the core runtime requirements without the Linux companion.

    The core-only certificate intentionally proves the documented Python
    fallback.  Its environment therefore installs the ordinary Python runtime
    dependencies while deliberately omitting the platform-marked native wheel.
    """

    payload = tomllib.loads(CORE_PYPROJECT.read_text(encoding="utf-8"))
    dependencies = payload["project"]["dependencies"]
    return tuple(
        str(requirement)
        for requirement in dependencies
        if not str(requirement).lower().startswith("quantbt-native")
    )


def _run(command: list[str], *, cwd: Path, environment: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=dict(environment),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({' '.join(command)}):\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _run_json_script(
    python: Path,
    script: str,
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    completed = _run([str(python), "-c", script], cwd=cwd, environment=environment)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"installed-wheel probe did not emit one JSON object: {completed.stdout!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("installed-wheel probe emitted a non-object JSON payload")
    return payload


def _installed_core_script(core_version: str) -> str:
    return textwrap.dedent(
        """
        import importlib.metadata as metadata
        import importlib.util
        import json
        from pathlib import Path

        import quantbt
        from quantbt.backends._native_event_rust import resolve_native_event_backend

        def installed_path(module):
            value = Path(module.__file__).resolve()
            assert "site-packages" in value.parts or "dist-packages" in value.parts, value
            return str(value)

        assert importlib.util.find_spec("_quantbt_native") is None
        assert metadata.version("quantbt-engine") == __CORE_VERSION__
        selection = resolve_native_event_backend(
            "auto",
            workload_id="event_static_tape_v2_v3",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="static_commands",
            profile="audit",
            account_model="linear_quote_settled_gross_cross",
            bars=10_000,
            environment={},
        )
        assert selection.resolved == "python"
        assert selection.promotion.reason == "native_unavailable"
        disabled = resolve_native_event_backend(
            "auto",
            workload_id="event_static_tape_v2_v3",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="static_commands",
            profile="audit",
            account_model="linear_quote_settled_gross_cross",
            bars=10_000,
            environment={"QUANTBT_DISABLE_NATIVE": "1"},
        )
        assert disabled.resolved == "python"
        assert disabled.promotion.reason == "emergency_native_disabled"
        print(json.dumps({
            "quantbt_path": installed_path(quantbt),
            "core_version": metadata.version("quantbt-engine"),
            "auto_reason_without_native": selection.promotion.reason,
            "disabled_reason": disabled.promotion.reason,
        }, sort_keys=True))
        """
    ).replace("__CORE_VERSION__", repr(core_version))


def _installed_native_script(core_version: str, native_version: str) -> str:
    """Return a self-contained installed-wheel behavioral probe.

    The script deliberately exercises public/static, IR batch/fold, and B3
    bounded helpers.  It does not import benchmark or test modules from the
    source repository, so all QuantBT behavior comes from installed wheels.
    """

    return textwrap.dedent(
        """
        import importlib.metadata as metadata
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd

        import _quantbt_native
        import quantbt
        from quantbt import (
            AccountConfig,
            ExecutionConfig,
            NativeEventBackend,
            NativeEventConfig,
            NativeIRFold,
            NativeStrategyIR,
            NativeStrategyKind,
            NativeStrategyParameters,
            OrderCommand,
            OrderSide,
            OrderType,
            QuantBTEndpoint,
        )
        from quantbt.backends import run_atomic_package_market, run_portfolio_target_market
        from quantbt.backends._native_event_rust import (
            NativeEventRustBackendError,
            probe_native_event_rust_extension,
            resolve_native_event_backend,
        )
        from quantbt.core.product_contracts import native_runtime_product_descriptor

        def installed_path(module):
            value = Path(module.__file__).resolve()
            assert "site-packages" in value.parts or "dist-packages" in value.parts, value
            return str(value)

        assert metadata.version("quantbt-engine") == __CORE_VERSION__
        assert metadata.version("quantbt-native") == __NATIVE_VERSION__
        status = probe_native_event_rust_extension()
        assert status.available and status.compatible and status.executable, status.reason
        assert status.product_descriptor == native_runtime_product_descriptor()
        assert _quantbt_native.api_version() == "0.4"

        static_selection = resolve_native_event_backend(
            "auto",
            workload_id="event_static_tape_v2_v3",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="static_commands",
            profile="audit",
            account_model="linear_quote_settled_gross_cross",
            bars=10_000,
            environment={},
        )
        assert static_selection.resolved == "rust"
        assert static_selection.promotion.reason == "auto_rust_certified"
        portfolio_selection = resolve_native_event_backend(
            "auto",
            workload_id="portfolio_target_market_v1",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="portfolio_target_market",
            profile="audit",
            account_model="linear_quote_settled_gross_cross",
            bars=2_000,
            symbol_count=2,
            environment={},
        )
        assert portfolio_selection.resolved == "python"
        disabled = resolve_native_event_backend(
            "auto",
            workload_id="event_static_tape_v2_v3",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="static_commands",
            profile="audit",
            account_model="linear_quote_settled_gross_cross",
            bars=10_000,
            environment={"QUANTBT_DISABLE_NATIVE": "1"},
        )
        assert disabled.resolved == "python"
        assert disabled.promotion.reason == "emergency_native_disabled"
        try:
            resolve_native_event_backend(
                "rust",
                workload_id="event_static_tape_v2_v3",
                execution_contract_id="event_lifecycle_v2_next_bar_close",
                strategy_mode="static_commands",
                profile="audit",
                account_model="linear_quote_settled_gross_cross",
                bars=10_000,
                environment={"QUANTBT_DISABLE_NATIVE": "1"},
            )
        except NativeEventRustBackendError:
            explicit_disable_fails_closed = True
        else:
            raise AssertionError("explicit Rust must fail when native is disabled")

        static_bars = 10_000
        static_index = pd.date_range("2025-01-01", periods=static_bars, freq="1h", tz="UTC")
        static_close = 100.0 + 0.01 * np.arange(static_bars, dtype=np.float64)
        static_frame = pd.DataFrame({
            "open": np.r_[static_close[0], static_close[:-1]],
            "high": static_close + 1.0,
            "low": static_close - 1.0,
            "close": static_close,
            "volume": 1_000.0,
        }, index=static_index)
        static_result = QuantBTEndpoint.event_driven(
            input_mode="orders",
            profile="optimize",
            backend="auto",
            initial_capital=10_000.0,
            leverage=5.0,
            fee_rate=0.0002,
            use_funding=False,
        ).simulate(
            data=static_frame,
            order_commands=[OrderCommand(
                timestamp=static_index[1], symbol="BTC", side=OrderSide.BUY,
                order_type=OrderType.MARKET, qty=0.5, order_id="installed-static",
            )],
            symbols=["BTC"],
        )
        assert static_result.metadata["execution_plan_v1"]["backend"] == "rust"
        assert static_result.metadata["rust_audit_replay"] is False

        ir_bars = 2_000
        ir_index = pd.date_range("2025-02-01", periods=ir_bars, freq="1h", tz="UTC")
        ir_close = 80.0 + 0.02 * np.arange(ir_bars, dtype=np.float64)
        ir_frame = pd.DataFrame({
            "open": np.r_[ir_close[0], ir_close[:-1]],
            "high": ir_close + 1.0,
            "low": ir_close - 1.0,
            "close": ir_close,
            "volume": 1_000.0,
        }, index=ir_index)
        ir_backend = NativeEventBackend(NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend="auto",
        ))
        ir_runner = ir_backend.prepare_native_strategy_ir(
            ir_index,
            closes={"BTC": ir_frame["close"]},
            highs={"BTC": ir_frame["high"]},
            lows={"BTC": ir_frame["low"]},
            opens={"BTC": ir_frame["open"]},
            program=NativeStrategyIR(
                NativeStrategyKind.GRID_LEVEL,
                "BTC",
                parameters=NativeStrategyParameters(quantity=0.25),
            ),
            symbols=["BTC"],
        )
        signal = np.where(np.arange(ir_bars) % 80 < 40, 1.0, 0.0).astype(np.float64)
        batch = ir_runner.run_batch_score(np.vstack((signal, np.roll(signal, 7))), workers=2)
        fold = NativeIRFold(0, 0, 0, 1_000, 1_000, 2_000)
        fold_result = ir_runner.run_fold_batch_score(np.vstack((signal, np.roll(signal, 7))), fold, workers=2)
        assert batch.metadata["execution_plan_v1"]["backend"] == "rust"
        assert batch.metadata["boundary_calls"] == 1
        assert fold_result.metadata["boundary_calls"] == 1

        index = pd.date_range("2025-03-01", periods=5, freq="1h", tz="UTC")
        closes = np.asarray([
            [100.0, 50.0], [101.0, 49.0], [102.0, 51.0], [101.0, 52.0], [103.0, 51.0],
        ], dtype=np.float64)
        common = {
            "timestamps_ns": np.ascontiguousarray(index.asi8, dtype=np.int64),
            "opens": closes,
            "highs": closes + 1.0,
            "lows": closes - 1.0,
            "closes": closes,
            "volumes": np.full_like(closes, 1_000.0),
            "funding": np.zeros_like(closes),
            "funding_mask": np.zeros(len(index), dtype=np.bool_),
            "symbols": ("BTC", "ETH"),
            "contract_sizes": np.ones(2, dtype=np.float64),
            "leverages": np.full(2, 5.0, dtype=np.float64),
            "fee_rates": np.full(2, 0.0002, dtype=np.float64),
            "initial_capital": 10_000.0,
            "maintenance_ratio": 0.005,
            "slippage_rate": 0.0001,
            "use_funding": False,
        }
        target_units = np.zeros((len(index), 2), dtype=np.float64)
        target_units[1:] = np.asarray([0.5, -0.25])
        target_score = run_portfolio_target_market(target_units=target_units, report_level="score", **common)
        target_audit = run_portfolio_target_market(target_units=target_units, report_level="audit", **common)
        assert abs(target_score.final_equity - target_audit.final_equity) <= 1e-12
        assert target_audit.to_audit_result().final_equity == target_audit.final_equity
        assert target_audit.payload["python_callbacks"] == 0
        assert target_audit.payload["boundary_calls"] == 1

        def python_oracle(commands):
            backend = NativeEventBackend(NativeEventConfig(
                account=AccountConfig(
                    initial_capital=10_000.0,
                    leverage=5.0,
                    maintenance_ratio=0.005,
                ),
                execution=ExecutionConfig(slippage_bps=1.0),
                fee_rate=0.0002,
                use_funding=False,
                native_backend="python",
                execution_contract="event_lifecycle_v2_next_bar_close",
            ))
            return backend.run_order_commands(
                datetime_index=index,
                commands=commands,
                closes={symbol: pd.Series(closes[:, column], index=index) for column, symbol in enumerate(common["symbols"])},
                highs={symbol: pd.Series((closes + 1.0)[:, column], index=index) for column, symbol in enumerate(common["symbols"])},
                lows={symbol: pd.Series((closes - 1.0)[:, column], index=index) for column, symbol in enumerate(common["symbols"])},
                contract_size={symbol: 1.0 for symbol in common["symbols"]},
                leverage={symbol: 5.0 for symbol in common["symbols"]},
                fee_rate={symbol: 0.0002 for symbol in common["symbols"]},
                symbols=list(common["symbols"]),
                report_level="audit",
            )

        target_oracle = python_oracle((
            OrderCommand(timestamp=index[1], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=0.5, order_id="target-btc"),
            OrderCommand(timestamp=index[1], symbol="ETH", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=0.25, order_id="target-eth"),
        ))
        np.testing.assert_allclose(target_audit.payload["equity"], target_oracle.equity.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(
            np.asarray(target_audit.payload["positions"]).reshape(len(index), 2),
            target_oracle.positions[["Position_BTC", "Position_ETH"]].to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
        np.testing.assert_allclose(target_audit.payload["fees"], target_oracle.fees.to_numpy(), rtol=0.0, atol=1e-12)

        package = run_atomic_package_market(
            command_bar=1,
            package_id=54_004,
            order_ids=np.asarray([54_101, 54_102], dtype=np.int64),
            symbol_ids=np.asarray([0, 1], dtype=np.uint32),
            signed_qty=np.asarray([0.4, -0.4], dtype=np.float64),
            source_age_ns=np.zeros(2, dtype=np.int64),
            venue_codes=np.ones(2, dtype=np.uint16),
            venue_sequence=np.asarray([0, 1], dtype=np.uint32),
            report_level="audit",
            **common,
        )
        assert package.payload["package_accepted"].tolist() == [True, True]
        assert package.payload["python_callbacks"] == 0
        assert package.payload["boundary_calls"] == 1
        package_oracle = python_oracle((
            OrderCommand(timestamp=index[1], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=0.4, order_id="package-btc"),
            OrderCommand(timestamp=index[1], symbol="ETH", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=0.4, order_id="package-eth"),
        ))
        np.testing.assert_allclose(package.payload["equity"], package_oracle.equity.to_numpy(), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(
            np.asarray(package.payload["positions"]).reshape(len(index), 2),
            package_oracle.positions[["Position_BTC", "Position_ETH"]].to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
        np.testing.assert_allclose(package.payload["fees"], package_oracle.fees.to_numpy(), rtol=0.0, atol=1e-12)

        print(json.dumps({
            "quantbt_path": installed_path(quantbt),
            "native_path": installed_path(_quantbt_native),
            "core_version": metadata.version("quantbt-engine"),
            "native_version": metadata.version("quantbt-native"),
            "static_auto_reason": static_selection.promotion.reason,
            "portfolio_auto_reason": portfolio_selection.promotion.reason,
            "disabled_reason": disabled.promotion.reason,
            "explicit_disable_fails_closed": explicit_disable_fails_closed,
            "static_backend": static_result.metadata["execution_plan_v1"]["backend"],
            "ir_batch_boundary_calls": int(batch.metadata["boundary_calls"]),
            "ir_fold_boundary_calls": int(fold_result.metadata["boundary_calls"]),
            "target_final_equity": float(target_audit.final_equity),
            "target_python_oracle_parity": "exact_atol_1e-12",
            "package_final_equity": float(package.final_equity),
            "package_accepted": [bool(value) for value in package.payload["package_accepted"]],
            "package_python_oracle_parity": "exact_atol_1e-12",
        }, sort_keys=True))
        """
    ).replace("__CORE_VERSION__", repr(core_version)).replace("__NATIVE_VERSION__", repr(native_version))


def _build_venv(python: Path, target: Path, *, core: Path, native: Path | None) -> Path:
    environment = _clean_environment()
    _run([str(python), "-m", "venv", str(target)], cwd=target.parent, environment=environment)
    installed = _venv_python(target)
    _run([str(installed), "-m", "pip", "install", "--upgrade", "pip"], cwd=target.parent, environment=environment)
    if native is None:
        # The fallback probe cannot use a normal dependency solve: on supported
        # Linux, the public core correctly requires quantbt-native. Install the
        # core without that companion, then install its non-native runtime base
        # explicitly. ``pip check`` is intentionally inapplicable here because
        # this is the one controlled environment which omits the companion.
        _run(
            [str(installed), "-m", "pip", "install", "--no-deps", str(core)],
            cwd=target.parent,
            environment=environment,
        )
        _run(
            [str(installed), "-m", "pip", "install", *_core_non_native_dependencies()],
            cwd=target.parent,
            environment=environment,
        )
        return installed

    # Install the staged native wheel first so pip resolves the exact local
    # companion rather than querying an index before it reaches the core.
    _run([str(installed), "-m", "pip", "install", str(native)], cwd=target.parent, environment=environment)
    _run([str(installed), "-m", "pip", "install", str(core)], cwd=target.parent, environment=environment)
    _run([str(installed), "-m", "pip", "check"], cwd=target.parent, environment=environment)
    return installed


def _registry_surface(registry: Mapping[str, Any]) -> dict[str, Any]:
    workloads = {str(item["id"]): item for item in registry["workloads"]}
    rules = {
        str(item["workload_id"]): item
        for item in registry["promotion_policy"]["rules"]
        if bool(item["enabled"])
    }
    promoted = []
    certified_explicit = []
    for identifier, workload in sorted(workloads.items()):
        if bool(workload["auto_promotion"]):
            rule = rules[identifier]
            promoted.append(
                {
                    "workload": identifier,
                    "stage": str(rule["stage"]),
                    "minimum_bars": int(rule["min_bars"]),
                }
            )
        elif str(workload["maturity"]) == "certified":
            certified_explicit.append(identifier)
    return {
        "promotion_table_version": str(registry["promotion_policy"]["table_version"]),
        "default_stage": str(registry["promotion_policy"]["default_stage"]),
        "core_only_auto_backend": "python",
        "native_companion_published": bool(registry["versions"]["native_package"].get("published", False)),
        "automatic_rust_workloads": promoted,
        "explicit_certified_workloads": certified_explicit,
        "rollback_controls": [
            "native_backend='python'",
            "QUANTBT_DISABLE_NATIVE=1",
            "QUANTBT_NATIVE_PROMOTION_MAX=explicit_only",
        ],
    }


def _artifact_evidence(dist: Path, registry: Mapping[str, Any]) -> tuple[Path, Path, list[dict[str, Any]]]:
    _, _, _, find_artifact, _ = _release_dependencies()
    core_meta = registry["versions"]["core_package"]
    native_meta = registry["versions"]["native_package"]
    core = find_artifact(dist, str(core_meta["distribution"]), ".whl")
    native = find_artifact(dist, str(native_meta["distribution"]), ".whl")
    artifacts = []
    for path in sorted(dist.glob("*.whl")):
        artifacts.append({"name": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    core_sdist = dist / f"quantbt_engine-{core_meta['version']}.tar.gz"
    if core_sdist.is_file():
        artifacts.append({"name": core_sdist.name, "bytes": core_sdist.stat().st_size, "sha256": _sha256(core_sdist)})
    return core, native, artifacts


def _benchmark_evidence() -> list[dict[str, str]]:
    result = []
    for relative in BENCHMARK_EVIDENCE:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"required Phase 54 benchmark evidence is missing: {relative}")
        json.loads(path.read_text(encoding="utf-8"))
        result.append({"path": relative, "sha256": _sha256(path)})
    return result


def _git_value(*arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def certify_release(
    dist: Path,
    *,
    python: Path,
) -> dict[str, Any]:
    """Build a serializable installed-wheel certification result or raise."""

    (
        validate_migration_audit,
        build_sbom,
        build_supply_chain_report,
        _,
        verify_staged_wheels,
    ) = _release_dependencies()
    violations = validate_migration_audit()
    if violations:
        raise RuntimeError("native migration audit failed: " + "; ".join(violations))
    registry = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    core, native, artifacts = _artifact_evidence(dist, registry)
    wheel_verification = verify_staged_wheels(dist, require_native=True, install=True)
    core_version = str(registry["versions"]["core_package"]["version"])
    native_version = str(registry["versions"]["native_package"]["version"])

    with tempfile.TemporaryDirectory(prefix="quantbt-native-release-") as raw:
        temporary = Path(raw)
        environment = _clean_environment()
        core_python = _build_venv(python, temporary / "core-only", core=core, native=None)
        core_only = _run_json_script(
            core_python,
            _installed_core_script(core_version),
            cwd=temporary,
            environment=environment,
        )
        native_python = _build_venv(python, temporary / "exact-pair", core=core, native=native)
        exact_pair = _run_json_script(
            native_python,
            _installed_native_script(core_version, native_version),
            cwd=temporary,
            environment=environment,
        )

    supply_chain = build_supply_chain_report()
    sbom = build_sbom()
    return {
        "schema": "quantbt-native-release-certification-v1",
        "phase": "54B.4",
        "git_sha": _git_value("rev-parse", "HEAD"),
        "git_ref": _git_value("symbolic-ref", "--short", "-q", "HEAD"),
        "host": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "product_contract": {
            "product_registry_fingerprint": _canonical_json_fingerprint(PRODUCT_REGISTRY),
            "lifecycle_registry_fingerprint": _canonical_json_fingerprint(LIFECYCLE_REGISTRY),
            "surface": _registry_surface(registry),
        },
        "artifacts": artifacts,
        "wheel_verification": wheel_verification,
        "installed_wheel": {
            "core_only": core_only,
            "exact_pair": exact_pair,
        },
        "benchmark_evidence": _benchmark_evidence(),
        "migration_audit": {
            "path": str(MIGRATION_AUDIT.relative_to(ROOT)),
            "sha256": _sha256(MIGRATION_AUDIT),
            "status": "pass",
        },
        "supply_chain": {
            "cargo_lock_sha256": supply_chain["build_provenance"]["cargo_lock_sha256"],
            "unsafe_code_policy": supply_chain["rust_workspace"]["unsafe_code_policy"],
            "unsafe_inventory_count": len(supply_chain["rust_workspace"]["unsafe_inventory"]),
            "sbom_sha256": sha256(
                json.dumps(sbom, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        "release_decision": {
            "core_pypi_release": "eligible after the matching native wheels are public and the core release workflow passes",
            "native_distribution": "wheel-only public-release candidate; trusted publishing and public consumer proof remain mandatory",
            "generic_portfolio_package_auto_promotion": "not enabled",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True, help="Directory containing staged core/native wheels and core sdist")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Interpreter used to create clean wheel environments")
    args = parser.parse_args(argv)
    try:
        payload = certify_release(args.dist.resolve(), python=args.python.resolve())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"native release certification failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"native release certification written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
