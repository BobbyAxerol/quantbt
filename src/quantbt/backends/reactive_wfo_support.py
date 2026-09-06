"""Reactive WFO contracts, selector bridge, and cold-segment helpers.

The public runtime owns prepared market/session lifecycle. This module owns
value objects and the bridge that lets WalkForwardEngine reuse its established
selection mathematics over opaque reactive score markers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, TYPE_CHECKING

import numpy as np
import pandas as pd

from ..core.runtime_governance import ParallelismPlanV1, RuntimeBudgetV1
from ..optimization.space import stable_params_key
from ..strategies.reactive_wfo import ReactiveWfoTaskV1, reactive_wfo_candidate_id
from ..walkforward import (
    WalkForwardConfig,
    WalkForwardEngine,
    WalkForwardFold,
    WalkForwardTrialRecord,
    _collect_subperiod_sharpes,
    _required_trades_for_index,
    _split_index_into_subperiods,
    _temporal_robustness_stats,
    _trial_to_dict,
    trade_frequency_penalty,
)
from .reactive_wfo_batch import reactive_wfo_marker_key

if TYPE_CHECKING:
    from .reactive_wfo import ReactivePreparedWfoRuntimeV1


_SUPPORTED_MODES = frozenset(
    {
        "mode_1_decay",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    }
)
_SUPPORTED_SCHEDULES = frozenset({"global", "per_fold_decay", "per_fold_causal"})


class ReactiveWalkForwardUnsupported(NotImplementedError):
    """The requested dynamic WFO semantics are not certified by W3."""


@dataclass(frozen=True, slots=True)
class ReactiveWfoRuntimeConfigV1:
    """Explicit resource/scheduling policy for one W3 run.

    ``certified_sequential_v1`` preserves Optuna's one ask/evaluate/tell loop.
    ``throughput_batch_v1`` is a distinct ask-B/evaluate-B/tell-B contract for
    explicit R3B strategies; it is deterministic for its declared seed and
    batch size but intentionally does not claim the sequential TPE sequence.
    The optional process worker is a transport optimization only and is not
    combined with a candidate batch callback.
    """

    worker_mode: str = "inprocess"
    optimizer_schedule: str = "certified_sequential_v1"
    candidate_batch_size: int = 1
    max_inflight_tasks: int = 1
    reference_best_objective: float | None = None
    max_quality_regret: float | None = None
    runtime_budget: RuntimeBudgetV1 = field(default_factory=RuntimeBudgetV1)
    parallelism_plan: ParallelismPlanV1 | None = None

    def __post_init__(self) -> None:
        worker_mode = str(self.worker_mode).lower().strip()
        if worker_mode not in {"inprocess", "process"}:
            raise ValueError("reactive WFO worker_mode must be 'inprocess' or 'process'")
        schedule = str(self.optimizer_schedule).lower().strip()
        if schedule not in {"certified_sequential_v1", "throughput_batch_v1"}:
            raise ValueError(
                "reactive WFO optimizer_schedule must be certified_sequential_v1 or throughput_batch_v1"
            )
        if int(self.candidate_batch_size) <= 0 or int(self.candidate_batch_size) > 64:
            raise ValueError("reactive WFO candidate_batch_size must be in 1..=64")
        if int(self.max_inflight_tasks) <= 0:
            raise ValueError("reactive WFO max_inflight_tasks must be >= 1")
        if schedule == "certified_sequential_v1" and int(self.candidate_batch_size) != 1:
            raise ValueError(
                "certified_sequential_v1 requires candidate_batch_size=1; "
                "use explicit throughput_batch_v1 for a distinct adaptive search contract"
            )
        if int(self.max_inflight_tasks) != 1:
            raise ValueError(
                "reactive WFO currently has one bounded native batch in flight; "
                "max_inflight_tasks must be 1"
            )
        reference = self.reference_best_objective
        threshold = self.max_quality_regret
        if (reference is None) != (threshold is None):
            raise ValueError(
                "reactive WFO reference_best_objective and max_quality_regret must be provided together"
            )
        if reference is not None:
            if not np.isfinite(float(reference)) or float(threshold) < 0.0:
                raise ValueError("reactive WFO quality reference must be finite and max_quality_regret must be >= 0")
        object.__setattr__(self, "worker_mode", worker_mode)
        object.__setattr__(self, "optimizer_schedule", schedule)
        object.__setattr__(self, "candidate_batch_size", int(self.candidate_batch_size))
        object.__setattr__(self, "max_inflight_tasks", int(self.max_inflight_tasks))


@dataclass(frozen=True, slots=True)
class ReactiveWfoScoreMarkerV1:
    """Opaque dynamic-score task returned to the generic WFO selector."""

    task: ReactiveWfoTaskV1
    params: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReactiveWfoFoldResultV1:
    """One cold OOS account segment under the explicit reset-flat contract."""

    fold_id: int
    params: Mapping[str, Any]
    result: Any
    score_metrics: Mapping[str, float]
    task: ReactiveWfoTaskV1
    strategy_state_fingerprint: object


@dataclass(slots=True)
class ReactiveWalkForwardResultV1:
    """Segmented reactive WFO result; it never fabricates a carry equity curve."""

    folds: Sequence[WalkForwardFold]
    params: Mapping[str, Any]
    params_by_fold: Mapping[int, Mapping[str, Any]]
    fold_results: Sequence[ReactiveWfoFoldResultV1]
    fold_table: pd.DataFrame
    trial_table: pd.DataFrame
    candidate_table: pd.DataFrame
    best_trial: Mapping[str, Any]
    metadata: Mapping[str, Any]

    @property
    def oos_output(self):
        """Dynamic WFO has orders/accounts, not a fabricated signal output."""

        return None

    @property
    def segmented_equity(self) -> pd.DataFrame:
        """Return reset-flat fold equity with an explicit fold key."""

        rows: list[pd.DataFrame] = []
        for item in self.fold_results:
            frame = pd.DataFrame(
                {
                    "equity": item.result.equity.to_numpy(dtype=float),
                    "fold_id": int(item.fold_id),
                },
                index=item.result.equity.index,
            )
            rows.append(frame)
        if not rows:
            return pd.DataFrame(columns=("equity", "fold_id"))
        return pd.concat(rows, axis=0)

    def fold_metrics(self) -> pd.DataFrame:
        """Return only honest per-fold account metrics, never a fake stitch."""

        rows = []
        for item in self.fold_results:
            metrics = item.result.full_report()
            rows.append(
                {
                    "fold_id": int(item.fold_id),
                    "start": item.result.equity.index[0],
                    "end": item.result.equity.index[-1],
                    "initial_capital": float(metrics["initial_capital"]),
                    "final_equity": float(metrics["final_equity"]),
                    "total_return_pct": float(metrics["total_return_pct"]),
                    "sharpe": float(metrics["sharpe"]),
                    "max_drawdown_pct": float(metrics["max_drawdown_pct"]),
                    "num_trades": int(metrics["num_trades"]),
                    "liquidated": bool(metrics["liquidated"]),
                }
            )
        return pd.DataFrame(rows)


class _ReactiveSelectionEngine(WalkForwardEngine):
    """Reuse selection formulas while scoring opaque reactive task markers."""

    def __init__(self, *, runtime: "ReactivePreparedWfoRuntimeV1", config: WalkForwardConfig) -> None:
        # ``WalkForwardEngine`` validates endpoint scoring at construction.
        # This stub is never invoked because W3 overrides the batch score
        # boundary below, but retaining the normal config keeps all selection
        # formulas and parameter validation unchanged.
        super().__init__(strategy=_reactive_marker_strategy, config=config, scorer=_reactive_unused_scorer)
        self._reactive_runtime = runtime
        self._precomputed_score_rows: dict[tuple[str, int, str, int, int], dict[str, float]] | None = None
        self._precomputed_failures: dict[tuple[str, int, str, int, int], dict[str, object]] = {}

    def set_precomputed_score_rows(
        self,
        rows: Mapping[tuple[str, int, str, int, int], Mapping[str, float]],
    ) -> None:
        """Install an all-or-nothing R3B fixed-matrix score cache.

        The cache is intentionally exact-keyed by candidate/fold/stage/window.
        A missing key is a contract violation, never a quiet fallback to a
        per-candidate score path that would make batch evidence ambiguous.
        """

        self._precomputed_score_rows = {
            tuple(key): {name: float(value) for name, value in row.items()}
            for key, row in rows.items()
        }
        self._precomputed_failures = {}

    def merge_precomputed_score_rows(
        self,
        rows: Mapping[tuple[str, int, str, int, int], Mapping[str, float]],
    ) -> None:
        """Append one all-or-nothing R3B score stage to the exact-key cache."""

        existing = {} if self._precomputed_score_rows is None else dict(self._precomputed_score_rows)
        for raw_key, raw_row in rows.items():
            key = tuple(raw_key)
            row = {name: float(value) for name, value in raw_row.items()}
            prior = existing.get(key)
            if prior is not None and prior != row:
                raise ReactiveWalkForwardUnsupported(
                    "reactive WFO received conflicting R3B score rows for one candidate/fold/window binding"
                )
            existing[key] = row
        self._precomputed_score_rows = existing

    def merge_precomputed_failures(
        self,
        failures: Mapping[tuple[str, int, str, int, int], Mapping[str, object]],
    ) -> None:
        """Attach exact candidate-local R3B errors to the score cache.

        A batch row can have a valid scalar payload for one candidate while a
        peer is rejected by its own command/wake-plan contract.  The failure is
        carried to the trial ledger and pruned before selection; it never
        becomes an accidental extreme metric that influences a selector.
        """

        for raw_key, raw_failure in failures.items():
            key = tuple(raw_key)
            failure = dict(raw_failure)
            prior = self._precomputed_failures.get(key)
            if prior is not None and prior != failure:
                raise ReactiveWalkForwardUnsupported(
                    "reactive WFO received conflicting R3B failures for one candidate/fold/window binding"
                )
            self._precomputed_failures[key] = failure

    def mark_precomputed_failure(
        self,
        record: WalkForwardTrialRecord,
        *,
        params: Mapping[str, Any],
    ) -> WalkForwardTrialRecord:
        """Turn any native candidate-local error into one excluded trial row."""

        candidate_id = reactive_wfo_candidate_id(params)
        failures = [
            dict(value)
            for key, value in self._precomputed_failures.items()
            if key[0] == candidate_id
        ]
        if not failures:
            return record
        failures.sort(
            key=lambda value: (
                int(value.get("fold_id", -1)),
                str(value.get("stage", "")),
                int(value.get("start_bar", -1)),
            )
        )
        return WalkForwardTrialRecord(
            trial_id=int(record.trial_id),
            params=dict(record.params),
            objective=-np.inf,
            mean_is_sharpe=float(record.mean_is_sharpe),
            mean_oos_sharpe=float(record.mean_oos_sharpe),
            mean_decay=float(record.mean_decay),
            std_decay=float(record.std_decay),
            fold_metrics=list(record.fold_metrics),
            pruned=True,
            selection_metadata={
                **dict(record.selection_metadata),
                "stage": "candidate_local_error",
                "candidate_error_count": int(len(failures)),
                "candidate_errors": tuple(failures),
                "oos_seen_by_optuna": False,
            },
        )

    def _call_strategy_for_indices(
        self,
        data,
        params: dict[str, Any],
        train_index: pd.DatetimeIndex,
        test_index: pd.DatetimeIndex,
        fold: WalkForwardFold,
        context: str = "out-of-sample generation",
    ) -> ReactiveWfoScoreMarkerV1:
        task = self._reactive_runtime.make_task(
            params=params,
            fold=fold,
            evaluation_index=pd.DatetimeIndex(test_index),
            stage=str(context),
        )
        return ReactiveWfoScoreMarkerV1(task=task, params=dict(params))

    def _score_strategy_outputs_batch(self, data, tasks):
        markers: list[ReactiveWfoScoreMarkerV1] = []
        for output, _index, _fold, _params, _context in tasks:
            if not isinstance(output, ReactiveWfoScoreMarkerV1):
                raise TypeError("reactive WFO selection received a non-reactive score marker")
            markers.append(output)
        if self._precomputed_score_rows is not None:
            rows: list[dict[str, float]] = []
            missing: list[tuple[str, int, str, int, int]] = []
            for marker in markers:
                key = reactive_wfo_marker_key(marker)
                row = self._precomputed_score_rows.get(key)
                if row is None:
                    missing.append(key)
                else:
                    rows.append(dict(row))
            if missing:
                raise ReactiveWalkForwardUnsupported(
                    "reactive WFO fixed candidate matrix omitted a precomputed score binding: "
                    f"{missing[0]!r}"
                )
            return rows
        return self._reactive_runtime.score_markers(markers)

    def evaluate_params_is(
        self,
        data,
        folds: Sequence[WalkForwardFold],
        params: Dict[str, Any],
        trial_id: int = 0,
    ) -> WalkForwardTrialRecord:
        """Score Mode 4/5 exclusively through absolute native task windows.

        The generic signal engine builds one train output then slices it for
        each temporal shard.  A reactive strategy owns mutable lifecycle state,
        so slicing an opaque marker would either fail or imply a fictitious
        replay.  Constructing one fresh task per shard preserves the existing
        temporal robustness mathematics while keeping the account, callback
        clock, and command coordinates honest.
        """

        fold_metrics: list[dict[str, object]] = []
        is_scores: list[float] = []
        score_tasks: list[tuple[ReactiveWfoScoreMarkerV1, pd.DatetimeIndex, WalkForwardFold, Dict[str, Any], str]] = []
        fold_work: list[tuple[WalkForwardFold, int, list[tuple[int, pd.DatetimeIndex, int]]]] = []
        for fold in folds:
            is_output = self._call_strategy_for_indices(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.train_index,
                fold=fold,
                context="anti-leakage in-sample search",
            )
            is_task = len(score_tasks)
            score_tasks.append(
                (is_output, fold.train_index, fold, params, "anti-leakage in-sample search")
            )
            shard_tasks: list[tuple[int, pd.DatetimeIndex, int]] = []
            if self.config.optimization_mode in {"mode_4_is_only_robust", "mode_5_full_robust"}:
                for shard_id, shard_index in enumerate(
                    _split_index_into_subperiods(fold.train_index, int(self.config.is_subperiods))
                ):
                    if len(shard_index) < 2:
                        continue
                    shard_output = self._call_strategy_for_indices(
                        data=data,
                        params=params,
                        train_index=fold.train_index,
                        test_index=shard_index,
                        fold=fold,
                        context=f"is-only robustness subperiod {shard_id}",
                    )
                    shard_task = len(score_tasks)
                    score_tasks.append(
                        (
                            shard_output,
                            shard_index,
                            fold,
                            params,
                            f"is-only robustness subperiod {shard_id}",
                        )
                    )
                    shard_tasks.append((shard_id, shard_index, shard_task))
            fold_work.append((fold, is_task, shard_tasks))

        scored = self._score_strategy_outputs_batch(data, score_tasks)
        for fold, is_task, shard_tasks in fold_work:
            is_metrics = scored[is_task]
            required_trades = _required_trades_for_index(
                fold.train_index,
                self.config.min_trades_per_year,
            )
            factor = 1.0 if self.config.trade_penalty_factor is None else float(self.config.trade_penalty_factor)
            penalty = trade_frequency_penalty(is_metrics["trade_count"], required_trades, factor)
            is_sharpe = float(is_metrics["sharpe"] - penalty)
            shard_stats = self._summarize_is_subperiod_metrics(
                [(shard_index, scored[task_index]) for _shard_id, shard_index, task_index in shard_tasks]
            )
            is_scores.append(is_sharpe)
            fold_metrics.append(
                {
                    "fold_id": fold.fold_id,
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "is_sharpe": is_sharpe,
                    "is_sharpe_raw": is_metrics["sharpe"],
                    "is_turnover": is_metrics["turnover"],
                    "is_trade_count": is_metrics["trade_count"],
                    "is_required_trades": required_trades,
                    "is_trade_penalty": penalty,
                    "oos_evaluated": False,
                    **shard_stats,
                }
            )

        mean_is = float(np.mean(is_scores)) if is_scores else 0.0
        temporal_stats = _temporal_robustness_stats(
            _collect_subperiod_sharpes(fold_metrics),
            q25_weight=float(self.config.q25_weight),
            dispersion_penalty=float(self.config.dispersion_penalty),
            fallback=mean_is,
        )
        temporal_stats["is_subperiod_count"] = temporal_stats["temporal_count"]
        return WalkForwardTrialRecord(
            trial_id=int(trial_id),
            params=dict(params),
            objective=mean_is,
            mean_is_sharpe=mean_is,
            mean_oos_sharpe=0.0,
            mean_decay=0.0,
            std_decay=0.0,
            fold_metrics=fold_metrics,
            selection_metadata={
                "stage": "is_search",
                "objective_mode": self.config.optimization_mode,
                "oos_seen_by_optuna": False,
                "reactive_task_windows": "absolute_prepared_market_fresh_account",
                **temporal_stats,
            },
        )


def _reactive_marker_strategy(*_args, **_kwargs):  # pragma: no cover - never executed directly
    raise RuntimeError("reactive WFO strategy markers must be scored by the prepared W3 runtime")


def _reactive_unused_scorer(**_kwargs):  # pragma: no cover - defensive only
    raise RuntimeError("reactive WFO uses its dedicated native score boundary")



def _normalize_fixed_candidate_matrix(
    candidate_matrix: Optional[Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    """Validate and canonically order one non-adaptive R3B candidate matrix.

    Trial identifiers are derived from the stable parameter representation, not
    caller list order.  That makes a fixed matrix reproducible when a service
    serializes candidates through an unordered source.
    """

    if candidate_matrix is None:
        raise ValueError(
            "throughput_batch_v1 requires candidate_matrix=[{...}, ...]; "
            "it does not run an implicit batched Optuna sampler"
        )
    normalized: list[tuple[str, dict[str, Any]]] = []
    expected_keys: tuple[str, ...] | None = None
    seen: set[str] = set()
    for row_id, raw in enumerate(candidate_matrix):
        if not isinstance(raw, Mapping) or not raw:
            raise TypeError(f"candidate_matrix[{row_id}] must be a non-empty parameter mapping")
        params = dict(raw)
        if any(not isinstance(name, str) or not name for name in params):
            raise ValueError(f"candidate_matrix[{row_id}] parameter names must be non-empty strings")
        keys = tuple(sorted(params))
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise ValueError(
                "all throughput_batch_v1 candidate matrix rows must declare the same parameter keys"
            )
        key = stable_params_key(params)
        if key in seen:
            raise ValueError(f"candidate_matrix contains a duplicate parameter row at index {row_id}")
        seen.add(key)
        normalized.append((key, params))
    if not normalized:
        raise ValueError("throughput_batch_v1 candidate_matrix must not be empty")
    return tuple(params for _key, params in sorted(normalized, key=lambda item: item[0]))


def _resolve_candidate_matrix_ranges(
    candidates: Sequence[Mapping[str, Any]],
    param_ranges: Optional[Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Return selector ranges without inventing values outside a fixed matrix."""

    if param_ranges is not None:
        resolved = dict(param_ranges)
        missing = sorted(set(resolved).difference(candidates[0]))
        if missing:
            raise ValueError(
                "candidate_matrix rows omit parameter(s) declared in param_ranges: " + ", ".join(missing)
            )
        return resolved, "caller_declared"

    derived: dict[str, list[Any]] = {}
    for name in sorted(candidates[0]):
        values: list[Any] = []
        seen: set[str] = set()
        for params in candidates:
            value = params[name]
            value_key = stable_params_key({name: value})
            if value_key not in seen:
                seen.add(value_key)
                values.append(value)
        derived[name] = values
    return derived, "derived_from_fixed_candidate_matrix"


