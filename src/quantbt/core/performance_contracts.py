"""Performance-planning and measurement contracts for public QuantBT routes.

The types in this module deliberately do not own market, account, or metric
state.  They make retention, observation, and timing requirements explicit so
future optimizations can remove duplicate work without silently changing the
economic contract.  The authoritative financial reducers remain the existing
backend-specific implementations.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from threading import Lock
from time import perf_counter_ns
from typing import Any, Iterator, Mapping


REQUIRED_COMPUTATION_PLAN_SCHEMA_V1 = "quantbt-required-computation-plan-v1"
EXCLUSIVE_WORK_PROFILER_SCHEMA_V1 = "quantbt-exclusive-work-profiler-v1"

EXCLUSIVE_WORK_STAGES_V1 = (
    "prepare_validate_ingest",
    "advance_match_account_wake",
    "projection_python_decision_command_write_ingest",
    "metrics_analysis_audit_encode_flush_public_adapt",
    "reset_cache_lookup_queue_wait",
)

ACTIVITY_COUNTERS_V1 = (
    "native_outer_entries",
    "python_strategy_entries",
    "python_callback_entries",
    "python_to_native_getter_calls",
    "python_to_native_writer_calls",
    "command_ingest_batches",
    "metric_observation_passes",
    "audit_rows_encoded",
    "audit_flushes",
    "cache_lookup_events",
    "session_resets",
    "worker_pool_starts",
)

_KNOWN_WFO_MODES = frozenset(
    {
        "none",
        "mode_1_decay",
        "mode_2_sbb",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    }
)
_MISSING = object()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ObservationIdV1:
    """One semantic observation, separate from fills and presentation reads.

    ``kind`` is intentionally part of the ID: a return observation and a fill
    occurring on the same bar are not interchangeable inputs to reducers.
    """

    stream: str
    kind: str
    ordinal: int
    subsequence: int = 0

    def __post_init__(self) -> None:
        if not self.stream.strip() or not self.kind.strip():
            raise ValueError("observation stream and kind must be non-empty")
        if int(self.ordinal) < 0 or int(self.subsequence) < 0:
            raise ValueError("observation ordinal and subsequence must be >= 0")

    @property
    def token(self) -> str:
        return f"{self.stream}:{self.kind}:{int(self.ordinal)}:{int(self.subsequence)}"


class ObservationLedgerV1:
    """Deduplicate reducer updates without conflating independent reducers.

    A reader can inspect the same observation many times, but one named reducer
    can claim it only once.  This is a small contract object used for planning
    and tests; it never mutates account state or replaces the native reducer.
    """

    def __init__(self, *, allowed_reducers: tuple[str, ...]) -> None:
        if not allowed_reducers or any(not item.strip() for item in allowed_reducers):
            raise ValueError("observation ledger requires non-empty reducer identifiers")
        if len(set(allowed_reducers)) != len(allowed_reducers):
            raise ValueError("observation ledger reducer identifiers must be unique")
        self._allowed = frozenset(allowed_reducers)
        self._claims: set[tuple[str, str]] = set()
        self._counts = {name: 0 for name in allowed_reducers}

    def claim(self, observation: ObservationIdV1, reducer: str) -> bool:
        """Return whether ``reducer`` may process this exact observation now."""

        if reducer not in self._allowed:
            raise ValueError(f"unknown observation reducer: {reducer}")
        key = (observation.token, reducer)
        if key in self._claims:
            return False
        self._claims.add(key)
        self._counts[reducer] += 1
        return True

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": "quantbt-observation-ledger-v1",
            "claimed_observation_reducer_pairs": len(self._claims),
            "reducer_observation_counts": dict(self._counts),
        }


@dataclass(frozen=True, slots=True)
class RequiredComputationPlanV1:
    """Compiled, immutable requirements for one public WFO invocation.

    The plan is a declaration and compatibility guard, not a second evaluator.
    It describes what the already-authoritative accounting and metric paths must
    retain for selection, reporting, and audit consumers.
    """

    route_id: str
    optimization_mode: str
    optimization_schedule: str
    scoring_backend: str
    financial_retention: str
    research_retention: str
    required_observation_kinds: tuple[str, ...]
    required_intermediate_paths: tuple[str, ...]
    reducers: tuple[str, ...]
    output_sinks: tuple[str, ...]
    requires_intermediate_checkpoints: bool
    opaque_custom_metric: bool
    native_score_eligible: bool
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, values in (
            ("required_observation_kinds", self.required_observation_kinds),
            ("required_intermediate_paths", self.required_intermediate_paths),
            ("reducers", self.reducers),
            ("output_sinks", self.output_sinks),
        ):
            if not values or any(not value.strip() for value in values):
                raise ValueError(f"{label} must contain non-empty identifiers")
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must not contain duplicates")
        if self.opaque_custom_metric and self.native_score_eligible:
            raise ValueError("opaque custom metrics cannot claim scalar-native score eligibility")

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(
            {
                "schema": REQUIRED_COMPUTATION_PLAN_SCHEMA_V1,
                "route_id": self.route_id,
                "optimization_mode": self.optimization_mode,
                "optimization_schedule": self.optimization_schedule,
                "scoring_backend": self.scoring_backend,
                "financial_retention": self.financial_retention,
                "research_retention": self.research_retention,
                "required_observation_kinds": self.required_observation_kinds,
                "required_intermediate_paths": self.required_intermediate_paths,
                "reducers": self.reducers,
                "output_sinks": self.output_sinks,
                "requires_intermediate_checkpoints": self.requires_intermediate_checkpoints,
                "opaque_custom_metric": self.opaque_custom_metric,
                "native_score_eligible": self.native_score_eligible,
                "notes": self.notes,
            }
        )

    def observation_ledger(self) -> ObservationLedgerV1:
        return ObservationLedgerV1(allowed_reducers=self.reducers)

    def require_native_score_eligibility(self) -> None:
        """Fail closed before a scalar-only native score loses opaque inputs."""

        if not self.native_score_eligible:
            raise ValueError(
                "the required computation plan retains opaque custom-metric inputs; "
                "a scalar-only native score route is not eligible"
            )

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": REQUIRED_COMPUTATION_PLAN_SCHEMA_V1,
            "route_id": self.route_id,
            "optimization_mode": self.optimization_mode,
            "optimization_schedule": self.optimization_schedule,
            "scoring_backend": self.scoring_backend,
            "financial_retention": self.financial_retention,
            "research_retention": self.research_retention,
            "required_observation_kinds": list(self.required_observation_kinds),
            "required_intermediate_paths": list(self.required_intermediate_paths),
            "reducers": list(self.reducers),
            "output_sinks": list(self.output_sinks),
            "requires_intermediate_checkpoints": bool(self.requires_intermediate_checkpoints),
            "opaque_custom_metric": bool(self.opaque_custom_metric),
            "native_score_eligible": bool(self.native_score_eligible),
            "fingerprint": self.fingerprint,
            "notes": list(self.notes),
        }


def compile_walkforward_computation_plan(config: Any) -> RequiredComputationPlanV1:
    """Compile conservative WFO retention requirements from a config object.

    Unknown/opaque custom metric declarations deliberately retain the complete
    execution observation stream.  The function accepts a duck-typed config to
    avoid coupling this contract module to ``WalkForwardConfig``.
    """

    mode = str(getattr(config, "optimization_mode", "")).lower().strip()
    if mode not in _KNOWN_WFO_MODES:
        raise ValueError(f"unsupported walk-forward optimization mode for computation plan: {mode!r}")
    schedule = str(getattr(config, "optimization_schedule", "global")).lower().strip()
    scoring_backend = str(getattr(config, "scoring_backend", "endpoint")).lower().strip()
    metadata = dict(getattr(config, "metadata", {}) or {})
    custom_requirements = metadata.get("custom_metric_requirements", _MISSING)
    opaque_custom_metric = custom_requirements is not _MISSING and not isinstance(custom_requirements, Mapping)
    compact_ledger = bool(metadata.get("compact_trial_ledger", True))

    observation_kinds = ["bar_close_equity", "return_sample", "trade_count", "selection_metric"]
    intermediate_paths = ["terminal_account_snapshot", "return_observation_stream", "candidate_fold_metric_rows"]
    reducers = ["standard_metrics", "trade_frequency", "selection_objective"]
    notes = [
        "Native MetricContractV2 remains the score-route authority where eligible.",
        "A fill event and a return observation have distinct observation IDs.",
    ]
    if mode == "none":
        notes.append("No Optuna selection is requested; the declared/fixed parameter replay remains fully observable.")
    elif mode == "mode_1_decay":
        observation_kinds.append("is_oos_decay_pair")
        intermediate_paths.append("fold_decay_components")
        reducers.append("decay_selector")
    elif mode == "mode_2_sbb":
        observation_kinds.append("bootstrap_return_path")
        intermediate_paths.append("stationary_bootstrap_return_input")
        reducers.append("bootstrap_selector")
    elif mode == "mode_3_flat_minima":
        intermediate_paths.append("parameter_plateau_coordinates")
        reducers.append("flat_minima_selector")
    elif mode == "mode_4_is_only_robust":
        observation_kinds.append("is_subperiod_metric")
        intermediate_paths.extend(("is_subperiod_metric_rows", "parameter_plateau_coordinates"))
        reducers.extend(("temporal_robustness", "plateau_selector"))
    else:  # mode_5_full_robust
        intermediate_paths.append("full_is_parameter_plateau")
        reducers.append("full_sample_robustness")

    if opaque_custom_metric:
        intermediate_paths.append("full_execution_observation_stream")
        reducers.append("opaque_custom_metric")
        notes.append(
            "An undeclared custom metric uses the conservative complete-input fallback; scalar-only scoring is disabled."
        )

    sinks = [
        "public_walk_forward_metadata",
        "stitched_oos_output",
        "fold_table",
        "trial_ledger_compact" if compact_ledger else "trial_ledger_full",
        "candidate_ledger",
    ]
    if bool(getattr(config, "optuna_trials", 0)):
        sinks.append("pruner_checkpoint_stream")
    return RequiredComputationPlanV1(
        route_id="QuantBTEndpoint.walk_forward",
        optimization_mode=mode,
        optimization_schedule=schedule,
        scoring_backend=scoring_backend,
        financial_retention="candidate_score_plus_final_endpoint_account",
        research_retention="compact_trial_ledger" if compact_ledger else "full_trial_ledger",
        required_observation_kinds=tuple(observation_kinds),
        required_intermediate_paths=tuple(intermediate_paths),
        reducers=tuple(reducers),
        output_sinks=tuple(sinks),
        requires_intermediate_checkpoints=bool(getattr(config, "optuna_trials", 0)),
        opaque_custom_metric=opaque_custom_metric,
        native_score_eligible=not opaque_custom_metric,
        notes=tuple(notes),
    )


class ExclusiveWorkProfilerV1:
    """Collect non-overlapping public-route timings and explicit counters.

    The profiler is opt-in and does not make scheduling/accounting decisions.
    It refuses nested named stages so a wall-time sample cannot be accidentally
    added to two buckets.  Aggregate worker CPU time is intentionally optional:
    a Python facade cannot honestly infer it from wall time.
    """

    def __init__(self, *, enabled: bool, route_id: str) -> None:
        if not str(route_id).strip():
            raise ValueError("profiler route_id must be non-empty")
        self.enabled = bool(enabled)
        self.route_id = str(route_id)
        self._started_ns = perf_counter_ns()
        self._active_stage: str | None = None
        self._active_started_ns: int | None = None
        self._elapsed_ns = {stage: 0 for stage in EXCLUSIVE_WORK_STAGES_V1}
        self._calls = {stage: 0 for stage in EXCLUSIVE_WORK_STAGES_V1}
        self._activity: dict[str, int | None] = {name: None for name in ACTIVITY_COUNTERS_V1}
        self._aggregate_worker_cpu_ns: int | None = None
        self._lock = Lock()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Measure one exclusive stage, or become a no-op when disabled."""

        if not self.enabled:
            yield
            return
        self.begin(name)
        try:
            yield
        finally:
            self.end(name)

    def begin(self, name: str) -> None:
        if not self.enabled:
            return
        self._validate_stage(name)
        with self._lock:
            if self._active_stage is not None:
                raise RuntimeError(
                    "exclusive work profiler does not allow nested stages: "
                    f"active={self._active_stage!r}, requested={name!r}"
                )
            self._active_stage = name
            self._active_started_ns = perf_counter_ns()

    def end(self, name: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._active_stage != name or self._active_started_ns is None:
                raise RuntimeError(f"exclusive work profiler stage is not active: {name!r}")
            elapsed = max(0, perf_counter_ns() - self._active_started_ns)
            self._elapsed_ns[name] += elapsed
            self._calls[name] += 1
            self._active_stage = None
            self._active_started_ns = None

    def record_elapsed(self, name: str, elapsed_ns: int, *, calls: int = 1) -> None:
        """Record an externally measured non-overlapping stage duration."""

        if not self.enabled:
            return
        self._validate_stage(name)
        if int(elapsed_ns) < 0 or int(calls) < 0:
            raise ValueError("profiler elapsed_ns and calls must be >= 0")
        with self._lock:
            if self._active_stage is not None:
                raise RuntimeError("cannot record an external stage while another profiler stage is active")
            self._elapsed_ns[name] += int(elapsed_ns)
            self._calls[name] += int(calls)

    def add_activity(self, name: str, amount: int = 1) -> None:
        """Record an observed boundary count without inventing zero values."""

        if not self.enabled:
            return
        if name not in self._activity:
            raise ValueError(f"unknown profiler activity counter: {name}")
        if int(amount) < 0:
            raise ValueError("profiler activity amount must be >= 0")
        with self._lock:
            previous = self._activity[name]
            self._activity[name] = int(amount) if previous is None else int(previous) + int(amount)

    def set_aggregate_worker_cpu_ns(self, value: int | None) -> None:
        if not self.enabled:
            return
        if value is not None and int(value) < 0:
            raise ValueError("aggregate worker CPU time must be >= 0 or None")
        with self._lock:
            self._aggregate_worker_cpu_ns = None if value is None else int(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._active_stage is not None:
                raise RuntimeError("cannot snapshot an exclusive profiler with an active stage")
            wall_elapsed = max(0, perf_counter_ns() - self._started_ns) if self.enabled else None
            return {
                "schema": EXCLUSIVE_WORK_PROFILER_SCHEMA_V1,
                "enabled": self.enabled,
                "route_id": self.route_id,
                "wall_elapsed_ns": wall_elapsed,
                "aggregate_worker_cpu_ns": self._aggregate_worker_cpu_ns,
                "exclusive_stage_elapsed_ns": dict(self._elapsed_ns),
                "exclusive_stage_calls": dict(self._calls),
                "activity_counters": dict(self._activity),
                "counter_semantics": {
                    "null": "not measured by this route; zero means measured zero",
                    "native_outer_entries": "Python-to-native prepared score batch calls",
                    "python_strategy_entries": "WFO strategy generation entries",
                    "python_callback_entries": "reactive callback entries; not measured by generic WFO",
                    "python_to_native_getter_calls": "inside-callback native getter crossings; not measured by generic WFO",
                    "python_to_native_writer_calls": "inside-callback native writer crossings; not measured by generic WFO",
                },
            }

    @staticmethod
    def _validate_stage(name: str) -> None:
        if name not in EXCLUSIVE_WORK_STAGES_V1:
            raise ValueError(f"unknown exclusive profiler stage: {name}")


__all__ = [
    "ACTIVITY_COUNTERS_V1",
    "EXCLUSIVE_WORK_PROFILER_SCHEMA_V1",
    "EXCLUSIVE_WORK_STAGES_V1",
    "ExclusiveWorkProfilerV1",
    "ObservationIdV1",
    "ObservationLedgerV1",
    "REQUIRED_COMPUTATION_PLAN_SCHEMA_V1",
    "RequiredComputationPlanV1",
    "compile_walkforward_computation_plan",
]
