"""Run-local WFO execution reuse and analysis provenance contracts.

The public walk-forward engine remains the authority for strategy lifecycle,
Optuna ordering, selector mathematics, and the final stitched account.  This
module owns only a deliberately narrow optimisation: a completed, pure native
score may be reused by a later *report-only* analysis of the exact same
economic execution in the same WFO run.

The cache never crosses runs or semantic builds, never stores partial/errors,
and never supplies an adaptive Optuna objective.  Those restrictions make the
performance path auditable rather than an implicit change to optimisation
semantics.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


WFO_EVALUATION_RUNTIME_SCHEMA_V1 = "quantbt-wfo-evaluation-runtime-v1"
WFO_TERMINAL_SCORE_CACHE_CONTRACT_V1 = "run_local_terminal_metrics_v1"
WFO_EXECUTION_REUSE_POLICIES_V1 = frozenset({"off", "auto", "require"})


# This is a retention declaration, not a replacement for any selector.  It is
# emitted with result metadata so consumers can see why a particular path did
# or did not become eligible for score reuse.
WFO_MODE_EVALUATION_MATRIX_V1: dict[str, dict[str, object]] = {
    "mode_1_decay": {
        "selection_inputs": ("is_metrics", "oos_metrics", "decay_components"),
        "retention": "fold_metric_rows",
        "score_reuse": "exact_completed_native_execution_only",
    },
    "mode_2_sbb": {
        "selection_inputs": ("is_return_path", "bootstrap_indices", "replicate_statistics"),
        "retention": "one_candidate_fold_return_path_plus_replicate_vector",
        "score_reuse": "proxy_path_authority_no_native_score_reuse",
    },
    "mode_3_flat_minima": {
        "selection_inputs": ("is_metrics", "parameter_coordinates", "plateau_neighborhood"),
        "retention": "candidate_metric_rows_and_plateau_coordinates",
        "score_reuse": "exact_completed_native_execution_only",
    },
    "mode_4_is_only_robust": {
        "selection_inputs": ("is_metrics", "is_subperiod_metrics", "plateau_neighborhood"),
        "retention": "is_subperiod_metric_rows_and_plateau_coordinates",
        "score_reuse": "exact_completed_native_execution_only",
    },
    "mode_5_full_robust": {
        "selection_inputs": ("full_is_metrics", "full_sample_plateau", "temporal_components"),
        "retention": "full_is_metric_rows_and_parameter_plateau",
        "score_reuse": "exact_completed_native_execution_only",
    },
}


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(encoded).hexdigest()


def _hash_parts(*parts: object) -> str:
    """Hash a typed ordered tuple without transient JSON/dict construction."""

    digest = sha256()
    for part in parts:
        encoded = f"{type(part).__qualname__}:{part}".encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def walkforward_mode_evaluation_matrix_v1() -> dict[str, dict[str, object]]:
    """Return a detached mode/retention declaration for public metadata."""

    return {
        mode: {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in details.items()
        }
        for mode, details in WFO_MODE_EVALUATION_MATRIX_V1.items()
    }


@dataclass(frozen=True, slots=True)
class WfoEvaluationIdentityV1:
    """Stable identifiers for one execution-analysis relationship.

    ``trial_id`` remains an optimizer identity.  ``execution_id`` deliberately
    excludes that ordinal only where the same candidate/fold/intent execution
    is safe to reuse; ``execution_attempt_id`` remains unique for every caller
    and therefore never erases duplicate-trial provenance.
    """

    run_id: str
    trial_id: int
    candidate_id: str
    execution_id: str
    execution_attempt_id: str
    analysis_id: str
    selection_id: str
    deployment_id: str

    def metadata(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "trial_id": int(self.trial_id),
            "candidate_id": self.candidate_id,
            "execution_id": self.execution_id,
            "execution_attempt_id": self.execution_attempt_id,
            "analysis_id": self.analysis_id,
            "selection_id": self.selection_id,
            "deployment_id": self.deployment_id,
        }


@dataclass(frozen=True, slots=True)
class WfoExecutionLookupV1:
    """One score-batch cache plan, retaining order without changing it."""

    cached_metrics: tuple[dict[str, float] | None, ...]
    keys: tuple[str | None, ...]
    attempt_rows: tuple[dict[str, object], ...]
    miss_positions: tuple[int, ...]
    lookup_count: int


class WfoExecutionReuseRuntimeV1:
    """Bounded, run-local native score reuse with explicit causal guards.

    A cache entry is a small terminal metric mapping only.  It cannot answer a
    full audit request, cannot stand in for a cancelled/pruned prefix, and is
    released at the end of the public WFO invocation.
    """

    def __init__(
        self,
        *,
        config: Any,
        prepared_context: Any | None,
        strategy_fingerprint: str,
        scorer: Any | None,
    ) -> None:
        metadata = dict(getattr(config, "metadata", {}) or {})
        policy = str(metadata.get("wfo_execution_reuse", "auto")).lower().strip()
        if policy not in WFO_EXECUTION_REUSE_POLICIES_V1:
            allowed = ", ".join(sorted(WFO_EXECUTION_REUSE_POLICIES_V1))
            raise ValueError(f"wfo_execution_reuse must be one of: {allowed}")
        capacity = int(metadata.get("wfo_execution_reuse_max_entries", 4096))
        trace_limit = int(metadata.get("wfo_execution_reuse_trace_limit", 2048))
        if capacity < 0 or trace_limit < 0:
            raise ValueError("WFO execution reuse capacities must be >= 0")

        self._config = config
        self._policy = policy
        self._capacity = capacity
        self._trace_limit = trace_limit
        self._cache: OrderedDict[str, tuple[dict[str, float], str]] = OrderedDict()
        # DatetimeIndex is immutable. Retaining one digest per already-owned
        # WFO task index avoids rebuilding pandas index wrappers for every
        # candidate while keeping an exact timestamp identity for irregular
        # calendars and subperiods.
        self._index_digests: dict[int, tuple[pd.DatetimeIndex, str]] = {}
        self._attempt_rows: list[dict[str, object]] = []
        self._attempt_rows_dropped = 0
        self._attempt_sequence = 0
        self._cache_evictions = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_stores = 0
        self._terminal_score_bars_reused = 0
        self._terminal_score_bars_executed = 0
        self._adaptive_read_bypasses = 0
        self._unsupported_task_bypasses = 0
        self._transient_failures = 0
        self._released = False
        self._selection_id = "pending"
        self._deployment_id = "pending"
        self._context_signature = "unprepared"
        self._config_signature = "unprepared"
        self._data_signature = "unprepared"
        self._contract: dict[str, object] | None = None
        self._enabled = False
        self._reason: str | None = None

        if policy == "off":
            self._reason = "policy_off"
        elif prepared_context is None:
            self._reason = "prepared_context_required"
        elif int(getattr(config, "optuna_trials", 0)) <= 0:
            self._reason = "no_adaptive_study_has_no_post_study_reuse"
        elif str(getattr(config, "optimization_mode", "")).lower().strip() == "mode_5_full_robust":
            # The current full-sample selector does not replay an exact
            # candidate score after the study. Do not charge every trial for a
            # cache that cannot produce a hit; the ordinary trial ledger is
            # still the authority for Mode 5 provenance.
            self._reason = "mode_5_has_no_post_study_exact_score_reuse"
        elif (
            str(getattr(config, "optimization_mode", "")).lower().strip() == "mode_4_is_only_robust"
            and str(getattr(config, "optimization_schedule", "")).lower().strip() == "per_fold_causal"
        ):
            # Strict per-fold Mode 4 selects on IS only and then realizes a
            # distinct outer OOS path. It has no exact post-study score replay
            # in the current certified schedule.
            self._reason = "mode_4_per_fold_causal_has_no_post_study_exact_score_reuse"
        else:
            self._context_signature = str(getattr(prepared_context, "signature", "unavailable"))
            self._config_signature = str(getattr(prepared_context, "config_signature", "unavailable"))
            self._data_signature = str(getattr(prepared_context, "data_signature", "unavailable"))
            contract = self._resolve_contract(scorer)
            if contract is None:
                self._reason = "scorer_has_no_pure_terminal_reuse_contract"
            elif str(getattr(config, "scoring_backend", "")).lower().strip() != "endpoint":
                self._reason = "proxy_or_non_endpoint_scoring_preserved"
            elif str(getattr(config, "strategy_lifecycle_policy", "isolated_v1")) != "isolated_v1":
                self._reason = "strategy_lifecycle_is_not_isolated"
            elif capacity == 0:
                self._reason = "zero_cache_capacity"
            else:
                self._contract = contract
                self._enabled = True
                self._reason = "run_local_pure_terminal_native_metrics"
        if policy == "require" and not self._enabled:
            raise ValueError(f"wfo_execution_reuse='require' is unavailable: {self._reason}")

        self._run_id = _canonical_hash(
            {
                "schema": WFO_EVALUATION_RUNTIME_SCHEMA_V1,
                "context_signature": self._context_signature,
                "config_signature": self._config_signature,
                "data_signature": self._data_signature,
                "strategy_fingerprint": str(strategy_fingerprint),
                "contract": self._contract,
            }
        )
        self._strategy_fingerprint = str(strategy_fingerprint)

    @staticmethod
    def _resolve_contract(scorer: Any | None) -> dict[str, object] | None:
        if scorer is None:
            return None
        getter = getattr(scorer, "wfo_execution_reuse_contract", None)
        raw = getter() if callable(getter) else getter
        if not isinstance(raw, Mapping):
            return None
        contract = dict(raw)
        if contract.get("contract") != WFO_TERMINAL_SCORE_CACHE_CONTRACT_V1:
            return None
        if not bool(contract.get("pure_terminal_metrics", False)):
            return None
        if not bool(contract.get("fresh_account_per_evaluation", False)):
            return None
        if not bool(contract.get("deterministic_given_contract", False)):
            return None
        if bool(contract.get("cross_run_reuse", False)):
            return None
        if not contract.get("engine_semantic_build") or not contract.get("numeric_contract"):
            return None
        # The public WFO scorer receives a human-readable stage/context for
        # diagnostics. Reuse can cross two labels only when the scorer states
        # explicitly that the label cannot alter the terminal metric.
        if "score_context_affects_terminal_metrics" not in contract:
            return None
        return contract

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and not self._released)

    def lookup(
        self,
        tasks: Sequence[tuple[Any, pd.DatetimeIndex, Any, Mapping[str, Any], str]],
        *,
        scope: Mapping[str, object] | None,
    ) -> WfoExecutionLookupV1:
        """Plan a deterministic cache lookup without dispatching any work."""

        active_scope = dict(scope or {})
        adaptive = bool(active_scope.get("adaptive_optimizer", False))
        cached: list[dict[str, float] | None] = []
        keys: list[str | None] = []
        attempts: list[dict[str, object]] = []
        misses: list[int] = []
        lookup_count = 0

        for ordinal, task in enumerate(tasks):
            key, candidate_id, reason = self._semantic_key(task, scope=active_scope)
            identity = self._new_identity(
                key=key,
                candidate_id=candidate_id,
                scope=active_scope,
                ordinal=ordinal,
            )
            row: dict[str, object] = {
                **identity.metadata(),
                "task_ordinal": int(ordinal),
                "task_bars": int(len(task[1])),
                "stage": str(active_scope.get("stage", "unspecified")),
                "study_id": int(active_scope.get("study_id", 0)),
                "rng_seed": int(active_scope.get("rng_seed", getattr(self._config, "random_seed", 0))),
                "adaptive_optimizer": adaptive,
                "status": "pending",
                "reuse_reason": reason,
                "reused_from_execution_attempt_id": None,
            }
            metric: dict[str, float] | None = None
            if key is None or not self.enabled:
                self._unsupported_task_bypasses += int(key is None)
                row["status"] = "cache_bypass"
                misses.append(ordinal)
            elif adaptive:
                # Current public Optuna code does not issue intermediate
                # reports, but we still do not read a cache while it is
                # adaptively sampling.  A later candidate-analysis pass may
                # safely reuse this completed exact metric.
                self._adaptive_read_bypasses += 1
                row["status"] = "adaptive_store_only"
                misses.append(ordinal)
            else:
                lookup_count += 1
                entry = self._cache.get(key)
                if entry is None:
                    self._cache_misses += 1
                    row["status"] = "cache_miss"
                    misses.append(ordinal)
                else:
                    values, source_attempt = entry
                    self._cache.move_to_end(key)
                    metric = dict(values)
                    self._cache_hits += 1
                    self._terminal_score_bars_reused += int(row["task_bars"])
                    row["status"] = "cache_hit"
                    row["reused_from_execution_attempt_id"] = source_attempt
            self._append_attempt(row)
            cached.append(metric)
            keys.append(key)
            attempts.append(row)

        return WfoExecutionLookupV1(
            cached_metrics=tuple(cached),
            keys=tuple(keys),
            attempt_rows=tuple(attempts),
            miss_positions=tuple(misses),
            lookup_count=int(lookup_count),
        )

    def commit(
        self,
        lookup: WfoExecutionLookupV1,
        *,
        metrics_by_position: Mapping[int, Mapping[str, object]],
    ) -> None:
        """Record complete score outcomes and cache only safe terminal rows."""

        for position in lookup.miss_positions:
            row = lookup.attempt_rows[position]
            raw = metrics_by_position.get(int(position))
            if raw is None:
                row["status"] = "transient_failure"
                self._transient_failures += 1
                continue
            metrics = self._compact_metrics(raw)
            if metrics is None:
                row["status"] = "uncacheable_metric_payload"
                continue
            row["status"] = "executed"
            self._terminal_score_bars_executed += int(row["task_bars"])
            key = lookup.keys[position]
            if key is None or not self.enabled:
                continue
            if int(self._capacity) <= 0:
                continue
            # Only completed terminal rows become a future report-only source.
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (metrics, str(row["execution_attempt_id"]))
            self._cache_stores += 1
            while len(self._cache) > int(self._capacity):
                self._cache.popitem(last=False)
                self._cache_evictions += 1

    def mark_batch_failure(self, lookup: WfoExecutionLookupV1) -> None:
        """Ensure a scorer exception never leaves a fake completed cache row."""

        for position in lookup.miss_positions:
            row = lookup.attempt_rows[position]
            if row.get("status") in {"pending", "adaptive_store_only", "cache_miss", "cache_bypass"}:
                row["status"] = "transient_failure"
                self._transient_failures += 1

    def finalize_selection(self, *, selected_params: Mapping[str, object], deployment_scope: Mapping[str, object]) -> None:
        """Attach cold-path selection/deployment IDs after the selector finishes."""

        candidate = _canonical_hash({"params": dict(selected_params)})
        self._selection_id = _canonical_hash(
            {"run_id": self._run_id, "selected_candidate_id": candidate, "stage": "selection"}
        )
        self._deployment_id = _canonical_hash(
            {
                "run_id": self._run_id,
                "selection_id": self._selection_id,
                "deployment_scope": dict(deployment_scope),
            }
        )
        for row in self._attempt_rows:
            row["selection_id"] = self._selection_id
            row["deployment_id"] = self._deployment_id

    def metadata(self, *, released: bool = False) -> dict[str, object]:
        """Return detached diagnostics without exposing cached metric mappings."""

        retained = [dict(row) for row in self._attempt_rows]
        return {
            "schema": WFO_EVALUATION_RUNTIME_SCHEMA_V1,
            "requested_policy": self._policy,
            "resolved_policy": (
                "enabled_then_released"
                if released and self._enabled
                else "enabled"
                if self.enabled
                else "disabled"
            ),
            "reason": self._reason,
            "run_local": True,
            "cross_run_reuse": False,
            "cache_payload": "completed_terminal_metric_mapping_only",
            "cache_lookup_policy": "post_adaptive_analysis_only_v1",
            "intermediate_checkpoint_replay": "not_needed_current_terminal_objective; adaptive_reads_bypassed",
            "run_id": self._run_id,
            "selection_id": self._selection_id,
            "deployment_id": self._deployment_id,
            "context_signature": self._context_signature,
            "data_signature": self._data_signature,
            "config_signature": self._config_signature,
            "strategy_fingerprint": self._strategy_fingerprint,
            "semantic_contract": None if self._contract is None else dict(self._contract),
            "capacity": int(self._capacity),
            "cache_entries": int(len(self._cache)),
            "cache_entries_released": bool(released),
            "cache_hits": int(self._cache_hits),
            "cache_misses": int(self._cache_misses),
            "cache_stores": int(self._cache_stores),
            "terminal_score_bars_reused": int(self._terminal_score_bars_reused),
            "terminal_score_bars_executed": int(self._terminal_score_bars_executed),
            "cache_evictions": int(self._cache_evictions),
            "adaptive_read_bypasses": int(self._adaptive_read_bypasses),
            "unsupported_task_bypasses": int(self._unsupported_task_bypasses),
            "transient_failures_not_cached": int(self._transient_failures),
            "attempt_rows_retained": int(len(retained)),
            "attempt_rows_dropped": int(self._attempt_rows_dropped),
            "attempt_ledger": retained,
            "mode_evaluation_matrix": walkforward_mode_evaluation_matrix_v1(),
            "streaming_reducer_contract": {
                "mode_2_sbb": "one_candidate_fold_replicate_vector_v1",
                "replicate_by_bar_by_candidate_tensor": "never_constructed_by_wfo_reducer",
                "rng_and_reduction": "existing_mode2_seed_indices_formula_and_numpy_reduction_order",
            },
        }

    def close(self) -> dict[str, object]:
        """Release terminal metric cache while preserving detached provenance."""

        before = len(self._cache)
        self._cache.clear()
        self._index_digests.clear()
        self._released = True
        payload = self.metadata(released=True)
        payload["cache_entries_before_release"] = int(before)
        payload["cache_entries"] = 0
        return payload

    def _append_attempt(self, row: dict[str, object]) -> None:
        if len(self._attempt_rows) < int(self._trace_limit):
            self._attempt_rows.append(row)
        else:
            self._attempt_rows_dropped += 1

    def _new_identity(
        self,
        *,
        key: str | None,
        candidate_id: str,
        scope: Mapping[str, object],
        ordinal: int,
    ) -> WfoEvaluationIdentityV1:
        self._attempt_sequence += 1
        trial_id = int(scope.get("trial_id", -1))
        execution_id = key or _canonical_hash(
            {
                "run_id": self._run_id,
                "candidate_id": candidate_id,
                "trial_id": trial_id,
                "ordinal": int(ordinal),
                "uncacheable": True,
            }
        )
        # IDs are logical provenance keys, not untrusted data hashes. The
        # execution ID is already cryptographically content-addressed; deriving
        # its per-attempt/analysis children avoids several JSON+SHA passes on
        # every adaptive score while preserving uniqueness and trace joins.
        execution_attempt_id = f"{execution_id}:attempt:{self._attempt_sequence}:{trial_id}"
        analysis_id = f"{execution_id}:analysis:terminal_metric_contract_v1"
        return WfoEvaluationIdentityV1(
            run_id=self._run_id,
            trial_id=trial_id,
            candidate_id=candidate_id,
            execution_id=execution_id,
            execution_attempt_id=execution_attempt_id,
            analysis_id=analysis_id,
            selection_id=self._selection_id,
            deployment_id=self._deployment_id,
        )

    def _semantic_key(
        self,
        task: tuple[Any, pd.DatetimeIndex, Any, Mapping[str, Any], str],
        *,
        scope: Mapping[str, object],
    ) -> tuple[str | None, str, str]:
        output, index, fold, params, context = task
        candidate_id = str(scope.get("candidate_id") or _canonical_hash({"params": dict(params)}))
        if not self._enabled:
            return None, candidate_id, self._reason or "disabled"
        digest = _series_intent_digest(output, index)
        if digest is None:
            return None, candidate_id, "non_scalar_or_noncontiguous_intent"
        index_digest = self._index_digest(index)
        if index_digest is None:
            return None, candidate_id, "noncanonical_or_empty_task_index"
        role = _data_role(index, fold)
        # ``run_id`` already commits context/config/data/strategy/contract
        # identities. Keeping their hashes in every task key was redundant and
        # made cache lookup slower than a short prepared native score on small
        # folds. The execution key still commits every semantic field through
        # that immutable run identity plus the task-specific payload below.
        context_identity = (
            str(context)
            if bool(self._contract and self._contract.get("score_context_affects_terminal_metrics", False))
            else "context_diagnostic_only"
        )
        key = _hash_parts(
            WFO_EVALUATION_RUNTIME_SCHEMA_V1,
            self._run_id,
            candidate_id,
            int(scope.get("study_id", 0)),
            int(getattr(fold, "fold_id", -1)),
            _timestamp_ns(getattr(fold, "train_start", None)),
            _timestamp_ns(getattr(fold, "train_end", None)),
            _timestamp_ns(getattr(fold, "test_start", None)),
            _timestamp_ns(getattr(fold, "test_end", None)),
            str(getattr(fold, "account_policy", "")),
            role,
            context_identity,
            index_digest,
            int(index.asi8[0]),
            int(index.asi8[-1]),
            int(len(index)),
            digest,
            "walkforward_config_seed_v1",
            int(scope.get("rng_seed", getattr(self._config, "random_seed", 0))),
            int(scope.get("trial_id", -1)),
            "complete_terminal_execution",
        )
        return key, candidate_id, "exact_semantic_key"

    def _index_digest(self, index: Any) -> str | None:
        """Return one exact timestamp digest for an immutable task index."""

        if not isinstance(index, pd.DatetimeIndex) or len(index) == 0 or index.tz is None:
            return None
        cached = self._index_digests.get(id(index))
        if cached is not None and cached[0] is index:
            return cached[1]
        timestamps = index.asi8
        if timestamps.ndim != 1 or not timestamps.flags.c_contiguous:
            return None
        digest = sha256(memoryview(timestamps).cast("B")).hexdigest()
        self._index_digests[id(index)] = (index, digest)
        return digest

    @staticmethod
    def _compact_metrics(raw: Mapping[str, object]) -> dict[str, float] | None:
        required = ("sharpe", "turnover", "trade_count")
        if not all(name in raw for name in required):
            return None
        metrics: dict[str, float] = {}
        for name, value in raw.items():
            if isinstance(value, (bool, np.bool_)):
                return None
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            # Objective inputs must be finite.  Report-only fields such as
            # profit factor may legitimately be infinite when a path has no
            # realized losses; preserve that exact value rather than disabling
            # an otherwise valid completed execution cache entry.
            if name in required and not np.isfinite(numeric):
                return None
            if np.isnan(numeric):
                return None
            metrics[str(name)] = numeric
        return metrics


def _series_intent_digest(output: Any, index: pd.DatetimeIndex) -> str | None:
    """Hash the validated native-ready values without an O(T) shadow copy.

    WalkForwardEngine calls this only after `validate_walkforward_strategy_output`
    has checked index coverage, UTC alignment, finite values, and the declared
    intent contract. The task index has its own exact immutable digest in the
    semantic key, so rebuilding and comparing pandas indexes here would add
    repeated object work without strengthening the effective score input.
    """

    if not isinstance(output, pd.Series):
        return None
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return None
    values = output.to_numpy(copy=False)
    if values.dtype != np.float64 or values.ndim != 1 or not values.flags.c_contiguous:
        return None
    return sha256(memoryview(values).cast("B")).hexdigest()


def _data_role(index: pd.DatetimeIndex, fold: Any) -> str:
    train = getattr(fold, "train_index", None)
    test = getattr(fold, "test_index", None)
    if train is not None and index.equals(train):
        return "in_sample"
    if test is not None and index.equals(test):
        return "out_of_sample"
    return "declared_subperiod"


def _timestamp_ns(value: Any) -> int | None:
    if isinstance(value, pd.Timestamp):
        return int(value.value)
    try:
        return int(pd.Timestamp(value).value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "WFO_EVALUATION_RUNTIME_SCHEMA_V1",
    "WFO_EXECUTION_REUSE_POLICIES_V1",
    "WFO_MODE_EVALUATION_MATRIX_V1",
    "WFO_TERMINAL_SCORE_CACHE_CONTRACT_V1",
    "WfoEvaluationIdentityV1",
    "WfoExecutionLookupV1",
    "WfoExecutionReuseRuntimeV1",
    "walkforward_mode_evaluation_matrix_v1",
]