def _score_row_from_result(result) -> dict[str, float]:
    report = result.full_report()
    return {
        "sharpe": float(report["sharpe"]),
        "turnover": float(result.metadata.get("total_turnover", 0.0)),
        "trade_count": float(report["num_trades"]),
        "mean_return": float(report["total_return_pct"]) / 100.0,
        "volatility": 0.0,
        "max_drawdown_pct": float(report["max_drawdown_pct"]),
        "profit_factor": float(report["profit_factor"]),
    }


def _records_frame(records: Sequence[WalkForwardTrialRecord]) -> pd.DataFrame:
    rows = []
    for record in records:
        row = _trial_to_dict(record)
        row["selection_metadata"] = dict(record.selection_metadata)
        rows.append(row)
    return pd.DataFrame(rows)


def _fold_table_with_segments(folds: Sequence[WalkForwardFold], results: Sequence[ReactiveWfoFoldResultV1]) -> pd.DataFrame:
    by_fold = {int(item.fold_id): item for item in results}
    rows = []
    for fold in folds:
        item = by_fold[int(fold.fold_id)]
        report = item.result.full_report()
        rows.append(
            {
                "fold_id": int(fold.fold_id),
                "train_start": fold.train_start,
                "train_end": fold.train_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "account_policy": "reset_flat",
                "selected_params": dict(item.params),
                "oos_final_equity": float(report["final_equity"]),
                "oos_sharpe": float(report["sharpe"]),
                "oos_max_drawdown_pct": float(report["max_drawdown_pct"]),
                "oos_num_trades": int(report["num_trades"]),
                "strategy_state_fingerprint": item.strategy_state_fingerprint,
            }
        )
    return pd.DataFrame(rows)


def run_cold_oos_segments(runtime: Any, *, folds, selected, params_by_fold):
    """Audit selected fold parameters on fresh absolute prepared windows."""

    results: list[ReactiveWfoFoldResultV1] = []
    for fold in folds:
        runtime._check_canceled()
        params = dict(params_by_fold.get(int(fold.fold_id), selected.params))
        task = runtime.make_task(
            params=params,
            fold=fold,
            evaluation_index=fold.test_index,
            stage="selected_outer_oos_cold_audit",
        )
        strategy = runtime._adapter.build_strategy(params=params, task=task)
        # A cold audit retains the exact absolute clock used by selection.
        result = runtime._prepared_runner.run_window(
            strategy,
            start_bar=int(task.start_bar),
            end_bar=int(task.end_bar),
        )
        fingerprint = getattr(strategy, "quantbt_state_fingerprint", None)
        results.append(
            ReactiveWfoFoldResultV1(
                fold_id=int(fold.fold_id),
                params=params,
                result=result,
                score_metrics=_score_row_from_result(result),
                task=task,
                strategy_state_fingerprint=fingerprint() if callable(fingerprint) else None,
            )
        )
    return results
