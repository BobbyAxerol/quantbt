#!/usr/bin/env python3
"""Create or validate Phase 78 public Rust-promotion evidence.

The certificate is deliberately route-scoped.  It measures the two
callback-free Stage-B workloads, but promotes only the one that clears the
current public end-to-end gate:

* canonical static command tapes at the 10,000-bar threshold are retained as
  a parity and performance observation; and
* ``NativeStrategyIR`` score at the 2,000-bar threshold is the A4 target.

Everything else remains outside this certificate.  In particular, a passing
record here does not promote arbitrary callbacks, reactive strategies, generic
walk-forward orchestration, portfolio/package endpoints, or intrabar routes.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import resource
from statistics import median
from time import perf_counter
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
)
from quantbt.backends._native_event_rust import probe_native_event_rust_extension
from quantbt.core.native_event_parity import assert_native_event_full_parity
from quantbt.planning import RunProfile

try:
    from tools.measurement_contract import (
        capture_measurement_identity,
        canonical_json_sha256,
        current_candidate_evidence_violations,
        load_measurement_contract,
        typed_array_sha256,
    )
except ModuleNotFoundError:  # Direct ``python tools/...`` invocation.
    from measurement_contract import (  # type: ignore[no-redef]
        capture_measurement_identity,
        canonical_json_sha256,
        current_candidate_evidence_violations,
        load_measurement_contract,
        typed_array_sha256,
    )


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "benchmarks" / "native_event" / "manifests" / "phase72_measurement_contract_v1.json"
PRODUCT_REGISTRY_PATH = ROOT / "contracts" / "native_event_product_registry.json"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "native_event" / "results" / "phase78_public_promotion.json"
MANIFEST_PATH = "benchmarks/native_event/results/phase78_public_promotion.json"
STATIC_WORKLOAD = "event_static_tape_v2_v3"
IR_WORKLOAD = "native_strategy_ir_v1"
RSS_PLATEAU_LIMIT_MB = 4.0
SPEED_PROMOTION_RATIO = 0.98
AUTO_PROMOTION_WORKLOADS = frozenset({IR_WORKLOAD})
STATIC_STABILITY_REPEATS = 15


def _current_rss_mb() -> float:
    """Read current Linux RSS, with a portable high-water fallback."""

    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _measurement_stats(samples: list[float], rss_samples: list[float], *, before_mb: float) -> dict[str, float | int | list[float]]:
    values = np.asarray(samples, dtype=np.float64)
    tail = np.asarray(rss_samples[-min(3, len(rss_samples)):], dtype=np.float64)
    after = float(rss_samples[-1])
    return {
        "sample_count": int(len(samples)),
        "median_seconds": float(median(samples)),
        "p95_seconds": float(np.quantile(values, 0.95)),
        "warm_rss_before_mb": float(before_mb),
        "warm_rss_after_mb": after,
        "warm_rss_delta_mb": max(0.0, after - float(before_mb)),
        "warm_rss_samples_mb": [float(value) for value in rss_samples],
        "warm_rss_tail_spread_mb": float(tail.max() - tail.min()),
    }


def _public_measurement_identity(
    *,
    warmup_procedure: str,
    data_sha256: str,
    intent_sha256: str,
) -> dict[str, Any]:
    """Capture provenance without publishing a workstation-specific file path."""

    identity = capture_measurement_identity(
        root=ROOT,
        warmup_procedure=warmup_procedure,
        data_sha256=data_sha256,
        intent_sha256=intent_sha256,
    )
    extension = identity.get("native_extension")
    if isinstance(extension, dict):
        for field, replacement in (
            ("module_path", "<installed-native-extension>"),
            ("wrapper_path", "<installed-native-wrapper>"),
        ):
            if extension.get(field):
                extension[field] = replacement
    return identity


def _measure_pair(
    rust_call: Callable[[], Any],
    python_call: Callable[[], Any],
    *,
    repeats: int,
) -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    """Measure matched public calls in alternating order after independent warm-up.

    A score route can sit within normal CPU-frequency and allocator noise.  The
    benchmark contract therefore alternates which backend runs first rather
    than timing all Rust samples before all Python samples.
    """

    rust_result = rust_call()
    python_result = python_call()
    rust_before = _current_rss_mb()
    python_before = rust_before
    rust_samples: list[float] = []
    python_samples: list[float] = []
    rust_rss: list[float] = []
    python_rss: list[float] = []

    def measure(call: Callable[[], Any], values: list[float], rss_values: list[float]) -> Any:
        started = perf_counter()
        result = call()
        values.append(perf_counter() - started)
        rss_values.append(_current_rss_mb())
        return result

    for ordinal in range(repeats):
        if ordinal % 2 == 0:
            rust_result = measure(rust_call, rust_samples, rust_rss)
            python_result = measure(python_call, python_samples, python_rss)
        else:
            python_result = measure(python_call, python_samples, python_rss)
            rust_result = measure(rust_call, rust_samples, rust_rss)
    return (
        _measurement_stats(rust_samples, rust_rss, before_mb=rust_before),
        _measurement_stats(python_samples, python_rss, before_mb=python_before),
        rust_result,
        python_result,
    )


def _frame(bars: int, *, start: str) -> pd.DataFrame:
    index = pd.date_range(start, periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.013 * phase + 1.7 * np.sin(phase / 29.0)
    open_ = np.r_[close[0], close[:-1]] + 0.05 * np.cos(phase / 13.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1.2,
            "low": np.minimum(open_, close) - 1.2,
            "close": close,
            "volume": np.full(bars, 1_000.0, dtype=np.float64),
        },
        index=index,
    )


def _static_commands(index: pd.DatetimeIndex) -> tuple[OrderCommand, ...]:
    points = np.linspace(1, len(index) - 2, num=12, dtype=np.int64)
    commands: list[OrderCommand] = []
    for ordinal, bar in enumerate(points):
        commands.append(
            OrderCommand(
                timestamp=index[int(bar)],
                symbol="BTC",
                side=OrderSide.BUY if ordinal % 2 == 0 else OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=0.25,
                order_id=f"phase78-static-{ordinal}",
            )
        )
    return tuple(commands)


def _static_endpoint(*, backend: str, profile: str = "audit") -> QuantBTEndpoint:
    return QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile=profile,
        backend=backend,
        execution_contract="event_lifecycle_v3_next_open",
        initial_capital=20_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        slippage_bps=2.0,
        use_funding=False,
    )


def _ir_backend(*, backend: str, report_level: str = "audit") -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
            report_level=report_level,
            native_backend=backend,
            execution_contract="event_lifecycle_v3_next_open",
        )
    )


def _ir_runner(frame: pd.DataFrame, *, backend: str, report_level: str = "audit"):
    program = NativeStrategyIR(
        NativeStrategyKind.GRID_LEVEL,
        "BTC",
        parameters=NativeStrategyParameters(quantity=0.25),
    )
    return _ir_backend(backend=backend, report_level=report_level).prepare_native_strategy_ir(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        program=program,
        symbols=["BTC"],
    )


def _result_contract(pair_id: str) -> dict[str, Any]:
    contract = load_measurement_contract(CONTRACT_PATH, root=ROOT)
    pair = next(item for item in contract["profile_pairs"] if item["id"] == pair_id)
    return {
        "timing_scope": pair["timing_scope"],
        "result_contract": pair["result_contract"],
        "metric_contract_id": "metric-contract-v2-365",
        "annualization_days": 365,
        "fee_contract_id": "canonical-one-way-fee-v1",
        "account_contract_id": "linear-quote-gross-cross-v1",
    }


def _route_record(
    *,
    workload_id: str,
    route_id: str,
    pair_id: str,
    identity: Mapping[str, Any],
    python_stats: Mapping[str, Any],
    rust_stats: Mapping[str, Any],
    cold_rss_mb: float,
    parity: Mapping[str, Any],
    data_sha256: str,
    intent_sha256: str,
) -> dict[str, Any]:
    comparator = _result_contract(pair_id)
    artifact_seed = {
        "workload_id": workload_id,
        "route_id": route_id,
        "identity": dict(identity),
        "python": dict(python_stats),
        "rust": dict(rust_stats),
        "parity": dict(parity),
        "data_sha256": data_sha256,
        "intent_sha256": intent_sha256,
    }
    artifact_sha256 = canonical_json_sha256(artifact_seed)
    warm_rss = float(rust_stats["warm_rss_after_mb"])
    faster = float(rust_stats["median_seconds"]) <= (
        float(python_stats["median_seconds"]) * SPEED_PROMOTION_RATIO
    )
    # A process may retain allocator arenas on its first result adaptation.
    # The release gate therefore records the full warm-up delta but judges the
    # bounded steady state from repeated post-warm samples, never by pretending
    # that the first allocation did not occur.
    plateau = float(rust_stats["warm_rss_tail_spread_mb"]) <= RSS_PLATEAU_LIMIT_MB
    evidence = {
        "status": "pass" if parity["passed"] and faster and plateau else "fail",
        "manifest": MANIFEST_PATH,
        "measurement_contract_id": "quantbt-phase72-measurement-contract-v1",
        "route_id": route_id,
        "profile_pair": pair_id,
        "measurement_status": "current_candidate_verified" if parity["passed"] and faster and plateau else "measured",
        "identity_status": "current_candidate" if identity["git_dirty"] is False else "non_clean_candidate",
        "promotion_eligible": bool(identity["git_dirty"] is False and parity["passed"] and faster and plateau),
        "end_to_end_faster_than_python": faster,
        "rss_plateau": plateau,
        "candidate_identity": dict(identity),
        "comparator_contract": {"python": dict(comparator), "native": dict(comparator)},
        "measurement": {
            "sample_count": int(rust_stats["sample_count"]),
            "median_seconds": float(rust_stats["median_seconds"]),
            "p95_seconds": float(rust_stats["p95_seconds"]),
            "cold_rss_mb": float(cold_rss_mb),
            "warm_rss_mb": warm_rss,
            "parity": dict(parity),
            "artifact_sha256": artifact_sha256,
        },
        "python_measurement": dict(python_stats),
        "rust_measurement": dict(rust_stats),
        "fixture_identity": {"data_sha256": data_sha256, "intent_sha256": intent_sha256},
    }
    return evidence


def run(
    *,
    static_bars: int,
    ir_bars: int,
    repeats: int,
    require_auto: bool,
    enforce_gates: bool = True,
) -> dict[str, Any]:
    """Produce Phase-78 evidence for the bounded public routes.

    Static command tapes remain in the certificate because their complete
    result/audit parity is a release invariant. Their public score facade is
    not auto-promoted unless it can maintain a material speed advantage across
    a longer alternating sample. Native Strategy IR score is the sole A4
    promotion target for this release candidate.
    """

    if static_bars < 10_000 or ir_bars < 2_000:
        raise ValueError("Phase 78 requires static_bars >= 10000 and ir_bars >= 2000")
    if repeats < 3:
        raise ValueError("Phase 78 requires at least three timing repeats")
    extension = probe_native_event_rust_extension()
    if not extension.executable:
        raise RuntimeError(f"quantbt-native executable extension is required: {extension.reason}")

    static_frame = _frame(static_bars, start="2026-01-01")
    static_commands = _static_commands(static_frame.index)
    static_python_endpoint = _static_endpoint(backend="python", profile="audit")
    static_rust_endpoint = _static_endpoint(backend="rust", profile="audit")
    static_auto_audit_endpoint = _static_endpoint(backend="auto", profile="audit")
    static_auto_score_endpoint = _static_endpoint(backend="auto", profile="optimize")
    static_rust_score_endpoint = _static_endpoint(backend="rust", profile="optimize")
    static_python_score_endpoint = _static_endpoint(backend="python", profile="optimize")
    # Audit remains the independent public-result parity oracle. It is not the
    # promotion comparator because both backends must materialize the same
    # pandas-facing report surface there.
    static_python = static_python_endpoint.simulate(
        data=static_frame, order_commands=static_commands, symbols=["BTC"]
    )
    static_rust = static_rust_endpoint.simulate(
        data=static_frame, order_commands=static_commands, symbols=["BTC"]
    )
    assert_native_event_full_parity(static_rust, static_python)
    static_auto_audit = static_auto_audit_endpoint.simulate(
        data=static_frame, order_commands=static_commands, symbols=["BTC"]
    )
    assert_native_event_full_parity(static_auto_audit, static_python)
    static_auto_score = static_auto_score_endpoint.simulate(
        data=static_frame, order_commands=static_commands, symbols=["BTC"]
    )
    if static_auto_score.metadata["execution_plan_v1"]["backend"] != "python":
        raise RuntimeError(
            "static public score route must remain Python while its public performance gate is held: "
            + str(static_auto_score.metadata["native_event_promotion_v1"]["reason"])
        )
    static_rust_stats, static_python_stats, _, _ = _measure_pair(
        lambda: static_rust_score_endpoint.simulate(
            data=static_frame, order_commands=static_commands, symbols=["BTC"]
        ),
        lambda: static_python_score_endpoint.simulate(
            data=static_frame, order_commands=static_commands, symbols=["BTC"]
        ),
        repeats=max(repeats, STATIC_STABILITY_REPEATS),
    )

    ir_frame = _frame(ir_bars, start="2026-02-01")
    phase = np.arange(ir_bars, dtype=np.float64)
    signal = np.where(phase % 120 < 40, 1.0, np.where(phase % 120 < 80, 2.0, 0.0)).astype(np.float64)
    ir_python_runner = _ir_runner(ir_frame, backend="python", report_level="audit")
    ir_rust_runner = _ir_runner(ir_frame, backend="rust", report_level="audit")
    ir_auto_runner = _ir_runner(ir_frame, backend="auto", report_level="audit")
    ir_python = ir_python_runner.backtest(signal, report_level="audit")
    ir_rust = ir_rust_runner.backtest(signal, report_level="audit")
    ir_auto = ir_auto_runner.backtest(signal, report_level="audit")
    assert_native_event_full_parity(ir_rust, ir_python)
    assert_native_event_full_parity(ir_auto, ir_python)
    ir_auto_score_runner = _ir_runner(ir_frame, backend="auto", report_level="score")
    ir_rust_score_runner = _ir_runner(ir_frame, backend="rust", report_level="score")
    ir_python_score_runner = _ir_runner(ir_frame, backend="python", report_level="score")
    ir_auto_score_plan = ir_auto_score_runner._plan_for(RunProfile.SCORE, public_result=False)  # noqa: SLF001
    ir_auto_score = ir_auto_score_runner.run_score(signal)
    if require_auto and ir_auto_score_plan.backend.value != "rust":
        raise RuntimeError(
            "Native Strategy IR public score auto route did not resolve Rust: "
            + str(ir_auto_score_plan.promotion_reason)
        )
    ir_rust_stats, ir_python_stats, _, _ = _measure_pair(
        lambda: ir_rust_score_runner.run_score(signal),
        lambda: ir_python_score_runner.run_score(signal),
        repeats=repeats,
    )

    static_data_hash = typed_array_sha256(
        static_frame.index.asi8,
        static_frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=np.float64),
    )
    static_intent_hash = sha256(
        "|".join(f"{item.timestamp.value}:{item.side.value}:{item.qty}:{item.order_id}" for item in static_commands).encode()
    ).hexdigest()
    ir_data_hash = typed_array_sha256(
        ir_frame.index.asi8,
        ir_frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=np.float64),
    )
    ir_intent_hash = typed_array_sha256(signal)
    initial_rss = _current_rss_mb()
    static_identity = _public_measurement_identity(
        warmup_procedure="Phase 78 paired Python/Rust public audit routes after one warm-up; current RSS sampled before and after repeated calls",
        data_sha256=static_data_hash,
        intent_sha256=static_intent_hash,
    )
    ir_identity = _public_measurement_identity(
        warmup_procedure="Phase 78 paired Python/Rust Native Strategy IR public audit routes after one warm-up; current RSS sampled before and after repeated calls",
        data_sha256=ir_data_hash,
        intent_sha256=ir_intent_hash,
    )
    static_parity = {
        "passed": True,
        "canonical_trace_fingerprint": static_rust.metadata["canonical_trace_fingerprint"],
        "auto_backend": static_auto_score.metadata["execution_plan_v1"]["backend"],
        "auto_reason": static_auto_score.metadata["native_event_promotion_v1"]["reason"],
        "minimum_bars": int(static_auto_score.metadata["native_event_promotion_v1"]["minimum_bars"]),
        "audit_backend": static_auto_audit.metadata["execution_plan_v1"]["backend"],
    }
    ir_parity = {
        "passed": True,
        "canonical_trace_fingerprint": ir_rust.metadata["canonical_trace_fingerprint"],
        "auto_backend": ir_auto_score_plan.backend.value,
        "auto_reason": ir_auto_score_plan.promotion_reason,
        "minimum_bars": int(ir_auto_score_plan.promotion_minimum_bars),
        "audit_backend": ir_auto.metadata["execution_plan_v1"]["backend"],
    }
    payload = {
        "schema": "quantbt-phase78-public-promotion-v1",
        "phase": "78",
        "status": "measured",
        "scope": {
            "auto_promotion_workloads": sorted(AUTO_PROMOTION_WORKLOADS),
            "measured_workloads": [STATIC_WORKLOAD, IR_WORKLOAD],
            "non_promotion_observations": {
                STATIC_WORKLOAD: "public_score_performance_not_stable_enough_for_auto",
            },
            "excluded_workloads": [
                "python_callback",
                "reactive",
                "generic_walk_forward",
                "portfolio",
                "package_arbitrage",
                "intrabar",
                "options",
            ],
            "required_auto": bool(require_auto),
            "platform_scope": "local exact native extension; release CI owns published Linux CPython 3.11-3.13 matrix",
        },
        "rss": {
            "process_after_certificate_mb": _current_rss_mb(),
            "process_before_identity_mb": initial_rss,
            "plateau_limit_mb": RSS_PLATEAU_LIMIT_MB,
        },
        "routes": {
            STATIC_WORKLOAD: _route_record(
                workload_id=STATIC_WORKLOAD,
                route_id="public_event_static",
                pair_id="score_to_score_v1",
                identity=static_identity,
                python_stats=static_python_stats,
                rust_stats=static_rust_stats,
                cold_rss_mb=float(static_rust_stats["warm_rss_before_mb"]),
                parity=static_parity,
                data_sha256=static_data_hash,
                intent_sha256=static_intent_hash,
            ),
            IR_WORKLOAD: _route_record(
                workload_id=IR_WORKLOAD,
                route_id="public_native_strategy_ir",
                pair_id="score_to_score_v1",
                identity=ir_identity,
                python_stats=ir_python_stats,
                rust_stats=ir_rust_stats,
                cold_rss_mb=float(ir_rust_stats["warm_rss_before_mb"]),
                parity=ir_parity,
                data_sha256=ir_data_hash,
                intent_sha256=ir_intent_hash,
            ),
        },
    }
    gate_failures: list[str] = []
    for workload_id, evidence in payload["routes"].items():
        violations = current_candidate_evidence_violations(
            evidence,
            load_measurement_contract(CONTRACT_PATH, root=ROOT),
        )
        if violations:
            gate_failures.append("Phase 78 evidence contract failed: " + "; ".join(violations))
        if workload_id not in AUTO_PROMOTION_WORKLOADS:
            continue
        if not evidence["promotion_eligible"]:
            gate_failures.append(
                f"Phase 78 {evidence['route_id']} did not satisfy promotion gates: "
                f"speed={evidence['end_to_end_faster_than_python']} "
                f"(rust={evidence['rust_measurement']['median_seconds']:.6f}s, "
                f"python={evidence['python_measurement']['median_seconds']:.6f}s), "
                f"rss={evidence['rss_plateau']} "
                f"(tail_spread={evidence['rust_measurement']['warm_rss_tail_spread_mb']:.3f}MiB, "
                f"warm_delta={evidence['rust_measurement']['warm_rss_delta_mb']:.3f}MiB, "
                f"limit={RSS_PLATEAU_LIMIT_MB:.3f}MiB), "
                f"clean={evidence['candidate_identity']['git_dirty'] is False}"
            )
    payload["status"] = "pass" if not gate_failures else "not_promotable"
    payload["gate_failures"] = gate_failures
    if gate_failures and enforce_gates:
        raise RuntimeError("; ".join(gate_failures))
    return payload


def registry_evidence(payload: Mapping[str, Any], workload_id: str) -> dict[str, Any]:
    """Extract the fail-closed registry summary for one certified workload."""

    routes = payload.get("routes")
    if not isinstance(routes, Mapping) or workload_id not in routes:
        raise KeyError(f"Phase 78 evidence does not contain workload {workload_id!r}")
    evidence = routes[workload_id]
    if not isinstance(evidence, Mapping):
        raise TypeError("Phase 78 route evidence must be an object")
    return dict(evidence)


def validate_checked_evidence(
    payload: Mapping[str, Any],
    *,
    registry: Mapping[str, Any],
) -> list[str]:
    """Return deterministic violations for the checked public certificate.

    The runtime resolver intentionally consumes a compact registry summary.  A
    release gate must therefore prove that the checked artifact and that exact
    summary are identical, rather than merely checking that both say ``pass``.
    """

    violations: list[str] = []
    if payload.get("schema") != "quantbt-phase78-public-promotion-v1":
        violations.append("unsupported Phase 78 promotion evidence schema")
    if payload.get("phase") != "78" or payload.get("status") != "pass":
        violations.append("Phase 78 promotion evidence is not a passing phase-78 record")
    routes = payload.get("routes")
    if not isinstance(routes, Mapping):
        return [*violations, "Phase 78 promotion evidence has no route map"]
    contract = load_measurement_contract(CONTRACT_PATH, root=ROOT)
    workloads = {
        str(item.get("id")): item
        for item in registry.get("workloads", ())
        if isinstance(item, Mapping)
    }
    rules = {
        str(item.get("workload_id")): item
        for item in registry.get("promotion_policy", {}).get("rules", ())
        if isinstance(item, Mapping)
    }
    summaries = registry.get("performance_evidence")
    if not isinstance(summaries, Mapping):
        return [*violations, "product registry performance_evidence must be an object"]
    target_workloads = payload.get("scope", {}).get("auto_promotion_workloads", ())
    if not isinstance(target_workloads, list) or set(target_workloads) != set(AUTO_PROMOTION_WORKLOADS):
        violations.append("Phase 78 certificate auto-promotion scope drifted")
        target_workloads = []
    for workload_id in (STATIC_WORKLOAD, IR_WORKLOAD):
        evidence = routes.get(workload_id)
        if not isinstance(evidence, Mapping):
            violations.append(f"certificate misses {workload_id}")
            continue
        for violation in current_candidate_evidence_violations(evidence, contract):
            violations.append(f"{workload_id}: {violation}")
        target = workload_id in target_workloads
        if target and evidence.get("promotion_eligible") is not True:
            violations.append(f"{workload_id}: certificate is not promotion eligible")
        if target and evidence.get("end_to_end_faster_than_python") is not True:
            violations.append(f"{workload_id}: end-to-end speed gate did not pass")
        if target and evidence.get("rss_plateau") is not True:
            violations.append(f"{workload_id}: RSS plateau gate did not pass")
        workload = workloads.get(workload_id)
        rule = rules.get(workload_id)
        if target:
            if workload is None or workload.get("maturity") != "promoted" or workload.get("auto_promotion") is not True:
                violations.append(f"{workload_id}: registry workload is not promoted")
            if rule is None or rule.get("enabled") is not True:
                violations.append(f"{workload_id}: registry promotion rule is not enabled")
            if summaries.get(workload_id) != dict(evidence):
                violations.append(f"{workload_id}: registry evidence differs from checked certificate")
        else:
            if workload is None or workload.get("auto_promotion") is not False:
                violations.append(f"{workload_id}: non-target workload must not be auto-promoted")
            if rule is None or rule.get("enabled") is not False:
                violations.append(f"{workload_id}: non-target promotion rule must remain disabled")
    return sorted(set(violations))


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 78 Public Rust Promotion Certificate",
        "",
        "This is route-scoped current-candidate evidence, not a blanket Rust claim.",
        "",
        "| Workload | Rust median | Python median | Rust RSS delta | Admission routing snapshot | Trace parity |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for workload_id, evidence in payload["routes"].items():
        rust = evidence["rust_measurement"]
        python = evidence["python_measurement"]
        parity = evidence["measurement"]["parity"]
        lines.append(
            f"| `{workload_id}` | {rust['median_seconds'] * 1_000:.3f} ms | "
            f"{python['median_seconds'] * 1_000:.3f} ms | {rust['warm_rss_tail_spread_mb']:.3f} MiB tail spread | "
            f"{parity['auto_backend']} ({parity['auto_reason']}) | {parity['passed']} |"
        )
    lines.extend(
        [
            "",
            "This artifact is the immutable pre-enable admission snapshot. Its routing column records the resolver before the registry rule was enabled, avoiding a self-referential benchmark identity. The current Phase 78 policy promotes only Native Strategy IR score at 2,000+ bars. Static command tapes remain Python-auto because their public score advantage did not remain stable across the longer paired sample. Python callbacks, reactive strategies, generic WFO, portfolio/package, intrabar, and options retain their declared policies.",
            "",
            "A4 evidence is not A5 engine-deletion approval. The Python oracle, rollback controls, and the historical NEXT-03 mirror-retirement record remain required until a stable shadow release has been observed and separately approved.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-bars", type=int, default=10_000)
    parser.add_argument("--ir-bars", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-explicit-only",
        action="store_true",
        help="Measure explicit Rust parity before an auto-promotion registry is sealed.",
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Write a non-promotional measurement record even when a route misses a promotion gate.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate a checked artifact and its exact registry summaries without benchmarking.",
    )
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.check:
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
            registry = json.loads(PRODUCT_REGISTRY_PATH.read_text(encoding="utf-8"))
            violations = validate_checked_evidence(payload, registry=registry)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Phase 78 public-promotion certificate check failed: {exc}")
            return 1
        if violations:
            print("Phase 78 public-promotion certificate check failed: " + "; ".join(violations))
            return 1
        print("Phase 78 public-promotion certificate: PASS")
        return 0
    try:
        payload = run(
            static_bars=args.static_bars,
            ir_bars=args.ir_bars,
            repeats=args.repeats,
            require_auto=not args.allow_explicit_only,
            enforce_gates=not args.diagnostic,
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"Phase 78 public-promotion certificate failed: {exc}")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(f"Phase 78 public-promotion certificate written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
