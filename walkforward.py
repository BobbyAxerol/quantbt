"""
quantbt.walkforward
-------------------
WalkForwardEngine foundation.

This module intentionally stays orchestration-focused. It builds time-safe
folds, calls a strategy adapter, stitches OOS signals/positions, and leaves the
final market simulation to existing QuantBT endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import time
import warnings
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from .core.preprocessor import validate_datetime
from .optimization.callbacks import SingleObjectiveEarlyStopping as _OptimizationEarlyStopping
from .optimization.space import stable_params_key, suggest_params as _optimization_suggest_params

try:  # optional acceleration; Python/NumPy baseline remains available
    from numba import njit
except Exception:  # pragma: no cover - optional dependency guard
    njit = None

_NUMBA_AVAILABLE = njit is not None

StrategyOutput = Union[pd.Series, pd.DataFrame, Dict[str, pd.Series]]


@dataclass(frozen=True)
class WalkForwardCompatibilityEntry:
    """One public walk-forward endpoint compatibility row."""

    target_mode: str
    expected_output: str
    final_engine: str
    status: str
    notes: str = ""


@dataclass(frozen=True)
class WalkForwardBenchmarkSnapshot:
    """Small deterministic kernel benchmark snapshot for audit/CI smoke tests."""

    n_obs: int
    n_samples: int
    seed: int
    numba_available: bool
    numba_requested: bool
    python_score_seconds: float
    accelerated_score_seconds: float
    python_bootstrap_seconds: float
    accelerated_bootstrap_seconds: float
    max_score_abs_diff: float
    max_bootstrap_abs_diff: float

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot."""
        return {
            "n_obs": self.n_obs,
            "n_samples": self.n_samples,
            "seed": self.seed,
            "numba_available": self.numba_available,
            "numba_requested": self.numba_requested,
            "python_score_seconds": self.python_score_seconds,
            "accelerated_score_seconds": self.accelerated_score_seconds,
            "python_bootstrap_seconds": self.python_bootstrap_seconds,
            "accelerated_bootstrap_seconds": self.accelerated_bootstrap_seconds,
            "max_score_abs_diff": self.max_score_abs_diff,
            "max_bootstrap_abs_diff": self.max_bootstrap_abs_diff,
        }


@dataclass(frozen=True)
class WalkForwardFold:
    """One time-safe train/OOS fold."""

    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_index: pd.DatetimeIndex
    test_index: pd.DatetimeIndex


@dataclass(frozen=True)
class PreparedWalkForwardContext:
    """Run-local, immutable WFO market/fold preparation contract.

    The context owns the one canonical timezone-aligned market snapshot used by
    a WFO run. Integer slicing replaces repeated boolean masks while strategy
    calls still receive isolated copies, so arbitrary user code cannot mutate
    another trial's market view. No context is shared across runs.
    """

    data: Any
    datetime_index: pd.DatetimeIndex
    folds: Tuple[WalkForwardFold, ...]
    data_signature: str
    config_signature: str
    signature: str
    cutoff_stops: Mapping[int, int]
    _stats: Dict[str, int] = field(
        default_factory=lambda: {
            "strategy_slice_requests": 0,
            "scoring_slice_requests": 0,
            "integer_slice_hits": 0,
        },
        repr=False,
        compare=False,
    )

    @classmethod
    def prepare(
        cls,
        *,
        data,
        datetime_index: pd.DatetimeIndex,
        folds: Sequence[WalkForwardFold],
        config: "WalkForwardConfig",
    ) -> "PreparedWalkForwardContext":
        idx = validate_datetime(datetime_index)
        fold_tuple = tuple(folds)
        cutoffs = {
            int(timestamp.value)
            for fold in fold_tuple
            for timestamp in (fold.train_end, fold.test_end)
        }
        if config.optimization_mode in {"mode_4_is_only_robust", "mode_5_full_robust"}:
            for fold in fold_tuple:
                for shard in _split_index_into_subperiods(fold.train_index, int(config.is_subperiods)):
                    if len(shard):
                        cutoffs.add(int(shard[-1].value))
        if (
            config.optimization_mode == "mode_1_decay"
            and config.optimization_schedule == "per_fold_causal"
        ):
            for outer_fold in fold_tuple:
                for inner_fold in _build_inner_folds(outer_fold, config):
                    for timestamp in (
                        inner_fold.train_end,
                        inner_fold.test_end,
                    ):
                        cutoffs.add(int(timestamp.value))
        cutoff_stops = {
            value: int(idx.searchsorted(pd.Timestamp(value, tz="UTC"), side="right"))
            for value in sorted(cutoffs)
        }
        data_signature = _complete_data_hash(data)
        config_signature = _config_hash(config)
        fold_payload = [
            (int(fold.fold_id), int(fold.train_start.value), int(fold.train_end.value), int(fold.test_start.value), int(fold.test_end.value))
            for fold in fold_tuple
        ]
        signature_payload = json.dumps(
            {
                "data": data_signature,
                "config": config_signature,
                "folds": fold_payload,
            },
            sort_keys=True,
        ).encode("utf-8")
        return cls(
            data=data,
            datetime_index=idx,
            folds=fold_tuple,
            data_signature=data_signature,
            config_signature=config_signature,
            signature=hashlib.sha256(signature_payload).hexdigest(),
            cutoff_stops=cutoff_stops,
        )

    def data_through(self, end: pd.Timestamp, *, strategy_copy: bool):
        """Return an integer-sliced causal view through ``end``."""
        key = int(pd.Timestamp(end).value)
        stop = self.cutoff_stops.get(key)
        if stop is None:
            stop = int(self.datetime_index.searchsorted(pd.Timestamp(end), side="right"))
        self._stats["integer_slice_hits"] += 1
        counter = "strategy_slice_requests" if strategy_copy else "scoring_slice_requests"
        self._stats[counter] += 1
        return _slice_strategy_data_by_stop(
            self.data,
            stop=stop,
            end=pd.Timestamp(end),
            strategy_copy=strategy_copy,
        )

    def validate_source(self, data) -> None:
        """Reject attempted reuse after any result-affecting source mutation."""
        if _complete_data_hash(data) != self.data_signature:
            raise ValueError("prepared walk-forward context source data signature changed")

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "run_local": True,
            "signature": self.signature,
            "data_signature": self.data_signature,
            "config_signature": self.config_signature,
            "bars": int(len(self.datetime_index)),
            "folds": int(len(self.folds)),
            "prepared_cutoffs": int(len(self.cutoff_stops)),
            **dict(self._stats),
        }


@dataclass(frozen=True)
class WalkForwardConfig:
    """
    Configuration for Phase 1 walk-forward splitting and stitching.

    Parameters
    ----------
    split_mode:
        String such as `walk_forward_2022`, an integer year, or a timestamp-like
        value marking the first OOS period.
    split_frequency:
        `single`, `yearly`, `semi_yearly`, `quarterly`, `monthly`, or
        `weekly`. `single` creates one train/test holdout fold.
    window_mode:
        `expanding` keeps the first train timestamp fixed. `rolling` uses
        `train_window` as the train lookback.
    train_window:
        Optional pandas offset string such as `365D` or `730D`, required for
        rolling mode.
    min_train_bars:
        Folds with fewer train bars are skipped.
    min_test_bars:
        Folds with fewer OOS bars are skipped.
    target_mode:
        Existing QuantBT route used for the final stitched backtest:
        `signal_notional`, `pct_equity`, `dca_ladder`, `portfolio`, `basket`,
        or `arbitrage`.
    fill_value:
        Value used outside OOS windows when constructing the stitched output.
    optimization_schedule:
        `global` preserves the existing one-study lifecycle. `per_fold_decay`
        runs the existing Mode 1 two-stage decay selector independently inside
        every outer fold. `per_fold_causal` performs strict IS-only Mode 4
        selection independently inside every outer fold.
    fold_boundary_position_policy:
        Position treatment when adjacent fold outputs are stitched. Phase 49A
        supports `carry` only: the final account engine receives one continuous
        target tape and trades only the actual target delta.
    """

    split_mode: Union[str, int, pd.Timestamp] = "walk_forward_2022"
    split_frequency: str = "quarterly"
    window_mode: str = "expanding"
    train_window: Optional[str] = None
    min_train_bars: int = 1
    min_test_bars: int = 1
    target_mode: str = "signal_notional"
    fill_value: float = 0.0
    optimization_mode: str = "none"
    optimization_schedule: str = "global"
    fold_boundary_position_policy: str = "carry"
    inner_split_frequency: Optional[str] = None
    inner_window_mode: Optional[str] = None
    inner_train_window: Optional[str] = None
    inner_min_folds: int = 2
    optuna_trials: int = 0
    optuna_early_stopping: Optional[int] = None
    random_seed: int = 42
    decay_lambda: float = 0.5
    decay_gamma: float = 0.5
    top_is_fraction: float = 0.10
    top_is_k: Optional[int] = None
    candidate_selection_metric: str = "robust_decay"
    candidate_decay_lambda: Optional[float] = None
    candidate_decay_gamma: Optional[float] = None
    sbb_samples: int = 256
    sbb_block_length: int = 20
    sbb_decay_lambda: float = 0.5
    sbb_std_penalty: float = 0.1
    sbb_simulation: str = "stationary"
    regime_count: int = 3
    regime_lookback: int = 20
    regime_weights: Optional[Dict[Union[int, str], float]] = None
    stress_vol_multiplier: float = 1.0
    garch_p: int = 1
    garch_q: int = 1
    garch_dist: str = "t"
    garch_vol_multiplier: float = 1.0
    flat_top_fraction: float = 0.1
    flat_eps: float = 0.15
    flat_min_samples: int = 3
    flat_selector: str = "medoid"
    plateau_quantile: float = 0.25
    plateau_median_weight: float = 0.25
    plateau_std_penalty: float = 0.50
    plateau_size_bonus: float = 0.01
    is_subperiods: int = 6
    q25_weight: float = 0.30
    dispersion_penalty: float = 0.50
    temporal_weight: float = 0.65
    plateau_weight: float = 0.35
    use_bootstrap_penalty: bool = False
    use_complexity_penalty: bool = False
    scoring_backend: str = "proxy"
    scoring_trading_days: int = 365
    min_trades_per_year: Optional[float] = None
    trade_penalty_factor: Optional[float] = None
    use_numba: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        freq = self.split_frequency.lower().strip()
        if freq not in {"single", "yearly", "semi_yearly", "quarterly", "monthly", "weekly"}:
            raise ValueError("split_frequency must be single, yearly, semi_yearly, quarterly, monthly, or weekly")
        object.__setattr__(self, "split_frequency", freq)

        mode = self.window_mode.lower().strip()
        if mode not in {"expanding", "rolling"}:
            raise ValueError("window_mode must be expanding or rolling")
        if mode == "rolling" and self.train_window is None:
            raise ValueError("rolling window_mode requires train_window")
        object.__setattr__(self, "window_mode", mode)

        if self.min_train_bars <= 0 or self.min_test_bars <= 0:
            raise ValueError("min_train_bars and min_test_bars must be > 0")
        opt_mode = self.optimization_mode.lower().strip()
        if opt_mode not in {
            "none",
            "mode_1_decay",
            "mode_2_sbb",
            "mode_3_flat_minima",
            "mode_4_is_only_robust",
            "mode_5_full_robust",
        }:
            raise NotImplementedError(
                "optimization_mode must be one of: none, mode_1_decay, mode_2_sbb, mode_3_flat_minima, "
                "mode_4_is_only_robust, mode_5_full_robust"
            )
        object.__setattr__(self, "optimization_mode", opt_mode)
        schedule = self.optimization_schedule.lower().strip()
        if schedule not in {"global", "per_fold_decay", "per_fold_causal"}:
            raise ValueError(
                "optimization_schedule must be global, per_fold_decay, or per_fold_causal"
            )
        if schedule == "per_fold_decay":
            if opt_mode != "mode_1_decay":
                raise NotImplementedError(
                    "optimization_schedule='per_fold_decay' currently requires "
                    "optimization_mode='mode_1_decay'"
                )
            if self.candidate_selection_metric.lower().strip() != "robust_decay":
                raise ValueError(
                    "per_fold_decay requires candidate_selection_metric='robust_decay' "
                    "to preserve the certified Mode 1 objective"
                )
        elif schedule == "per_fold_causal" and opt_mode not in {"mode_1_decay", "mode_4_is_only_robust"}:
            raise NotImplementedError(
                "optimization_schedule='per_fold_causal' currently requires "
                "optimization_mode='mode_1_decay' with nested inner validation or "
                "optimization_mode='mode_4_is_only_robust'"
            )
        if schedule == "per_fold_causal" and opt_mode == "mode_1_decay":
            if self.candidate_selection_metric.lower().strip() != "robust_decay":
                raise ValueError(
                    "causal Mode 1 requires candidate_selection_metric='robust_decay' "
                    "to preserve the certified inner-fold decay objective"
                )
            if self.inner_split_frequency is None or self.inner_window_mode is None or self.inner_train_window is None:
                raise ValueError(
                    "causal Mode 1 requires inner_split_frequency, inner_window_mode, "
                    "and inner_train_window so all decay selection stays inside outer IS"
                )
            inner_frequency = str(self.inner_split_frequency).lower().strip()
            if inner_frequency not in {"single", "yearly", "semi_yearly", "quarterly", "monthly", "weekly"}:
                raise ValueError(
                    "inner_split_frequency must be single, yearly, semi_yearly, quarterly, monthly, or weekly"
                )
            inner_window_mode = str(self.inner_window_mode).lower().strip()
            if inner_window_mode not in {"expanding", "rolling"}:
                raise ValueError("inner_window_mode must be expanding or rolling")
            try:
                inner_window = pd.Timedelta(self.inner_train_window)
            except (TypeError, ValueError) as exc:
                raise ValueError("inner_train_window must be a positive pandas Timedelta string such as '180D'") from exc
            if inner_window <= pd.Timedelta(0):
                raise ValueError("inner_train_window must be positive")
            if int(self.inner_min_folds) <= 0:
                raise ValueError("inner_min_folds must be > 0")
            object.__setattr__(self, "inner_split_frequency", inner_frequency)
            object.__setattr__(self, "inner_window_mode", inner_window_mode)
            object.__setattr__(self, "inner_train_window", str(self.inner_train_window))
            object.__setattr__(self, "inner_min_folds", int(self.inner_min_folds))
        if schedule != "global" and self.optuna_trials <= 0:
            raise ValueError("per-fold optimization schedules require optuna_trials > 0")
        object.__setattr__(self, "optimization_schedule", schedule)

        boundary_policy = self.fold_boundary_position_policy.lower().strip()
        if boundary_policy != "carry":
            raise NotImplementedError(
                "fold_boundary_position_policy currently supports 'carry' only"
            )
        object.__setattr__(self, "fold_boundary_position_policy", boundary_policy)
        if self.optuna_trials < 0:
            raise ValueError("optuna_trials must be >= 0")
        if self.optuna_early_stopping is not None and self.optuna_early_stopping <= 0:
            raise ValueError("optuna_early_stopping must be > 0")
        if not 0.0 < self.top_is_fraction <= 1.0:
            raise ValueError("top_is_fraction must be in (0, 1]")
        if self.top_is_k is not None and self.top_is_k <= 0:
            raise ValueError("top_is_k must be > 0 when provided")
        metric = self.candidate_selection_metric.lower().strip()
        if opt_mode == "mode_4_is_only_robust" and metric == "robust_decay":
            metric = "is_only_robust"
        if opt_mode == "mode_5_full_robust" and metric == "robust_decay":
            metric = "full_robust"
        valid_metrics = {
            "robust_decay",
            "mean_oos_sharpe",
            "mean_is_sharpe",
            "is_plateau_robust",
            "is_only_robust",
            "full_robust",
            "full_plateau_robust",
            "full_temporal_robust",
            "full_best",
        }
        if metric not in valid_metrics:
            raise ValueError(
                "candidate_selection_metric must be robust_decay, mean_oos_sharpe, "
                "mean_is_sharpe, is_plateau_robust, is_only_robust, full_robust, "
                "full_plateau_robust, full_temporal_robust, or full_best"
            )
        object.__setattr__(self, "candidate_selection_metric", metric)
        if opt_mode == "mode_4_is_only_robust" and metric != "is_only_robust":
            raise ValueError("mode_4_is_only_robust requires candidate_selection_metric='is_only_robust'")
        if opt_mode == "mode_5_full_robust" and metric not in {
            "full_robust",
            "full_plateau_robust",
            "full_temporal_robust",
            "full_best",
        }:
            raise ValueError(
                "mode_5_full_robust requires candidate_selection_metric to be one of: "
                "full_robust, full_plateau_robust, full_temporal_robust, full_best"
            )
        candidate_decay_lambda = None if self.candidate_decay_lambda is None else float(self.candidate_decay_lambda)
        if candidate_decay_lambda is not None and candidate_decay_lambda < 0.0:
            raise ValueError("candidate_decay_lambda must be >= 0 when provided")
        object.__setattr__(self, "candidate_decay_lambda", candidate_decay_lambda)
        candidate_decay_gamma = None if self.candidate_decay_gamma is None else float(self.candidate_decay_gamma)
        if candidate_decay_gamma is not None and candidate_decay_gamma < 0.0:
            raise ValueError("candidate_decay_gamma must be >= 0 when provided")
        object.__setattr__(self, "candidate_decay_gamma", candidate_decay_gamma)
        if self.sbb_samples <= 0:
            raise ValueError("sbb_samples must be > 0")
        if self.sbb_block_length <= 0:
            raise ValueError("sbb_block_length must be > 0")
        sim = self.sbb_simulation.lower().strip()
        if sim not in {"stationary", "regime", "stress", "garch"}:
            raise ValueError("sbb_simulation must be stationary, regime, stress, or garch")
        object.__setattr__(self, "sbb_simulation", sim)
        if self.regime_count < 2:
            raise ValueError("regime_count must be >= 2")
        if self.regime_lookback <= 0:
            raise ValueError("regime_lookback must be > 0")
        weights = None
        if self.regime_weights is not None:
            weights = _normalize_regime_weights(self.regime_weights, int(self.regime_count))
        object.__setattr__(self, "regime_weights", weights)
        if self.stress_vol_multiplier <= 0.0:
            raise ValueError("stress_vol_multiplier must be > 0")
        if self.garch_p <= 0 or self.garch_q <= 0:
            raise ValueError("garch_p and garch_q must be > 0")
        garch_dist = self.garch_dist.lower().strip()
        if garch_dist not in {"normal", "gaussian", "t", "studentst"}:
            raise ValueError("garch_dist must be normal, gaussian, t, or studentst")
        object.__setattr__(self, "garch_dist", "normal" if garch_dist == "gaussian" else garch_dist)
        if self.garch_vol_multiplier <= 0.0:
            raise ValueError("garch_vol_multiplier must be > 0")
        if not 0.0 < self.flat_top_fraction <= 1.0:
            raise ValueError("flat_top_fraction must be in (0, 1]")
        if self.flat_eps <= 0.0:
            raise ValueError("flat_eps must be > 0")
        if self.flat_min_samples <= 0:
            raise ValueError("flat_min_samples must be > 0")
        selector = self.flat_selector.lower().strip()
        if selector not in {"medoid", "centroid"}:
            raise ValueError("flat_selector must be medoid or centroid")
        object.__setattr__(self, "flat_selector", selector)
        if not 0.0 <= self.plateau_quantile <= 1.0:
            raise ValueError("plateau_quantile must be in [0, 1]")
        if self.plateau_median_weight < 0.0:
            raise ValueError("plateau_median_weight must be >= 0")
        if self.plateau_std_penalty < 0.0:
            raise ValueError("plateau_std_penalty must be >= 0")
        if self.is_subperiods <= 0:
            raise ValueError("is_subperiods must be > 0")
        if self.q25_weight < 0.0:
            raise ValueError("q25_weight must be >= 0")
        if self.dispersion_penalty < 0.0:
            raise ValueError("dispersion_penalty must be >= 0")
        if self.temporal_weight < 0.0 or self.plateau_weight < 0.0:
            raise ValueError("temporal_weight and plateau_weight must be >= 0")
        scoring_backend = self.scoring_backend.lower().strip()
        if scoring_backend not in {"proxy", "endpoint"}:
            raise ValueError("scoring_backend must be proxy or endpoint")
        if opt_mode == "mode_2_sbb" and scoring_backend == "endpoint":
            raise ValueError("mode_2_sbb requires scoring_backend='proxy' because it simulates train return paths")
        object.__setattr__(self, "scoring_backend", scoring_backend)
        try:
            scoring_days = int(self.scoring_trading_days)
        except (TypeError, ValueError) as exc:
            raise ValueError("scoring_trading_days must be a positive integer") from exc
        if scoring_days <= 0:
            raise ValueError("scoring_trading_days must be > 0")
        object.__setattr__(self, "scoring_trading_days", scoring_days)
        min_trades = None if self.min_trades_per_year is None else float(self.min_trades_per_year)
        if min_trades is not None and min_trades < 0.0:
            raise ValueError("min_trades_per_year must be >= 0 when provided")
        object.__setattr__(self, "min_trades_per_year", min_trades)
        penalty_factor = None if self.trade_penalty_factor is None else float(self.trade_penalty_factor)
        if penalty_factor is not None and penalty_factor < 0.0:
            raise ValueError("trade_penalty_factor must be >= 0 when provided")
        object.__setattr__(self, "trade_penalty_factor", penalty_factor)


@dataclass
class WalkForwardResult:
    """Phase 1 walk-forward artifact returned before/after final backtest."""

    folds: List[WalkForwardFold]
    oos_output: Optional[StrategyOutput]
    fold_table: pd.DataFrame
    params: Dict[str, Any]
    backtest_result: Any = None
    trial_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    candidate_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    best_trial: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def oos_positions(self) -> Optional[StrategyOutput]:
        """Alias for `oos_output` used by portfolio-style callers."""
        return self.oos_output


@dataclass(frozen=True)
class WalkForwardTrialRecord:
    """Audit row for one parameter trial."""

    trial_id: int
    params: Dict[str, Any]
    objective: float
    mean_is_sharpe: float
    mean_oos_sharpe: float
    mean_decay: float
    std_decay: float
    fold_metrics: List[Dict[str, Any]]
    pruned: bool = False
    selection_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _PerFoldScheduleRun:
    """Internal Phase 49A artifact before chronological OOS stitching."""

    outputs: List[StrategyOutput]
    selected_records: List[WalkForwardTrialRecord]
    trial_records: List[WalkForwardTrialRecord]
    candidate_records: List[WalkForwardTrialRecord]
    params_by_fold: Dict[int, Dict[str, Any]]
    selection_rows: List[Dict[str, Any]]
    inner_fold_rows: List[Dict[str, Any]]


class EarlyStoppingCallback(_OptimizationEarlyStopping):
    """Stop Optuna if best value does not improve after N trials."""

    def __init__(self, early_stopping_rounds: int, direction: str = "maximize"):
        super().__init__(patience=int(early_stopping_rounds), direction=direction, min_delta=0.0)
        self.early_stopping_rounds = int(early_stopping_rounds)


class DuplicatePruner:
    """Optuna pruner that avoids running duplicate parameter sets."""

    def __init__(self):
        self.trial_params = set()

    def prune(self, study, trial) -> bool:
        params_key = stable_params_key(trial.params)
        if params_key in self.trial_params:
            return True
        self.trial_params.add(params_key)
        return False


def logging_callback(study, frozen_trial) -> None:
    """Record previous best value when Optuna improves."""
    previous_best_value = study.user_attrs.get("previous_best_value", None)
    if previous_best_value != study.best_value:
        study.set_user_attr("previous_best_value", study.best_value)


def walkforward_support_matrix(as_dataframe: bool = True):
    """
    Return the current walk-forward compatibility matrix.

    This is intentionally public so notebooks/services can validate a route
    before wiring a strategy into `QuantBTEndpoint.walk_forward(...)`.
    """
    entries = [
        WalkForwardCompatibilityEntry(
            target_mode="signal_notional",
            expected_output="pd.Series scalar signal",
            final_engine="native_vectorized or native_event",
            status="supported",
            notes="Recommended default for single-symbol systematic alpha.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="notional",
            expected_output="pd.Series scalar target",
            final_engine="native_vectorized or native_event",
            status="supported",
            notes="Explicit notional sizing route.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="unit",
            expected_output="pd.Series scalar target",
            final_engine="native_vectorized or native_event",
            status="supported",
            notes="Explicit unit sizing route.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="pct_equity",
            expected_output="pd.Series scalar weight",
            final_engine="legacy BacktestEngine",
            status="supported",
            notes="Legacy `%_equity` accounting route.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="dca_ladder",
            expected_output="pd.Series structural ladder level",
            final_engine="legacy BacktestEngine",
            status="supported",
            notes="Requires high/low data for intrabar ladder fills.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="portfolio",
            expected_output="pd.DataFrame or dict[str, pd.Series]",
            final_engine="PortfolioBacktestEngine",
            status="supported",
            notes="Multi-symbol portfolio positions stitched across OOS folds.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="basket",
            expected_output="pd.Series scalar basket signal",
            final_engine="native_event basket route",
            status="supported",
            notes="Requires BasketSpec on the endpoint.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="arbitrage",
            expected_output="pd.Series scalar package signal",
            final_engine="supported arbitrage package route",
            status="partial",
            notes="Current supported arbitrage specs only; future specialized engines reserved.",
        ),
        WalkForwardCompatibilityEntry(
            target_mode="nautilus_validation",
            expected_output="pd.Series scalar signal",
            final_engine="Nautilus adapter",
            status="reserved",
            notes="Reserved for future WFO parity validation, not routed by walk-forward today.",
        ),
    ]
    rows = [entry.__dict__ for entry in entries]
    if as_dataframe:
        return pd.DataFrame(rows)
    return rows


class WalkForwardEngine:
    """
    Time-safe walk-forward splitter and OOS stitcher.

    The engine can use fixed `params`, Optuna decay search, SBB robustness, or
    flat-minima selection. The final output is always stitched OOS only;
    endpoint simulation is still delegated to QuantBT's normal backtest routes.
    """

    def __init__(
        self,
        strategy: Any,
        config: Optional[WalkForwardConfig] = None,
        scorer: Optional[Callable[..., Dict[str, float]]] = None,
    ):
        if strategy is None:
            raise ValueError("WalkForwardEngine requires a strategy callable or strategy class/object")
        self.strategy = strategy
        self.config = config or WalkForwardConfig()
        self.scorer = scorer
        if self.config.scoring_backend == "endpoint" and self.scorer is None:
            raise ValueError("scoring_backend='endpoint' requires a scorer callback")

    def run(
        self,
        data,
        params: Optional[Dict[str, Any]] = None,
        param_ranges: Optional[Dict[str, Any]] = None,
        datetime_index: Optional[Union[pd.DatetimeIndex, pd.Series]] = None,
    ) -> WalkForwardResult:
        """Build folds, call the strategy per fold, and stitch OOS output."""
        profile_enabled = bool(self.config.metadata.get("profile_walkforward", False))
        self._performance_profile = {"enabled": profile_enabled, "strategy_calls": 0, "score_calls": 0}
        prepare_started = time.perf_counter()
        idx = _infer_datetime_index(data, datetime_index)
        data_for_strategy = _align_data_to_datetime_index(data, idx)
        folds = self.build_folds(idx)
        use_prepared_context = bool(self.config.metadata.get("use_prepared_wfo_context", True))
        prepared_context = (
            PreparedWalkForwardContext.prepare(
                data=data_for_strategy,
                datetime_index=idx,
                folds=folds,
                config=self.config,
            )
            if use_prepared_context
            else None
        )
        if profile_enabled:
            self._performance_profile["data_alignment_fold_prepare_seconds"] = time.perf_counter() - prepare_started
        self._prepared_context = prepared_context
        if prepared_context is not None and hasattr(self.scorer, "bind_walkforward_context"):
            self.scorer.bind_walkforward_context(prepared_context)
        try:
            return self._run_aligned(
                data_for_strategy=data_for_strategy,
                idx=idx,
                folds=folds,
                params=params,
                param_ranges=param_ranges,
                prepared_context=prepared_context,
            )
        finally:
            self._prepared_context = None

    def _run_aligned(
        self,
        *,
        data_for_strategy,
        idx: pd.DatetimeIndex,
        folds: Sequence[WalkForwardFold],
        params: Optional[Dict[str, Any]],
        param_ranges: Optional[Dict[str, Any]],
        prepared_context: Optional[PreparedWalkForwardContext],
    ) -> WalkForwardResult:
        schedule = self.config.optimization_schedule
        params_by_fold: Dict[int, Dict[str, Any]] = {}
        selection_rows: List[Dict[str, Any]] = []
        inner_fold_rows: List[Dict[str, Any]] = []

        if schedule == "global":
            optimization_requested = (
                params is None
                and self.config.optimization_mode in {
                    "mode_1_decay",
                    "mode_2_sbb",
                    "mode_3_flat_minima",
                    "mode_4_is_only_robust",
                    "mode_5_full_robust",
                }
                and self.config.optuna_trials > 0
            )
            trial_records: List[WalkForwardTrialRecord] = []
            candidate_records: List[WalkForwardTrialRecord] = []
            if params is not None:
                chosen_params = dict(params)
                selected_record = self.evaluate_params(
                    data=data_for_strategy,
                    folds=folds,
                    params=chosen_params,
                    trial_id=0,
                )
                trial_records.append(selected_record)
            elif optimization_requested:
                selected_record, trial_records, candidate_records = self.optimize_params(
                    data=data_for_strategy,
                    folds=folds,
                    param_ranges=param_ranges or {},
                )
                chosen_params = dict(selected_record.params)
            else:
                chosen_params = dict(_default_params_from_ranges(param_ranges or {}))
                selected_record = self.evaluate_params(
                    data=data_for_strategy,
                    folds=folds,
                    params=chosen_params,
                    trial_id=0,
                )
                trial_records.append(selected_record)

            outputs: List[StrategyOutput] = []
            for fold in folds:
                out = self._call_strategy(data=data_for_strategy, params=chosen_params, fold=fold)
                outputs.append(_slice_output_to_test(out, fold.test_index))
        else:
            if params is not None:
                raise ValueError(
                    "per-fold optimization schedules require param_ranges and do not "
                    "accept one fixed params dictionary"
                )
            scheduled = self._run_per_fold_schedule(
                data=data_for_strategy,
                folds=folds,
                param_ranges=param_ranges or {},
            )
            outputs = scheduled.outputs
            trial_records = scheduled.trial_records
            candidate_records = scheduled.candidate_records
            params_by_fold = scheduled.params_by_fold
            selection_rows = scheduled.selection_rows
            inner_fold_rows = scheduled.inner_fold_rows
            selected_record = scheduled.selected_records[-1]
            chosen_params = dict(selected_record.params)

        stitched = stitch_oos_outputs(
            outputs=outputs,
            folds=folds,
            full_index=idx,
            fill_value=self.config.fill_value,
        )
        fold_table = _fold_table(folds)
        boundary_table = _fold_boundary_table(
            stitched,
            folds=folds,
            full_index=idx,
            fill_value=self.config.fill_value,
        )
        if schedule == "per_fold_decay":
            validation_claim = "selection_adjusted_oos"
            causality_claim = "fold_local_decay_calibration"
            chronological_validation_claim = "selection_adjusted_outer_oos"
            oos_used_for_selection = True
            params_semantics = "last_completed_fold_selected_params"
        elif schedule == "per_fold_causal":
            strict_claim = (
                "strict_nested_fold_local_retraining"
                if self.config.optimization_mode == "mode_1_decay"
                else "strict_fold_local_retraining"
            )
            validation_claim = strict_claim
            causality_claim = strict_claim
            chronological_validation_claim = "strict_outer_oos_after_frozen_selection"
            oos_used_for_selection = False
            params_semantics = "last_completed_fold_selected_params"
        else:
            validation_claim = (
                "none_full_sample_calibration"
                if self.config.optimization_mode == "mode_5_full_robust"
                else "walk_forward_oos"
            )
            causality_claim = "retrospective_global_calibration"
            chronological_validation_claim = "not_causal_multi_fold_global_calibration"
            oos_used_for_selection = self.config.optimization_mode not in {
                "mode_2_sbb",
                "mode_4_is_only_robust",
                "mode_5_full_robust",
            } and self.config.candidate_selection_metric not in {
                "is_plateau_robust",
                "is_only_robust",
                "full_robust",
                "full_plateau_robust",
                "full_temporal_robust",
                "full_best",
            }
            params_semantics = "single_global_parameter_set"

        return WalkForwardResult(
            folds=folds,
            oos_output=stitched,
            fold_table=fold_table,
            params=chosen_params,
            trial_table=_trial_table(trial_records),
            candidate_table=_trial_table(candidate_records),
            best_trial=_trial_to_dict(selected_record),
            metadata={
                "engine": "walk_forward_phase49a" if schedule != "global" else "walk_forward_phase4",
                "split_mode": str(self.config.split_mode),
                "split_frequency": self.config.split_frequency,
                "window_mode": self.config.window_mode,
                "target_mode": self.config.target_mode,
                "optimization_mode": self.config.optimization_mode,
                "optimization_schedule": schedule,
                "fold_boundary_position_policy": self.config.fold_boundary_position_policy,
                "validation_claim": validation_claim,
                "causality_claim": causality_claim,
                "full_sample_used_for_selection": self.config.optimization_mode == "mode_5_full_robust",
                "oos_used_for_selection": oos_used_for_selection,
                "params_semantics": params_semantics,
                "params_by_fold": params_by_fold,
                "fold_selection_table": pd.DataFrame(selection_rows),
                "inner_fold_table": pd.DataFrame(inner_fold_rows),
                "fold_boundary_table": boundary_table,
                "account_execution": "single_stitched_run",
                "n_folds": len(folds),
                "n_studies": len(folds) if schedule != "global" else int(optimization_requested),
                "optuna_trials_scope": (
                    "per_fold" if schedule != "global" else ("global" if optimization_requested else "none")
                ),
                "optuna_trials_configured_per_study": int(self.config.optuna_trials),
                "n_optuna_trial_rows": _optuna_record_count(trial_records),
                "n_trials": len(trial_records),
                "n_candidates": len(candidate_records),
                "trial_ledger_mode": (
                    "compact" if self.config.metadata.get("compact_trial_ledger", True) else "full"
                ),
                "full_trial_metrics_retained": 1 if selected_record.fold_metrics else 0,
                "top_is_fraction": self.config.top_is_fraction,
                "top_is_k": self.config.top_is_k,
                "candidate_selection_metric": self.config.candidate_selection_metric,
                "chronological_validation_claim": chronological_validation_claim,
                "inner_validation": _inner_validation_metadata(self.config),
                "data_hash": _data_hash(data_for_strategy),
                "config_hash": _config_hash(self.config),
                "random_seed": self.config.random_seed,
                "scoring_trading_days": self.config.scoring_trading_days,
                "min_trades_per_year": self.config.min_trades_per_year,
                "trade_penalty_factor": self.config.trade_penalty_factor,
                "sbb_simulation": self.config.sbb_simulation,
                "sbb_samples": self.config.sbb_samples,
                "sbb_block_length": self.config.sbb_block_length,
                "regime_count": self.config.regime_count,
                "regime_lookback": self.config.regime_lookback,
                "regime_weights": self.config.regime_weights,
                "stress_vol_multiplier": self.config.stress_vol_multiplier,
                "garch_p": self.config.garch_p,
                "garch_q": self.config.garch_q,
                "garch_dist": self.config.garch_dist,
                "garch_vol_multiplier": self.config.garch_vol_multiplier,
                "numba_enabled": bool(self.config.use_numba and _NUMBA_AVAILABLE),
                "plateau_quantile": self.config.plateau_quantile,
                "plateau_median_weight": self.config.plateau_median_weight,
                "plateau_std_penalty": self.config.plateau_std_penalty,
                "plateau_size_bonus": self.config.plateau_size_bonus,
                "is_subperiods": self.config.is_subperiods,
                "q25_weight": self.config.q25_weight,
                "dispersion_penalty": self.config.dispersion_penalty,
                "temporal_weight": self.config.temporal_weight,
                "plateau_weight": self.config.plateau_weight,
                "use_bootstrap_penalty": self.config.use_bootstrap_penalty,
                "use_complexity_penalty": self.config.use_complexity_penalty,
                "scoring_backend": self.config.scoring_backend,
                "prepared_wfo_context": (
                    prepared_context.metadata
                    if prepared_context is not None
                    else {"enabled": False, "run_local": True}
                ),
                "performance_profile": dict(getattr(self, "_performance_profile", {})),
                **self.config.metadata,
            },
        )

    def _run_per_fold_schedule(
        self,
        data,
        folds: Sequence[WalkForwardFold],
        param_ranges: Dict[str, Any],
    ) -> _PerFoldScheduleRun:
        """Run independent chronological studies under the Phase 49A contract."""
        schedule = self.config.optimization_schedule
        outputs: List[StrategyOutput] = []
        selected_records: List[WalkForwardTrialRecord] = []
        trial_records: List[WalkForwardTrialRecord] = []
        candidate_records: List[WalkForwardTrialRecord] = []
        params_by_fold: Dict[int, Dict[str, Any]] = {}
        selection_rows: List[Dict[str, Any]] = []
        inner_fold_rows: List[Dict[str, Any]] = []

        for fold in folds:
            fold_seed = _derive_fold_seed(self.config.random_seed, fold.fold_id)
            is_nested_mode1 = (
                schedule == "per_fold_causal"
                and self.config.optimization_mode == "mode_1_decay"
            )
            inner_folds: List[WalkForwardFold] = []
            if is_nested_mode1:
                inner_folds = _build_inner_folds(fold, self.config)
                selected, fold_trials, fold_candidates = self.optimize_params(
                    data=data,
                    folds=inner_folds,
                    param_ranges=param_ranges,
                    random_seed=fold_seed,
                    evaluate_oos_candidates=True,
                )
                inner_fold_rows.extend(
                    _inner_fold_audit_rows(
                        outer_fold=fold,
                        inner_folds=inner_folds,
                    )
                )
            else:
                selected, fold_trials, fold_candidates = self.optimize_params(
                    data=data,
                    folds=[fold],
                    param_ranges=param_ranges,
                    random_seed=fold_seed,
                    evaluate_oos_candidates=schedule == "per_fold_decay",
                )

            oos_used = schedule == "per_fold_decay"
            selection_label = (
                "fold_local_decay_calibration"
                if oos_used
                else (
                    "strict_nested_fold_local_retraining"
                    if is_nested_mode1
                    else "strict_fold_local_retraining"
                )
            )
            common_metadata = {
                "optimization_schedule": schedule,
                "schedule_fold_id": int(fold.fold_id),
                "study_id": int(fold.fold_id),
                "fold_seed": int(fold_seed),
                "selection_data_start": fold.train_start,
                "selection_data_end": fold.train_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "inner_fold_count": int(len(inner_folds)),
                "inner_validation": _inner_validation_metadata(self.config),
            }
            tagged_trials = [
                _with_selection_metadata(
                    record,
                    {**record.selection_metadata, **common_metadata},
                )
                for record in fold_trials
            ]
            tagged_candidates = [
                _with_selection_metadata(
                    record,
                    {**record.selection_metadata, **common_metadata},
                )
                for record in fold_candidates
            ]

            selected = _with_selection_metadata(
                selected,
                {
                    **selected.selection_metadata,
                    **common_metadata,
                    "causality_claim": selection_label,
                    "outer_oos_used_for_selection": bool(oos_used),
                    "oos_used_for_selection": bool(oos_used),
                    "selection_adjustment_note": (
                        "same_fold_oos_used_for_candidate_decay_selection"
                        if oos_used
                        else (
                            "outer_oos_excluded_from_nested_inner_decay_selection"
                            if is_nested_mode1
                            else "outer_oos_excluded_from_parameter_selection"
                        )
                    ),
                },
            )
            params_by_fold[int(fold.fold_id)] = dict(selected.params)

            out = self._call_strategy(data=data, params=dict(selected.params), fold=fold)
            out = _slice_output_to_test(out, fold.test_index)
            outputs.append(out)

            if oos_used:
                outer_is = float(selected.mean_is_sharpe)
                outer_oos = float(selected.mean_oos_sharpe)
                outer_decay = float(selected.mean_decay)
            else:
                oos_metrics = self._score_strategy_output(
                    data,
                    out,
                    fold.test_index,
                    fold=fold,
                    params=dict(selected.params),
                    context="post-selection outer OOS realization",
                )
                required = _required_trades_for_index(
                    fold.test_index,
                    self.config.min_trades_per_year,
                )
                factor = 1.0 if self.config.trade_penalty_factor is None else float(self.config.trade_penalty_factor)
                penalty = trade_frequency_penalty(oos_metrics["trade_count"], required, factor)
                outer_is = float(selected.mean_is_sharpe)
                outer_oos = float(oos_metrics["sharpe"] - penalty)
                outer_decay = float(outer_is - outer_oos)
                selected = _with_selection_metadata(
                    selected,
                    {
                        **selected.selection_metadata,
                        "outer_is_metric": outer_is,
                        "outer_oos_metric": outer_oos,
                        "outer_realized_decay": outer_decay,
                        "outer_oos_trade_count": float(oos_metrics["trade_count"]),
                        "outer_oos_trade_penalty": float(penalty),
                    },
                )

            selected_records.append(selected)
            trial_records.extend(tagged_trials)
            candidate_records.extend(tagged_candidates)
            optuna_rows = sum(
                1
                for record in tagged_trials
                if record.pruned or record.selection_metadata.get("stage") == "is_search"
            )
            selection_rows.append(
                {
                    "fold_id": int(fold.fold_id),
                    "study_id": int(fold.fold_id),
                    "fold_seed": int(fold_seed),
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "selected_trial_id": int(selected.trial_id),
                    "selected_params": dict(selected.params),
                    "selected_is_objective": float(selected.mean_is_sharpe),
                    "candidate_is_metric": outer_is,
                    "candidate_oos_metric": outer_oos,
                    "candidate_decay": outer_decay,
                    "candidate_count": int(len(tagged_candidates)),
                    "study_trial_rows": int(optuna_rows),
                    "outer_oos_used_for_selection": bool(oos_used),
                    "causality_claim": selection_label,
                    "inner_fold_count": int(len(inner_folds)),
                    "inner_validation": _inner_validation_metadata(self.config),
                }
            )

        return _PerFoldScheduleRun(
            outputs=outputs,
            selected_records=selected_records,
            trial_records=trial_records,
            candidate_records=candidate_records,
            params_by_fold=params_by_fold,
            selection_rows=selection_rows,
            inner_fold_rows=inner_fold_rows,
        )

    def optimize_params(
        self,
        data,
        folds: Sequence[WalkForwardFold],
        param_ranges: Dict[str, Any],
        random_seed: Optional[int] = None,
        evaluate_oos_candidates: bool = True,
    ) -> tuple[WalkForwardTrialRecord, List[WalkForwardTrialRecord], List[WalkForwardTrialRecord]]:
        """Run anti-leakage two-stage optimization and return selected params plus ledgers."""
        if not param_ranges:
            raise ValueError(f"{self.config.optimization_mode} optimization requires param_ranges")
        validate_param_ranges(param_ranges, context=self.config.optimization_mode)
        try:
            import optuna
        except ImportError as exc:  # pragma: no cover - environment guard
            raise ImportError("WalkForwardEngine optimization requires optuna") from exc

        records: List[WalkForwardTrialRecord] = []
        seen_params = set()
        compact_ledger = bool(self.config.metadata.get("compact_trial_ledger", True))

        def objective(trial):
            params = _sample_params(trial, param_ranges)
            params_key = stable_params_key(params)
            if params_key in seen_params:
                record = WalkForwardTrialRecord(
                    trial_id=int(trial.number),
                    params=dict(params),
                    objective=-np.inf,
                    mean_is_sharpe=0.0,
                    mean_oos_sharpe=0.0,
                    mean_decay=0.0,
                    std_decay=0.0,
                    fold_metrics=[],
                    pruned=True,
                )
                records.append(record)
                raise optuna.TrialPruned("duplicate parameter set")
            seen_params.add(params_key)
            if self.config.optimization_mode == "mode_2_sbb":
                record = self.evaluate_params_sbb(data=data, folds=folds, params=params, trial_id=trial.number)
            else:
                record = self.evaluate_params_is(data=data, folds=folds, params=params, trial_id=trial.number)
            records.append(record)
            if not compact_ledger:
                trial.set_user_attr("fold_metrics", record.fold_metrics)
                trial.set_user_attr("params", record.params)
                trial.set_user_attr("mean_is_sharpe", record.mean_is_sharpe)
                trial.set_user_attr("mean_oos_sharpe", record.mean_oos_sharpe)
                trial.set_user_attr("mean_decay", record.mean_decay)
                trial.set_user_attr("std_decay", record.std_decay)
            return record.objective

        study_seed = int(self.config.random_seed if random_seed is None else random_seed)
        sampler = optuna.samplers.TPESampler(seed=study_seed)
        pruner = DuplicatePruner()
        study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)
        callbacks = [logging_callback]
        if self.config.optuna_early_stopping is not None:
            callbacks.append(EarlyStoppingCallback(self.config.optuna_early_stopping))
        study.optimize(
            objective,
            n_trials=int(self.config.optuna_trials),
            callbacks=callbacks,
            show_progress_bar=False,
        )
        del study
        candidates = _select_is_candidate_records(records, param_ranges, self.config)
        if self.config.optimization_mode == "mode_5_full_robust":
            if not candidates:
                raise ValueError("full-sample robust optimization produced no candidates")
            selected = _with_selection_metadata(
                candidates[0],
                {
                    **candidates[0].selection_metadata,
                    "stage": "full_sample_candidate_selection",
                    "candidate_selection_complete": True,
                    "oos_seen_by_optuna": False,
                    "oos_used_for_selection": False,
                    "full_sample_used_for_selection": True,
                    "validation_claim": "none_full_sample_calibration",
                    "intended_use": "production_calibration",
                },
            )
            records.extend(candidates)
            return selected, self._compact_trial_records(records), self._compact_trial_records(candidates)
        if not evaluate_oos_candidates:
            if self.config.optimization_mode != "mode_4_is_only_robust":
                raise NotImplementedError(
                    "OOS-free candidate selection is currently certified for Mode 4 only"
                )
            if not candidates:
                raise ValueError("IS-only robust optimization produced no candidates")
            selected = _with_selection_metadata(
                candidates[0],
                {
                    **candidates[0].selection_metadata,
                    "stage": "is_only_candidate_selection",
                    "candidate_selection_complete": True,
                    "oos_seen_by_optuna": False,
                    "oos_used_for_selection": False,
                },
            )
            return selected, self._compact_trial_records(records), self._compact_trial_records(candidates)
        candidate_records = []
        seen_candidate_params = set()
        for candidate_id, candidate in enumerate(candidates):
            params_key = tuple(sorted(candidate.params.items()))
            if params_key in seen_candidate_params:
                continue
            seen_candidate_params.add(params_key)
            evaluated = self.evaluate_params(
                data=data,
                folds=folds,
                params=dict(candidate.params),
                trial_id=int(candidate.trial_id),
            )
            evaluated = _with_selection_metadata(
                evaluated,
                {
                    **candidate.selection_metadata,
                    "stage": "oos_candidate_selection",
                    "candidate_id": int(candidate_id),
                    "source_trial_id": int(candidate.trial_id),
                    "source_is_objective": float(candidate.objective),
                    "oos_seen_by_optuna": False,
                },
            )
            candidate_records.append(evaluated)
        if not candidate_records:
            raise ValueError("anti-leakage optimization produced no OOS candidates")
        best = _select_oos_candidate_record(candidate_records, self.config)
        records.extend(candidate_records)
        return best, self._compact_trial_records(records), self._compact_trial_records(candidate_records)

    def _compact_trial_records(
        self,
        records: Sequence[WalkForwardTrialRecord],
    ) -> List[WalkForwardTrialRecord]:
        if not bool(self.config.metadata.get("compact_trial_ledger", True)):
            return list(records)
        return [_without_fold_metrics(record) for record in records]

    def evaluate_params_is(
        self,
        data,
        folds: Sequence[WalkForwardFold],
        params: Dict[str, Any],
        trial_id: int = 0,
    ) -> WalkForwardTrialRecord:
        """Score params on in-sample folds only for anti-leakage Optuna search."""
        fold_metrics = []
        is_scores = []

        for fold in folds:
            is_output = self._call_strategy_for_indices(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.train_index,
                fold=fold,
                context="anti-leakage in-sample search",
            )
            is_metrics = self._score_strategy_output(
                data,
                is_output,
                fold.train_index,
                fold=fold,
                params=params,
                context="anti-leakage in-sample search",
            )
            required_trades = _required_trades_for_index(fold.train_index, self.config.min_trades_per_year)
            factor = 1.0 if self.config.trade_penalty_factor is None else float(self.config.trade_penalty_factor)
            penalty = trade_frequency_penalty(is_metrics["trade_count"], required_trades, factor)
            is_sharpe = is_metrics["sharpe"] - penalty
            shard_stats = self._score_is_subperiods(
                data=data,
                is_output=is_output,
                train_index=fold.train_index,
                fold=fold,
                params=params,
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
        shard_values = _collect_subperiod_sharpes(fold_metrics)
        temporal_stats = _temporal_robustness_stats(
            shard_values,
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
                **temporal_stats,
            },
        )

    def _score_is_subperiods(
        self,
        data,
        is_output: StrategyOutput,
        train_index: pd.DatetimeIndex,
        fold: WalkForwardFold,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.config.optimization_mode not in {"mode_4_is_only_robust", "mode_5_full_robust"}:
            return {}
        shards = _split_index_into_subperiods(train_index, int(self.config.is_subperiods))
        scores = []
        raw_scores = []
        trade_counts = []
        factor = 1.0 if self.config.trade_penalty_factor is None else float(self.config.trade_penalty_factor)
        for shard_id, shard_index in enumerate(shards):
            if len(shard_index) < 2:
                continue
            shard_output = _slice_output_to_test(is_output, shard_index)
            metrics = self._score_strategy_output(
                data,
                shard_output,
                shard_index,
                fold=fold,
                params=params,
                context=f"is-only robustness subperiod {shard_id}",
            )
            required = _required_trades_for_index(shard_index, self.config.min_trades_per_year)
            penalty = trade_frequency_penalty(metrics["trade_count"], required, factor)
            raw = float(metrics["sharpe"])
            score = raw - penalty
            raw_scores.append(raw)
            scores.append(float(score))
            trade_counts.append(float(metrics["trade_count"]))
        stats = _temporal_robustness_stats(
            scores,
            q25_weight=float(self.config.q25_weight),
            dispersion_penalty=float(self.config.dispersion_penalty),
            fallback=0.0,
        )
        return {
            "is_subperiod_sharpes": [float(x) for x in scores],
            "is_subperiod_sharpes_raw": [float(x) for x in raw_scores],
            "is_subperiod_trade_counts": [float(x) for x in trade_counts],
            "is_subperiod_count": int(len(scores)),
            "is_subperiod_median": stats["temporal_median"],
            "is_subperiod_q25": stats["temporal_q25"],
            "is_subperiod_mad": stats["temporal_mad"],
            "is_temporal_score": stats["temporal_score"],
        }

    def evaluate_params(
        self,
        data,
        folds: Sequence[WalkForwardFold],
        params: Dict[str, Any],
        trial_id: int = 0,
    ) -> WalkForwardTrialRecord:
        """Score params with mode_1_decay return-proxy metrics."""
        fold_metrics = []
        is_scores = []
        oos_scores = []
        decay = []

        for fold in folds:
            is_output = self._call_strategy_for_indices(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.train_index,
                fold=fold,
                context="in-sample scoring",
            )
            oos_output = self._call_strategy_for_indices(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.test_index,
                fold=fold,
                context="out-of-sample scoring",
            )
            is_metrics = self._score_strategy_output(
                data,
                is_output,
                fold.train_index,
                fold=fold,
                params=params,
                context="in-sample scoring",
            )
            oos_metrics = self._score_strategy_output(
                data,
                oos_output,
                fold.test_index,
                fold=fold,
                params=params,
                context="out-of-sample scoring",
            )
            is_required_trades = _required_trades_for_index(fold.train_index, self.config.min_trades_per_year)
            oos_required_trades = _required_trades_for_index(fold.test_index, self.config.min_trades_per_year)
            factor = 1.0 if self.config.trade_penalty_factor is None else float(self.config.trade_penalty_factor)
            is_penalty = trade_frequency_penalty(is_metrics["trade_count"], is_required_trades, factor)
            oos_penalty = trade_frequency_penalty(oos_metrics["trade_count"], oos_required_trades, factor)
            is_sharpe = is_metrics["sharpe"] - is_penalty
            oos_sharpe = oos_metrics["sharpe"] - oos_penalty
            d = is_sharpe - oos_sharpe
            is_scores.append(is_sharpe)
            oos_scores.append(oos_sharpe)
            decay.append(d)
            fold_metrics.append(
                {
                    "fold_id": fold.fold_id,
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "is_sharpe": is_sharpe,
                    "oos_sharpe": oos_sharpe,
                    "is_sharpe_raw": is_metrics["sharpe"],
                    "oos_sharpe_raw": oos_metrics["sharpe"],
                    "decay": d,
                    "is_turnover": is_metrics["turnover"],
                    "oos_turnover": oos_metrics["turnover"],
                    "is_trade_count": is_metrics["trade_count"],
                    "oos_trade_count": oos_metrics["trade_count"],
                    "is_required_trades": is_required_trades,
                    "oos_required_trades": oos_required_trades,
                    "is_trade_penalty": is_penalty,
                    "oos_trade_penalty": oos_penalty,
                }
            )

        mean_oos = float(np.mean(oos_scores)) if oos_scores else 0.0
        mean_is = float(np.mean(is_scores)) if is_scores else 0.0
        mean_decay = float(np.mean(decay)) if decay else 0.0
        std_decay = float(np.std(decay, ddof=1)) if len(decay) > 1 else 0.0
        decay_lambda = self.config.decay_lambda if self.config.candidate_decay_lambda is None else self.config.candidate_decay_lambda
        decay_gamma = self.config.decay_gamma if self.config.candidate_decay_gamma is None else self.config.candidate_decay_gamma
        objective = (
            mean_oos
            - float(decay_lambda) * std_decay
            - float(decay_gamma) * max(0.0, mean_decay)
        )
        return WalkForwardTrialRecord(
            trial_id=int(trial_id),
            params=dict(params),
            objective=float(objective),
            mean_is_sharpe=mean_is,
            mean_oos_sharpe=mean_oos,
            mean_decay=mean_decay,
            std_decay=std_decay,
            fold_metrics=fold_metrics,
        )

    def evaluate_params_sbb(
        self,
        data,
        folds: Sequence[WalkForwardFold],
        params: Dict[str, Any],
        trial_id: int = 0,
    ) -> WalkForwardTrialRecord:
        """
        Score params with train-only synthetic OOS robustness.

        The strategy is evaluated on each train fold, then its train return
        proxy is simulated with the selected Mode 2 generator. The selected
        objective rewards high synthetic Sharpe and penalizes estimated decay
        from original IS Sharpe to synthetic Sharpe. OOS bars are not evaluated
        inside the Optuna objective.
        """
        fold_metrics = []
        is_scores = []
        synthetic_scores = []
        synthetic_stds = []
        decay = []

        for fold in folds:
            is_output = self._call_strategy_for_indices(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.train_index,
                fold=fold,
                context="sbb train scoring",
            )
            is_metrics = self._score_strategy_output(
                data,
                is_output,
                fold.train_index,
                fold=fold,
                params=params,
                context="sbb train scoring",
            )
            returns = strategy_return_series(
                data,
                is_output,
                fold.train_index,
            ).to_numpy(dtype=np.float64)
            seed = int(self.config.random_seed) + int(trial_id) * 100_003 + int(fold.fold_id) * 9_176
            boot = synthetic_walkforward_sharpes(
                returns=returns,
                n_samples=int(self.config.sbb_samples),
                block_length=int(self.config.sbb_block_length),
                seed=seed,
                trading_days=int(self.config.scoring_trading_days),
                use_numba=bool(self.config.use_numba),
                simulation=self.config.sbb_simulation,
                regime_count=int(self.config.regime_count),
                regime_lookback=int(self.config.regime_lookback),
                regime_weights=self.config.regime_weights,
                stress_vol_multiplier=float(self.config.stress_vol_multiplier),
                garch_p=int(self.config.garch_p),
                garch_q=int(self.config.garch_q),
                garch_dist=self.config.garch_dist,
                garch_vol_multiplier=float(self.config.garch_vol_multiplier),
            )
            synthetic_mean = float(np.mean(boot)) if len(boot) else 0.0
            synthetic_std = float(np.std(boot, ddof=1)) if len(boot) > 1 else 0.0
            required_trades = _required_trades_for_index(fold.train_index, self.config.min_trades_per_year)
            factor = 1.0 if self.config.trade_penalty_factor is None else float(self.config.trade_penalty_factor)
            penalty = trade_frequency_penalty(is_metrics["trade_count"], required_trades, factor)
            is_sharpe = is_metrics["sharpe"] - penalty
            synthetic_sharpe = synthetic_mean - penalty
            d = float(is_sharpe - synthetic_sharpe)
            fold_objective = (
                synthetic_sharpe
                - float(self.config.sbb_decay_lambda) * max(0.0, d)
                - float(self.config.sbb_std_penalty) * synthetic_std
            )
            is_scores.append(is_sharpe)
            synthetic_scores.append(synthetic_sharpe)
            synthetic_stds.append(synthetic_std)
            decay.append(d)
            fold_metrics.append(
                {
                    "fold_id": fold.fold_id,
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "is_sharpe": is_sharpe,
                    "synthetic_oos_sharpe": synthetic_sharpe,
                    "is_sharpe_raw": is_metrics["sharpe"],
                    "synthetic_oos_sharpe_raw": synthetic_mean,
                    "synthetic_oos_std": synthetic_std,
                    "decay": d,
                    "sbb_objective": float(fold_objective),
                    "sbb_samples": int(self.config.sbb_samples),
                    "sbb_block_length": int(self.config.sbb_block_length),
                    "sbb_simulation": self.config.sbb_simulation,
                    "regime_count": int(self.config.regime_count),
                    "regime_lookback": int(self.config.regime_lookback),
                    "regime_weights": self.config.regime_weights,
                    "stress_vol_multiplier": float(self.config.stress_vol_multiplier),
                    "garch_p": int(self.config.garch_p),
                    "garch_q": int(self.config.garch_q),
                    "garch_dist": self.config.garch_dist,
                    "garch_vol_multiplier": float(self.config.garch_vol_multiplier),
                    "is_turnover": is_metrics["turnover"],
                    "is_trade_count": is_metrics["trade_count"],
                    "is_required_trades": required_trades,
                    "is_trade_penalty": penalty,
                }
            )

        mean_is = float(np.mean(is_scores)) if is_scores else 0.0
        mean_synthetic = float(np.mean(synthetic_scores)) if synthetic_scores else 0.0
        mean_synthetic_std = float(np.mean(synthetic_stds)) if synthetic_stds else 0.0
        mean_decay = float(np.mean(decay)) if decay else 0.0
        std_decay = float(np.std(decay, ddof=1)) if len(decay) > 1 else 0.0
        objective = (
            mean_synthetic
            - float(self.config.sbb_decay_lambda) * max(0.0, mean_decay)
            - float(self.config.sbb_std_penalty) * mean_synthetic_std
        )
        return WalkForwardTrialRecord(
            trial_id=int(trial_id),
            params=dict(params),
            objective=float(objective),
            mean_is_sharpe=mean_is,
            mean_oos_sharpe=mean_synthetic,
            mean_decay=mean_decay,
            std_decay=std_decay,
            fold_metrics=fold_metrics,
            selection_metadata={
                "stage": "is_search",
                "objective_mode": "mode_2_sbb",
                "sbb_samples": int(self.config.sbb_samples),
                "sbb_block_length": int(self.config.sbb_block_length),
                "sbb_simulation": self.config.sbb_simulation,
                "regime_count": int(self.config.regime_count),
                "regime_lookback": int(self.config.regime_lookback),
                "regime_weights": self.config.regime_weights,
                "stress_vol_multiplier": float(self.config.stress_vol_multiplier),
                "garch_p": int(self.config.garch_p),
                "garch_q": int(self.config.garch_q),
                "garch_dist": self.config.garch_dist,
                "garch_vol_multiplier": float(self.config.garch_vol_multiplier),
                "oos_seen_by_optuna": False,
            },
        )

    def build_folds(self, idx: pd.DatetimeIndex) -> List[WalkForwardFold]:
        """Return chronological train/OOS folds without lookahead."""
        idx = validate_datetime(idx)
        if len(idx) == 0:
            raise ValueError("walk-forward datetime index is empty")

        if self.config.optimization_mode == "mode_5_full_robust":
            if len(idx) < self.config.min_train_bars:
                raise ValueError("full-sample robust calibration produced too few bars")
            return [
                WalkForwardFold(
                    fold_id=0,
                    train_start=idx[0],
                    train_end=idx[-1],
                    test_start=idx[0],
                    test_end=idx[-1],
                    train_index=idx,
                    test_index=idx,
                )
            ]

        first_oos = _first_oos_timestamp(self.config.split_mode)
        if first_oos <= idx[0]:
            raise ValueError("first OOS timestamp must be after the first data timestamp")
        if first_oos > idx[-1]:
            raise ValueError("first OOS timestamp is after the available data")

        if self.config.split_frequency == "single":
            train_start = idx[0] if self.config.window_mode == "expanding" else first_oos - pd.Timedelta(self.config.train_window)
            train_index = idx[(idx >= train_start) & (idx < first_oos)]
            test_index = idx[idx >= first_oos]
            if len(train_index) < self.config.min_train_bars:
                raise ValueError("train/test split produced too few train bars")
            if len(test_index) < self.config.min_test_bars:
                raise ValueError("train/test split produced too few test bars")
            return [
                WalkForwardFold(
                    fold_id=0,
                    train_start=train_index[0],
                    train_end=train_index[-1],
                    test_start=test_index[0],
                    test_end=test_index[-1],
                    train_index=train_index,
                    test_index=test_index,
                )
            ]

        step = _frequency_offset(self.config.split_frequency)
        folds: List[WalkForwardFold] = []
        test_start = first_oos
        fold_id = 0
        while test_start <= idx[-1]:
            test_stop = test_start + step
            test_mask = (idx >= test_start) & (idx < test_stop)
            test_index = idx[test_mask]
            if len(test_index) < self.config.min_test_bars:
                test_start = test_stop
                continue

            if self.config.window_mode == "expanding":
                train_start = idx[0]
            else:
                train_start = test_start - pd.Timedelta(self.config.train_window)
            train_mask = (idx >= train_start) & (idx < test_start)
            train_index = idx[train_mask]
            if len(train_index) < self.config.min_train_bars:
                test_start = test_stop
                continue

            folds.append(
                WalkForwardFold(
                    fold_id=fold_id,
                    train_start=train_index[0],
                    train_end=train_index[-1],
                    test_start=test_index[0],
                    test_end=test_index[-1],
                    train_index=train_index,
                    test_index=test_index,
                )
            )
            fold_id += 1
            test_start = test_stop

        if not folds:
            raise ValueError("walk-forward split produced no folds")
        return folds

    def _score_strategy_output(
        self,
        data,
        output: StrategyOutput,
        index: pd.DatetimeIndex,
        fold: WalkForwardFold,
        params: Dict[str, Any],
        context: str,
    ) -> Dict[str, float]:
        score_started = time.perf_counter()
        scoring_data = (
            data
            if self.config.optimization_schedule == "global"
            else self._prepared_data_through(data, index[-1], strategy_copy=False)
        )
        if self.config.scoring_backend == "endpoint":
            assert self.scorer is not None
            metrics = self.scorer(
                data=scoring_data,
                output=output,
                index=index,
                fold=fold,
                params=params,
                context=context,
                trading_days=int(self.config.scoring_trading_days),
            )
        else:
            metrics = score_strategy_output(
                scoring_data,
                output,
                index,
                trading_days=int(self.config.scoring_trading_days),
                use_numba=bool(self.config.use_numba),
            )
        self._profile_add("score_seconds", time.perf_counter() - score_started, count_key="score_calls")
        return metrics

    def _call_strategy(self, data, params: Dict[str, Any], fold: WalkForwardFold) -> StrategyOutput:
        return self._call_strategy_for_indices(
            data=data,
            params=params,
            train_index=fold.train_index,
            test_index=fold.test_index,
            fold=fold,
        )

    def _call_strategy_for_indices(
        self,
        data,
        params: Dict[str, Any],
        train_index: pd.DatetimeIndex,
        test_index: pd.DatetimeIndex,
        fold: WalkForwardFold,
        context: str = "out-of-sample generation",
    ) -> StrategyOutput:
        strategy_started = time.perf_counter()
        strategy = self.strategy() if isinstance(self.strategy, type) else self.strategy
        strategy_data = (
            data
            if self.config.optimization_schedule == "global"
            else self._prepared_data_through(data, test_index[-1], strategy_copy=True)
        )
        try:
            if hasattr(strategy, "build_signal"):
                output = strategy.build_signal(
                    data=strategy_data,
                    params=params,
                    train_index=train_index,
                    test_index=test_index,
                    fold=fold,
                )
            elif hasattr(strategy, "generate_signal"):
                output = strategy.generate_signal(
                    data=strategy_data,
                    params=params,
                    train_index=train_index,
                    test_index=test_index,
                    fold=fold,
                )
            elif callable(strategy):
                output = strategy(
                    data=strategy_data,
                    params=params,
                    train_index=train_index,
                    test_index=test_index,
                    fold=fold,
                )
            else:
                raise TypeError("strategy must be callable or expose build_signal/generate_signal")
        except Exception as exc:
            raise RuntimeError(
                "walk-forward strategy failed during "
                f"{context} for fold_id={fold.fold_id}, "
                f"train=[{fold.train_start}, {fold.train_end}], "
                f"test=[{test_index[0]}, {test_index[-1]}]"
            ) from exc
        validated = validate_walkforward_strategy_output(
            output,
            expected_index=test_index,
            context=f"{context} fold_id={fold.fold_id}",
        )
        self._profile_add("strategy_seconds", time.perf_counter() - strategy_started, count_key="strategy_calls")
        return validated

    def _prepared_data_through(self, data, end: pd.Timestamp, *, strategy_copy: bool):
        prepared = getattr(self, "_prepared_context", None)
        if prepared is not None and data is prepared.data:
            return prepared.data_through(end, strategy_copy=strategy_copy)
        return _slice_strategy_data_through(data, end)

    def _profile_add(self, key: str, elapsed: float, *, count_key: str) -> None:
        profile = getattr(self, "_performance_profile", None)
        if not profile or not profile.get("enabled"):
            return
        profile[key] = float(profile.get(key, 0.0)) + float(elapsed)
        profile[count_key] = int(profile.get(count_key, 0)) + 1


def validate_walkforward_strategy_output(
    output: StrategyOutput,
    expected_index: pd.DatetimeIndex,
    context: str = "walk-forward strategy output",
) -> StrategyOutput:
    """
    Validate strategy output before slicing/stitching.

    Walk-forward output must be timestamp-indexed. Accepting RangeIndex or
    array-like output would silently reindex to all zeros, which is dangerous in
    production research.
    """
    idx = validate_datetime(expected_index)
    if len(idx) == 0:
        raise ValueError(f"{context}: expected_index is empty")

    if isinstance(output, pd.Series):
        _validate_timestamped_index(output.index, context=context)
        _validate_index_coverage(output.index, idx, context=context)
        return output

    if isinstance(output, pd.DataFrame):
        if len(output.columns) == 0:
            raise ValueError(f"{context}: DataFrame output must have at least one column")
        _validate_timestamped_index(output.index, context=context)
        _validate_index_coverage(output.index, idx, context=context)
        return output

    if isinstance(output, dict):
        if not output:
            raise ValueError(f"{context}: dict output must contain at least one symbol")
        for symbol, series in output.items():
            if not isinstance(symbol, str) or not symbol:
                raise ValueError(f"{context}: dict output keys must be non-empty symbol strings")
            if not isinstance(series, pd.Series):
                raise TypeError(f"{context}: dict output for {symbol!r} must be a pandas Series")
            _validate_timestamped_index(series.index, context=f"{context} symbol={symbol}")
            _validate_index_coverage(series.index, idx, context=f"{context} symbol={symbol}")
        return output

    raise TypeError(
        f"{context}: strategy output must be pd.Series, pd.DataFrame, or dict[str, pd.Series]; "
        f"got {type(output).__name__}"
    )


def validate_param_ranges(param_ranges: Dict[str, Any], context: str = "walk-forward optimization") -> Dict[str, Any]:
    """Validate Optuna/default parameter ranges and return the original mapping."""
    if not isinstance(param_ranges, dict):
        raise TypeError(f"{context}: param_ranges must be a dict, got {type(param_ranges).__name__}")
    if not param_ranges:
        raise ValueError(f"{context}: param_ranges must not be empty")
    for name, spec in param_ranges.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"{context}: parameter names must be non-empty strings")
        if isinstance(spec, tuple) and len(spec) in (2, 3) and all(_is_number(x) for x in spec):
            low = float(spec[0])
            high = float(spec[1])
            if high < low:
                raise ValueError(f"{context}: param_ranges[{name!r}] high must be >= low")
            if len(spec) == 3 and float(spec[2]) <= 0.0:
                raise ValueError(f"{context}: param_ranges[{name!r}] step must be > 0")
        elif isinstance(spec, (list, tuple)):
            if not spec:
                raise ValueError(f"{context}: param_ranges[{name!r}] categorical choices must not be empty")
        elif spec is None:
            raise ValueError(f"{context}: param_ranges[{name!r}] fixed value must not be None")
    return param_ranges


def trade_frequency_penalty(
    actual_trades: float,
    required_trades: float,
    penalty_factor: Optional[float],
) -> float:
    """
    Smooth normalized linear penalty for under-trading.

    Returns zero when disabled, when required trades are non-positive, or when
    actual trades meet/exceed the required count.
    """
    if penalty_factor is None or penalty_factor <= 0.0 or required_trades <= 0.0:
        return 0.0
    actual = max(0.0, float(actual_trades))
    required = max(0.0, float(required_trades))
    return float(penalty_factor) * max(0.0, 1.0 - actual / required)


def _required_trades_for_index(index: pd.DatetimeIndex, min_trades_per_year: Optional[float]) -> float:
    if min_trades_per_year is None or min_trades_per_year <= 0.0 or len(index) == 0:
        return 0.0
    idx = validate_datetime(index)
    if len(idx) <= 1:
        duration_days = 1.0 / 365.0
    else:
        duration_days = max((idx[-1] - idx[0]).total_seconds() / 86_400.0, 1.0 / 365.0)
    return float(min_trades_per_year) * (duration_days / 365.0)


def _validate_timestamped_index(index, context: str) -> None:
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError(f"{context}: output must use a pandas DatetimeIndex, got {type(index).__name__}")
    if len(index) == 0:
        raise ValueError(f"{context}: output index is empty")


def _validate_index_coverage(index: pd.DatetimeIndex, expected_index: pd.DatetimeIndex, context: str) -> None:
    output_index = validate_datetime(index)
    missing = expected_index.difference(output_index)
    if len(missing) > 0:
        sample = ", ".join(str(ts) for ts in missing[:3])
        raise ValueError(
            f"{context}: output index must cover every expected fold timestamp; "
            f"missing {len(missing)} of {len(expected_index)} timestamps, first missing: {sample}"
        )


def score_strategy_output(
    data,
    output: StrategyOutput,
    index: pd.DatetimeIndex,
    trading_days: int = 365,
    use_numba: bool = True,
) -> Dict[str, float]:
    """
    Score strategy output with a transparent return proxy.

    This is an optimization-time metric, not the final accounting simulation.
    Final PnL/fees/slippage/margin still come from the endpoint backtest after
    OOS stitching.
    """
    idx = validate_datetime(index)
    if len(idx) < 2:
        return {"sharpe": 0.0, "turnover": 0.0, "mean_return": 0.0, "volatility": 0.0}
    strat_returns = strategy_return_series(data, output, idx)
    position_matrix = strategy_position_frame(output, idx)
    returns_arr = strat_returns.to_numpy(dtype=np.float64)
    pos_arr = position_matrix.to_numpy(dtype=np.float64)
    if bool(use_numba) and _NUMBA_AVAILABLE:
        mean, sd, sharpe, turnover, trade_count = _score_returns_positions_numba(returns_arr, pos_arr, float(trading_days))
    else:
        mean, sd, sharpe, turnover, trade_count = _score_returns_positions_python(returns_arr, pos_arr, float(trading_days))
    return {
        "sharpe": float(sharpe),
        "turnover": float(turnover),
        "trade_count": float(trade_count),
        "mean_return": float(mean),
        "volatility": float(sd),
    }


def strategy_position_frame(output: StrategyOutput, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Return strategy output as a float position DataFrame on `index`."""
    idx = validate_datetime(index)
    if isinstance(output, pd.DataFrame):
        return _normalize_frame_output(output).reindex(idx).fillna(0.0)
    if isinstance(output, dict):
        return pd.DataFrame(
            {symbol: _normalize_series_output(series).reindex(idx).fillna(0.0) for symbol, series in output.items()},
            index=idx,
        )
    return pd.DataFrame({"DEFAULT": _normalize_series_output(output).reindex(idx).fillna(0.0)}, index=idx)


def strategy_return_series(data, output: StrategyOutput, index: pd.DatetimeIndex) -> pd.Series:
    """Return the transparent position return proxy used by WFO scoring."""
    idx = validate_datetime(index)
    if len(idx) == 0:
        return pd.Series(dtype=float, index=idx)
    close_map = _close_map_from_data(data)
    if isinstance(output, pd.DataFrame):
        symbols = list(output.columns)
        pos = _normalize_frame_output(output, symbols).reindex(idx).fillna(0.0)
        returns = pd.DataFrame({s: close_map[s].reindex(idx).pct_change().fillna(0.0) for s in symbols})
        strat_returns = (pos * returns).mean(axis=1)
    elif isinstance(output, dict):
        symbols = list(output.keys())
        pos = pd.DataFrame({s: _normalize_series_output(output[s]).reindex(idx).fillna(0.0) for s in symbols})
        returns = pd.DataFrame({s: close_map[s].reindex(idx).pct_change().fillna(0.0) for s in symbols})
        strat_returns = (pos * returns).mean(axis=1)
    else:
        series = _normalize_series_output(output).reindex(idx).fillna(0.0)
        close = next(iter(close_map.values())).reindex(idx)
        strat_returns = series * close.pct_change().fillna(0.0)
    return strat_returns.fillna(0.0).astype(float)


def stationary_bootstrap_sharpes(
    returns: np.ndarray,
    n_samples: int,
    block_length: int,
    seed: int,
    trading_days: int = 365,
    use_numba: bool = True,
) -> np.ndarray:
    """
    Generate Sharpe values from stationary block bootstrap samples.

    Random index generation stays in NumPy for transparent seeding. The repeated
    sample scoring loop is numba-accelerated when numba is available.
    """
    clean = np.asarray(returns, dtype=np.float64)
    clean = clean[np.isfinite(clean)]
    if clean.size < 2:
        return np.zeros(int(n_samples), dtype=np.float64)
    indices = _stationary_bootstrap_indices(
        n_obs=int(clean.size),
        n_samples=int(n_samples),
        block_length=int(block_length),
        seed=int(seed),
    )
    if bool(use_numba) and _NUMBA_AVAILABLE:
        return _bootstrap_sharpes_numba(clean, indices, float(trading_days))
    return _bootstrap_sharpes_python(clean, indices, float(trading_days))


def synthetic_walkforward_sharpes(
    returns: np.ndarray,
    n_samples: int,
    block_length: int,
    seed: int,
    trading_days: int = 365,
    use_numba: bool = True,
    simulation: str = "stationary",
    regime_count: int = 3,
    regime_lookback: int = 20,
    regime_weights: Optional[Dict[Union[int, str], float]] = None,
    stress_vol_multiplier: float = 1.0,
    garch_p: int = 1,
    garch_q: int = 1,
    garch_dist: str = "t",
    garch_vol_multiplier: float = 1.0,
) -> np.ndarray:
    """
    Generate train-only synthetic Sharpe samples for Mode 2 WFO scoring.

    `stationary` preserves the legacy SBB behavior. `regime` bootstraps blocks
    from volatility regimes estimated on the IS return proxy. `stress` keeps the
    SBB dependence model but scales demeaned returns before sampling. `garch`
    fits a GARCH(p, q) model on IS returns and simulates volatility-clustered
    paths with a deterministic seed.
    """
    sim = str(simulation).lower().strip()
    clean = np.asarray(returns, dtype=np.float64)
    clean = clean[np.isfinite(clean)]
    if clean.size < 2:
        return np.zeros(int(n_samples), dtype=np.float64)
    if sim == "stationary":
        return stationary_bootstrap_sharpes(clean, n_samples, block_length, seed, trading_days, use_numba)
    if sim == "stress":
        stressed = _stress_returns(clean, float(stress_vol_multiplier))
        return stationary_bootstrap_sharpes(stressed, n_samples, block_length, seed, trading_days, use_numba)
    if sim == "regime":
        labels = volatility_regime_labels(clean, regime_count=int(regime_count), lookback=int(regime_lookback))
        weights = _normalize_regime_weights(regime_weights, int(regime_count)) if regime_weights is not None else None
        indices = _regime_bootstrap_indices(
            labels=labels,
            n_samples=int(n_samples),
            block_length=int(block_length),
            seed=int(seed),
            regime_weights=weights,
            regime_count=int(regime_count),
        )
        if bool(use_numba) and _NUMBA_AVAILABLE:
            return _bootstrap_sharpes_numba(clean, indices, float(trading_days))
        return _bootstrap_sharpes_python(clean, indices, float(trading_days))
    if sim == "garch":
        paths = _garch_simulated_paths(
            clean,
            n_samples=int(n_samples),
            seed=int(seed),
            p=int(garch_p),
            q=int(garch_q),
            dist=str(garch_dist),
            vol_multiplier=float(garch_vol_multiplier),
        )
        if bool(use_numba) and _NUMBA_AVAILABLE:
            return _path_sharpes_numba(paths, float(trading_days))
        return _path_sharpes_python(paths, float(trading_days))
    raise ValueError("simulation must be stationary, regime, stress, or garch")


def volatility_regime_labels(returns: np.ndarray, regime_count: int = 3, lookback: int = 20) -> np.ndarray:
    """
    Assign trailing-volatility regime labels from 0 (low vol) to N-1 (high vol).

    The function uses only the in-sample return proxy passed by the caller. It
    does not inspect future OOS bars, so it is safe inside the WFO objective.
    """
    clean = np.asarray(returns, dtype=np.float64)
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return np.zeros(0, dtype=np.int64)
    n_regimes = max(2, int(regime_count))
    window = max(1, int(lookback))
    trailing_vol = np.empty(clean.size, dtype=np.float64)
    abs_ret = np.abs(clean)
    cumsum = np.concatenate(([0.0], np.cumsum(abs_ret)))
    for i in range(clean.size):
        start = max(0, i + 1 - window)
        trailing_vol[i] = (cumsum[i + 1] - cumsum[start]) / float(i + 1 - start)
    quantiles = np.linspace(0.0, 1.0, n_regimes + 1)[1:-1]
    cuts = np.quantile(trailing_vol, quantiles) if quantiles.size else np.array([], dtype=np.float64)
    labels = np.searchsorted(cuts, trailing_vol, side="right").astype(np.int64)
    return np.minimum(labels, n_regimes - 1)


def benchmark_walkforward_kernels(
    n_obs: int = 2_000,
    n_samples: int = 128,
    seed: int = 42,
    use_numba: bool = True,
) -> WalkForwardBenchmarkSnapshot:
    """
    Run a deterministic lightweight benchmark for WFO numeric kernels.

    The snapshot is intended for smoke/performance-regression tracking. Unit
    tests should assert finite timings and numerical equivalence, not hard wall
    clock thresholds.
    """
    if n_obs < 2:
        raise ValueError("n_obs must be >= 2")
    if n_samples < 1:
        raise ValueError("n_samples must be >= 1")
    rng = np.random.default_rng(int(seed))
    returns = rng.normal(loc=0.0002, scale=0.01, size=int(n_obs)).astype(np.float64)
    positions = rng.choice(np.array([-1.0, 0.0, 1.0], dtype=np.float64), size=(int(n_obs), 3))
    indices = _stationary_bootstrap_indices(
        n_obs=int(n_obs),
        n_samples=int(n_samples),
        block_length=max(2, int(np.sqrt(n_obs))),
        seed=int(seed),
    )

    start = time.perf_counter()
    py_score = _score_returns_positions_python(returns, positions, 365.0)
    python_score_seconds = time.perf_counter() - start

    start = time.perf_counter()
    accelerated_score = (
        _score_returns_positions_numba(returns, positions, 365.0)
        if bool(use_numba) and _NUMBA_AVAILABLE
        else _score_returns_positions_python(returns, positions, 365.0)
    )
    accelerated_score_seconds = time.perf_counter() - start

    start = time.perf_counter()
    py_boot = _bootstrap_sharpes_python(returns, indices, 365.0)
    python_bootstrap_seconds = time.perf_counter() - start

    start = time.perf_counter()
    accelerated_boot = (
        _bootstrap_sharpes_numba(returns, indices, 365.0)
        if bool(use_numba) and _NUMBA_AVAILABLE
        else _bootstrap_sharpes_python(returns, indices, 365.0)
    )
    accelerated_bootstrap_seconds = time.perf_counter() - start

    return WalkForwardBenchmarkSnapshot(
        n_obs=int(n_obs),
        n_samples=int(n_samples),
        seed=int(seed),
        numba_available=bool(_NUMBA_AVAILABLE),
        numba_requested=bool(use_numba),
        python_score_seconds=float(python_score_seconds),
        accelerated_score_seconds=float(accelerated_score_seconds),
        python_bootstrap_seconds=float(python_bootstrap_seconds),
        accelerated_bootstrap_seconds=float(accelerated_bootstrap_seconds),
        max_score_abs_diff=float(np.max(np.abs(np.asarray(py_score) - np.asarray(accelerated_score)))),
        max_bootstrap_abs_diff=float(np.max(np.abs(py_boot - accelerated_boot))),
    )


def _stationary_bootstrap_indices(n_obs: int, n_samples: int, block_length: int, seed: int) -> np.ndarray:
    if n_obs <= 0:
        raise ValueError("n_obs must be > 0")
    rng = np.random.default_rng(int(seed))
    p = 1.0 / max(1.0, float(block_length))
    indices = np.empty((int(n_samples), int(n_obs)), dtype=np.int64)
    for sample in range(int(n_samples)):
        current = int(rng.integers(0, n_obs))
        indices[sample, 0] = current
        for i in range(1, n_obs):
            if rng.random() < p:
                current = int(rng.integers(0, n_obs))
            else:
                current = (current + 1) % n_obs
            indices[sample, i] = current
    return indices


def _regime_bootstrap_indices(
    labels: np.ndarray,
    n_samples: int,
    block_length: int,
    seed: int,
    regime_weights: Optional[Dict[Union[int, str], float]] = None,
    regime_count: Optional[int] = None,
) -> np.ndarray:
    labels = np.asarray(labels, dtype=np.int64)
    if labels.size <= 0:
        raise ValueError("labels must not be empty")
    n_obs = int(labels.size)
    n_regimes = max(int(np.max(labels)) + 1, 2 if regime_count is None else int(regime_count))
    rng = np.random.default_rng(int(seed))
    p = 1.0 / max(1.0, float(block_length))
    if regime_weights is None:
        counts = np.bincount(labels, minlength=n_regimes).astype(np.float64)
        probs = counts / counts.sum()
    else:
        probs = np.zeros(n_regimes, dtype=np.float64)
        for key, value in regime_weights.items():
            idx = _regime_key_to_index(key, n_regimes)
            probs[idx] = float(value)
        total = float(probs.sum())
        if total <= 0.0:
            raise ValueError("regime_weights must sum to a positive value")
        probs = probs / total

    starts_by_regime = [np.flatnonzero(labels == regime) for regime in range(n_regimes)]
    all_starts = np.arange(n_obs, dtype=np.int64)
    indices = np.empty((int(n_samples), n_obs), dtype=np.int64)
    for sample in range(int(n_samples)):
        current_regime = int(rng.choice(n_regimes, p=probs))
        choices = starts_by_regime[current_regime]
        if choices.size == 0:
            choices = all_starts
        current = int(rng.choice(choices))
        indices[sample, 0] = current
        for i in range(1, n_obs):
            next_current = (current + 1) % n_obs
            if rng.random() < p or labels[next_current] != current_regime:
                current_regime = int(rng.choice(n_regimes, p=probs))
                choices = starts_by_regime[current_regime]
                if choices.size == 0:
                    choices = all_starts
                current = int(rng.choice(choices))
            else:
                current = next_current
            indices[sample, i] = current
    return indices


def _stress_returns(returns: np.ndarray, vol_multiplier: float) -> np.ndarray:
    clean = np.asarray(returns, dtype=np.float64)
    mean = float(np.mean(clean)) if clean.size else 0.0
    return mean + (clean - mean) * float(vol_multiplier)


def _normalize_regime_weights(
    weights: Optional[Dict[Union[int, str], float]],
    regime_count: int,
) -> Optional[Dict[int, float]]:
    if weights is None:
        return None
    n_regimes = max(2, int(regime_count))
    out: Dict[int, float] = {}
    for key, value in weights.items():
        idx = _regime_key_to_index(key, n_regimes)
        val = float(value)
        if val < 0.0:
            raise ValueError("regime_weights values must be >= 0")
        out[idx] = out.get(idx, 0.0) + val
    total = sum(out.values())
    if total <= 0.0:
        raise ValueError("regime_weights must sum to a positive value")
    return {key: value / total for key, value in out.items()}


def _regime_key_to_index(key: Union[int, str], regime_count: int) -> int:
    n_regimes = max(2, int(regime_count))
    if isinstance(key, (int, np.integer)):
        idx = int(key)
    else:
        raw = str(key).lower().strip()
        aliases = {
            "low": 0,
            "low_vol": 0,
            "calm": 0,
            "mid": n_regimes // 2,
            "medium": n_regimes // 2,
            "normal": n_regimes // 2,
            "high": n_regimes - 1,
            "high_vol": n_regimes - 1,
            "crash": n_regimes - 1,
            "stress": n_regimes - 1,
        }
        idx = aliases[raw] if raw in aliases else int(raw)
    if idx < 0 or idx >= n_regimes:
        raise ValueError(f"regime key {key!r} is outside [0, {n_regimes - 1}]")
    return idx


def _garch_simulated_paths(
    returns: np.ndarray,
    n_samples: int,
    seed: int,
    p: int,
    q: int,
    dist: str,
    vol_multiplier: float,
) -> np.ndarray:
    clean = np.asarray(returns, dtype=np.float64)
    clean = clean[np.isfinite(clean)]
    min_obs = max(30, (int(p) + int(q)) * 12)
    if clean.size < min_obs:
        raise ValueError(f"garch simulation requires at least {min_obs} finite IS returns")
    try:
        from arch import arch_model
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise ImportError("sbb_simulation='garch' requires the optional arch package") from exc

    scaled = clean * 100.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = arch_model(
            scaled,
            mean="Constant",
            vol="GARCH",
            p=int(p),
            q=int(q),
            dist=str(dist),
            rescale=False,
        )
        result = model.fit(disp="off", show_warning=False)

    params = result.params
    mu = float(params.get("mu", 0.0))
    omega = max(float(params.get("omega", np.var(scaled) * 0.01)), 1e-12)
    alphas = np.array([max(float(params.get(f"alpha[{i}]", 0.0)), 0.0) for i in range(1, int(p) + 1)])
    betas = np.array([max(float(params.get(f"beta[{i}]", 0.0)), 0.0) for i in range(1, int(q) + 1)])
    total_persistence = float(alphas.sum() + betas.sum())
    unconditional_var = float(np.var(scaled, ddof=1))
    if total_persistence < 0.999:
        unconditional_var = max(omega / max(1e-12, 1.0 - total_persistence), 1e-12)
    rng = np.random.default_rng(int(seed))
    paths_pct = np.empty((int(n_samples), clean.size), dtype=np.float64)
    max_lag = max(int(p), int(q), 1)
    nu = max(float(params.get("nu", 8.0)), 2.1)
    for sample_id in range(int(n_samples)):
        eps = np.zeros(clean.size + max_lag, dtype=np.float64)
        sigma2 = np.full(clean.size + max_lag, unconditional_var, dtype=np.float64)
        for t in range(max_lag, clean.size + max_lag):
            var_t = omega
            for i, alpha in enumerate(alphas, start=1):
                var_t += float(alpha) * eps[t - i] * eps[t - i]
            for j, beta in enumerate(betas, start=1):
                var_t += float(beta) * sigma2[t - j]
            sigma2[t] = max(var_t, 1e-12)
            if str(dist).lower() in {"t", "studentst"}:
                shock = float(rng.standard_t(nu)) * float(np.sqrt((nu - 2.0) / nu))
            else:
                shock = float(rng.normal())
            eps[t] = float(np.sqrt(sigma2[t])) * shock
            paths_pct[sample_id, t - max_lag] = mu + eps[t]
    paths = paths_pct / 100.0
    return _stress_paths(paths, float(vol_multiplier))


def _stress_paths(paths: np.ndarray, vol_multiplier: float) -> np.ndarray:
    arr = np.asarray(paths, dtype=np.float64)
    means = np.mean(arr, axis=1, keepdims=True)
    return means + (arr - means) * float(vol_multiplier)


def _score_returns_positions_python(
    returns: np.ndarray,
    positions: np.ndarray,
    trading_days: float,
) -> Tuple[float, float, float, float, float]:
    returns = np.asarray(returns, dtype=np.float64)
    positions = np.asarray(positions, dtype=np.float64)
    if returns.size == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    mean = float(np.mean(returns))
    sd = float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0
    sharpe = (mean / sd) * float(np.sqrt(trading_days)) if sd > 0.0 else 0.0
    turnover = 0.0
    trade_count = 0.0
    if positions.ndim == 1:
        positions = positions.reshape((-1, 1))
    if positions.shape[0] > 0:
        trade_count += float(np.count_nonzero(np.abs(positions[0, :]) > 0.0))
    if positions.shape[0] > 1:
        diffs = np.diff(positions, axis=0)
        turnover = float(np.abs(diffs).sum())
        trade_count = float(np.count_nonzero(np.abs(diffs) > 0.0))
        trade_count += float(np.count_nonzero(np.abs(positions[0, :]) > 0.0))
    return mean, sd, sharpe, turnover, trade_count


def _bootstrap_sharpes_python(returns: np.ndarray, indices: np.ndarray, trading_days: float) -> np.ndarray:
    out = np.empty(indices.shape[0], dtype=np.float64)
    for i in range(indices.shape[0]):
        sample = returns[indices[i]]
        mean = float(np.mean(sample))
        sd = float(np.std(sample, ddof=1)) if sample.size > 1 else 0.0
        out[i] = (mean / sd) * float(np.sqrt(trading_days)) if sd > 0.0 else 0.0
    return out


def _path_sharpes_python(paths: np.ndarray, trading_days: float) -> np.ndarray:
    arr = np.asarray(paths, dtype=np.float64)
    out = np.empty(arr.shape[0], dtype=np.float64)
    for i in range(arr.shape[0]):
        sample = arr[i]
        mean = float(np.mean(sample))
        sd = float(np.std(sample, ddof=1)) if sample.size > 1 else 0.0
        out[i] = (mean / sd) * float(np.sqrt(trading_days)) if sd > 0.0 else 0.0
    return out


if _NUMBA_AVAILABLE:

    @njit(cache=True)
    def _score_returns_positions_numba(returns, positions, trading_days):  # pragma: no cover - compared via tests
        n = returns.shape[0]
        if n == 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        total = 0.0
        for i in range(n):
            total += returns[i]
        mean = total / n
        sd = 0.0
        if n > 1:
            var = 0.0
            for i in range(n):
                diff = returns[i] - mean
                var += diff * diff
            sd = (var / (n - 1)) ** 0.5
        sharpe = 0.0
        if sd > 0.0:
            sharpe = (mean / sd) * (trading_days ** 0.5)
        turnover = 0.0
        trade_count = 0.0
        if positions.shape[0] > 0:
            for j in range(positions.shape[1]):
                if abs(positions[0, j]) > 0.0:
                    trade_count += 1.0
        if positions.shape[0] > 1:
            for i in range(1, positions.shape[0]):
                for j in range(positions.shape[1]):
                    diff = positions[i, j] - positions[i - 1, j]
                    turnover += abs(diff)
                    if abs(diff) > 0.0:
                        trade_count += 1.0
        return mean, sd, sharpe, turnover, trade_count

    @njit(cache=True)
    def _bootstrap_sharpes_numba(returns, indices, trading_days):  # pragma: no cover - compared via tests
        n_samples = indices.shape[0]
        n_obs = indices.shape[1]
        out = np.empty(n_samples, dtype=np.float64)
        for sample_id in range(n_samples):
            total = 0.0
            for i in range(n_obs):
                total += returns[indices[sample_id, i]]
            mean = total / n_obs
            sd = 0.0
            if n_obs > 1:
                var = 0.0
                for i in range(n_obs):
                    diff = returns[indices[sample_id, i]] - mean
                    var += diff * diff
                sd = (var / (n_obs - 1)) ** 0.5
            if sd > 0.0:
                out[sample_id] = (mean / sd) * (trading_days ** 0.5)
            else:
                out[sample_id] = 0.0
        return out

    @njit(cache=True)
    def _path_sharpes_numba(paths, trading_days):  # pragma: no cover - compared via tests
        n_samples = paths.shape[0]
        n_obs = paths.shape[1]
        out = np.empty(n_samples, dtype=np.float64)
        for sample_id in range(n_samples):
            total = 0.0
            for i in range(n_obs):
                total += paths[sample_id, i]
            mean = total / n_obs
            sd = 0.0
            if n_obs > 1:
                var = 0.0
                for i in range(n_obs):
                    diff = paths[sample_id, i] - mean
                    var += diff * diff
                sd = (var / (n_obs - 1)) ** 0.5
            if sd > 0.0:
                out[sample_id] = (mean / sd) * (trading_days ** 0.5)
            else:
                out[sample_id] = 0.0
        return out

else:

    def _score_returns_positions_numba(returns, positions, trading_days):  # pragma: no cover - fallback alias
        return _score_returns_positions_python(returns, positions, trading_days)

    def _bootstrap_sharpes_numba(returns, indices, trading_days):  # pragma: no cover - fallback alias
        return _bootstrap_sharpes_python(returns, indices, trading_days)

    def _path_sharpes_numba(paths, trading_days):  # pragma: no cover - fallback alias
        return _path_sharpes_python(paths, trading_days)


def select_flat_minima_record(
    records: Sequence[WalkForwardTrialRecord],
    param_ranges: Dict[str, Any],
    config: WalkForwardConfig,
) -> WalkForwardTrialRecord:
    """
    Select a robust top-trial cluster member instead of a sharp isolated peak.

    This implements the Phase 3 flat-minima selector with a small deterministic
    DBSCAN-style clustering pass over normalized parameter coordinates.
    """
    candidates = [r for r in records if not r.pruned and np.isfinite(r.objective)]
    if not candidates:
        raise ValueError("flat-minima selection received no completed trials")
    ranked = sorted(candidates, key=lambda record: record.objective, reverse=True)
    top_n = max(1, int(np.ceil(len(ranked) * float(config.flat_top_fraction))))
    top_n = min(len(ranked), max(top_n, int(config.flat_min_samples)))
    top = ranked[:top_n]
    matrix, names = _param_matrix(top, param_ranges)
    if matrix.shape[0] == 1 or matrix.shape[1] == 0:
        return _with_selection_metadata(
            top[0],
            {
                "objective_mode": "mode_3_flat_minima",
                "selector": "fallback_best",
                "reason": "insufficient_cluster_points",
                "top_trials": int(top_n),
            },
        )

    labels, cluster_method = _dbscan_cluster_labels(
        matrix,
        eps=float(config.flat_eps),
        min_samples=int(config.flat_min_samples),
    )
    cluster_ids = sorted(label for label in set(labels.tolist()) if label >= 0)
    if not cluster_ids:
        return _with_selection_metadata(
            top[0],
            {
                "objective_mode": "mode_3_flat_minima",
                "selector": "fallback_best",
                "reason": "no_dense_cluster",
                "top_trials": int(top_n),
                "eps": float(config.flat_eps),
                "min_samples": int(config.flat_min_samples),
                "cluster_method": cluster_method,
            },
        )

    best_cluster = None
    best_key = None
    for cluster_id in cluster_ids:
        member_idx = np.flatnonzero(labels == cluster_id)
        member_objectives = np.array([top[i].objective for i in member_idx], dtype=np.float64)
        key = (len(member_idx), float(np.mean(member_objectives)), float(np.max(member_objectives)))
        if best_key is None or key > best_key:
            best_key = key
            best_cluster = member_idx
    assert best_cluster is not None
    centroid = np.mean(matrix[best_cluster], axis=0)
    distances = np.sqrt(((matrix[best_cluster] - centroid) ** 2).sum(axis=1))
    selected_idx = int(best_cluster[int(np.argmin(distances))])
    medoid = top[selected_idx]
    centroid_params = _centroid_params(
        centroid=centroid,
        names=names,
        param_ranges=param_ranges,
        base_params=medoid.params,
    )
    selected = medoid
    requires_evaluation = False
    if config.flat_selector == "centroid":
        selected = WalkForwardTrialRecord(
            trial_id=-1,
            params=centroid_params,
            objective=float(np.mean([top[i].objective for i in best_cluster])),
            mean_is_sharpe=float(np.mean([top[i].mean_is_sharpe for i in best_cluster])),
            mean_oos_sharpe=float(np.mean([top[i].mean_oos_sharpe for i in best_cluster])),
            mean_decay=float(np.mean([top[i].mean_decay for i in best_cluster])),
            std_decay=float(np.mean([top[i].std_decay for i in best_cluster])),
            fold_metrics=[],
        )
        requires_evaluation = True
    return _with_selection_metadata(
        selected,
        {
            "objective_mode": "mode_3_flat_minima",
            "selector": str(config.flat_selector),
            "param_names": names,
            "selected_trial_id": int(selected.trial_id),
            "medoid_trial_id": int(medoid.trial_id),
            "medoid_params": dict(medoid.params),
            "centroid_params": centroid_params,
            "centroid_normalized": [float(x) for x in centroid.tolist()],
            "requires_evaluation": requires_evaluation,
            "cluster_size": int(len(best_cluster)),
            "cluster_mean_objective": float(np.mean([top[i].objective for i in best_cluster])),
            "cluster_best_objective": float(np.max([top[i].objective for i in best_cluster])),
            "top_trials": int(top_n),
            "eps": float(config.flat_eps),
            "min_samples": int(config.flat_min_samples),
            "cluster_method": cluster_method,
        },
    )


def select_is_plateau_robust_record(
    records: Sequence[WalkForwardTrialRecord],
    param_ranges: Dict[str, Any],
    config: WalkForwardConfig,
) -> WalkForwardTrialRecord:
    """
    Select robust train-only params from the top IS/search trial plateau.

    The selector first takes the top `top_is_fraction`/`top_is_k` trials by the
    train-side objective.  Inside that candidate pool it prefers dense parameter
    regions whose lower-tail and median scores remain strong while penalizing
    noisy, isolated peaks.  OOS metrics are intentionally not used.
    """
    completed = [record for record in records if not record.pruned and np.isfinite(record.objective)]
    if not completed:
        raise ValueError("is_plateau_robust selection received no completed trials")
    ranked = sorted(completed, key=lambda record: record.objective, reverse=True)
    top_n = _candidate_count(len(ranked), config)
    top = ranked[:top_n]
    matrix, names = _param_matrix(top, param_ranges)
    if matrix.shape[0] == 1 or matrix.shape[1] == 0:
        return _with_selection_metadata(
            top[0],
            {
                "objective_mode": config.optimization_mode,
                "selector": "fallback_best_train_objective",
                "selected_by": "is_plateau_robust",
                "oos_used_for_selection": False,
                "reason": "insufficient_cluster_points",
                "top_trials": int(top_n),
            },
        )

    labels, cluster_method = _dbscan_cluster_labels(
        matrix,
        eps=float(config.flat_eps),
        min_samples=int(config.flat_min_samples),
    )
    cluster_ids = sorted(label for label in set(labels.tolist()) if label >= 0)
    if not cluster_ids:
        return _with_selection_metadata(
            top[0],
            {
                "objective_mode": config.optimization_mode,
                "selector": "fallback_best_train_objective",
                "selected_by": "is_plateau_robust",
                "oos_used_for_selection": False,
                "reason": "no_dense_train_plateau",
                "top_trials": int(top_n),
                "eps": float(config.flat_eps),
                "min_samples": int(config.flat_min_samples),
                "cluster_method": cluster_method,
            },
        )

    best_cluster = None
    best_key = None
    best_cluster_stats = None
    for cluster_id in cluster_ids:
        member_idx = np.flatnonzero(labels == cluster_id)
        values = np.array([top[i].objective for i in member_idx], dtype=np.float64)
        q = float(np.quantile(values, float(config.plateau_quantile)))
        median = float(np.median(values))
        std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
        cluster_score = (
            q
            + float(config.plateau_median_weight) * median
            - float(config.plateau_std_penalty) * std
            + float(config.plateau_size_bonus) * float(np.log1p(len(member_idx)))
        )
        key = (cluster_score, q, median, len(member_idx), float(np.max(values)))
        if best_key is None or key > best_key:
            best_key = key
            best_cluster = member_idx
            best_cluster_stats = {
                "plateau_score": float(cluster_score),
                "plateau_quantile_score": q,
                "plateau_median_score": median,
                "plateau_std_score": std,
                "cluster_best_objective": float(np.max(values)),
            }
    assert best_cluster is not None and best_cluster_stats is not None

    centroid = np.mean(matrix[best_cluster], axis=0)
    distances = np.sqrt(((matrix[best_cluster] - centroid) ** 2).sum(axis=1))
    selected_idx = int(best_cluster[int(np.argmin(distances))])
    medoid = top[selected_idx]
    centroid_params = _centroid_params(
        centroid=centroid,
        names=names,
        param_ranges=param_ranges,
        base_params=medoid.params,
    )
    selected = medoid
    requires_evaluation = False
    if config.flat_selector == "centroid":
        selected = WalkForwardTrialRecord(
            trial_id=-1,
            params=centroid_params,
            objective=float(best_cluster_stats["plateau_score"]),
            mean_is_sharpe=float(np.mean([top[i].mean_is_sharpe for i in best_cluster])),
            mean_oos_sharpe=0.0,
            mean_decay=0.0,
            std_decay=0.0,
            fold_metrics=[],
        )
        requires_evaluation = True

    return _with_selection_metadata(
        selected,
        {
            **best_cluster_stats,
            "objective_mode": config.optimization_mode,
            "selector": str(config.flat_selector),
            "selected_by": "is_plateau_robust",
            "oos_used_for_selection": False,
            "param_names": names,
            "selected_trial_id": int(selected.trial_id),
            "medoid_trial_id": int(medoid.trial_id),
            "medoid_params": dict(medoid.params),
            "centroid_params": centroid_params,
            "centroid_normalized": [float(x) for x in centroid.tolist()],
            "requires_evaluation": requires_evaluation,
            "cluster_size": int(len(best_cluster)),
            "top_trials": int(top_n),
            "eps": float(config.flat_eps),
            "min_samples": int(config.flat_min_samples),
            "plateau_quantile": float(config.plateau_quantile),
            "plateau_median_weight": float(config.plateau_median_weight),
            "plateau_std_penalty": float(config.plateau_std_penalty),
            "plateau_size_bonus": float(config.plateau_size_bonus),
            "cluster_method": cluster_method,
        },
    )


def select_is_only_robust_record(
    records: Sequence[WalkForwardTrialRecord],
    param_ranges: Dict[str, Any],
    config: WalkForwardConfig,
) -> WalkForwardTrialRecord:
    """
    Select strict train-only robust params from IS temporal stability + plateau.

    This selector is designed for `mode_4_is_only_robust`.  It never reads OOS
    metrics.  It combines two IS-only robustness signals:

    * temporal robustness across train subperiod shards;
    * plateau robustness across dense top-trial parameter regions.
    """
    completed = [record for record in records if not record.pruned and np.isfinite(record.objective)]
    if not completed:
        raise ValueError("is_only_robust selection received no completed trials")
    ranked = sorted(completed, key=lambda record: record.objective, reverse=True)
    top_n = _candidate_count(len(ranked), config)
    top = ranked[:top_n]
    matrix, names = _param_matrix(top, param_ranges)
    if matrix.shape[0] == 1 or matrix.shape[1] == 0:
        selected = _best_temporal_record(top)
        return _with_selection_metadata(
            selected,
            {
                **selected.selection_metadata,
                "objective_mode": config.optimization_mode,
                "selector": "fallback_best_is_temporal",
                "selected_by": "is_only_robust",
                "oos_used_for_selection": False,
                "reason": "insufficient_cluster_points",
                "top_trials": int(top_n),
                "candidate_selection_complete": True,
            },
        )

    labels, cluster_method = _dbscan_cluster_labels(
        matrix,
        eps=float(config.flat_eps),
        min_samples=int(config.flat_min_samples),
    )
    cluster_ids = sorted(label for label in set(labels.tolist()) if label >= 0)
    if not cluster_ids:
        selected = _best_temporal_record(top)
        return _with_selection_metadata(
            selected,
            {
                **selected.selection_metadata,
                "objective_mode": config.optimization_mode,
                "selector": "fallback_best_is_temporal",
                "selected_by": "is_only_robust",
                "oos_used_for_selection": False,
                "reason": "no_dense_train_plateau",
                "top_trials": int(top_n),
                "eps": float(config.flat_eps),
                "min_samples": int(config.flat_min_samples),
                "cluster_method": cluster_method,
                "candidate_selection_complete": True,
            },
        )

    best_cluster = None
    best_key = None
    best_cluster_stats = None
    for cluster_id in cluster_ids:
        member_idx = np.flatnonzero(labels == cluster_id)
        objective_values = np.array([top[i].objective for i in member_idx], dtype=np.float64)
        temporal_values = np.array(
            [float(top[i].selection_metadata.get("temporal_score", top[i].mean_is_sharpe)) for i in member_idx],
            dtype=np.float64,
        )
        q = float(np.quantile(objective_values, float(config.plateau_quantile)))
        median = float(np.median(objective_values))
        std = float(np.std(objective_values, ddof=1)) if len(objective_values) > 1 else 0.0
        plateau_score = (
            q
            + float(config.plateau_median_weight) * median
            - float(config.plateau_std_penalty) * std
            + float(config.plateau_size_bonus) * float(np.log1p(len(member_idx)))
        )
        temporal_stats = _temporal_robustness_stats(
            temporal_values,
            q25_weight=float(config.q25_weight),
            dispersion_penalty=float(config.dispersion_penalty),
            fallback=float(np.mean(temporal_values)) if len(temporal_values) else 0.0,
        )
        bootstrap_penalty = 0.0
        complexity_penalty = 0.0
        final_score = (
            float(config.temporal_weight) * float(temporal_stats["temporal_score"])
            + float(config.plateau_weight) * float(plateau_score)
            - bootstrap_penalty
            - complexity_penalty
        )
        key = (
            final_score,
            float(temporal_stats["temporal_q25"]),
            float(temporal_stats["temporal_median"]),
            plateau_score,
            len(member_idx),
            float(np.max(objective_values)),
        )
        if best_key is None or key > best_key:
            best_key = key
            best_cluster = member_idx
            best_cluster_stats = {
                "is_only_robust_score": float(final_score),
                "temporal_score": float(temporal_stats["temporal_score"]),
                "temporal_median": float(temporal_stats["temporal_median"]),
                "temporal_q25": float(temporal_stats["temporal_q25"]),
                "temporal_mad": float(temporal_stats["temporal_mad"]),
                "plateau_score": float(plateau_score),
                "plateau_quantile_score": q,
                "plateau_median_score": median,
                "plateau_std_score": std,
                "cluster_best_objective": float(np.max(objective_values)),
                "bootstrap_penalty": bootstrap_penalty,
                "complexity_penalty": complexity_penalty,
            }
    assert best_cluster is not None and best_cluster_stats is not None

    centroid = np.mean(matrix[best_cluster], axis=0)
    distances = np.sqrt(((matrix[best_cluster] - centroid) ** 2).sum(axis=1))
    selected_idx = int(best_cluster[int(np.argmin(distances))])
    medoid = top[selected_idx]
    centroid_params = _centroid_params(
        centroid=centroid,
        names=names,
        param_ranges=param_ranges,
        base_params=medoid.params,
    )
    selected = medoid
    requires_evaluation = False
    if config.flat_selector == "centroid":
        selected = WalkForwardTrialRecord(
            trial_id=-1,
            params=centroid_params,
            objective=float(best_cluster_stats["is_only_robust_score"]),
            mean_is_sharpe=float(np.mean([top[i].mean_is_sharpe for i in best_cluster])),
            mean_oos_sharpe=0.0,
            mean_decay=0.0,
            std_decay=0.0,
            fold_metrics=[],
        )
        requires_evaluation = True

    return _with_selection_metadata(
        selected,
        {
            **selected.selection_metadata,
            **best_cluster_stats,
            "objective_mode": config.optimization_mode,
            "selector": str(config.flat_selector),
            "selected_by": "is_only_robust",
            "oos_used_for_selection": False,
            "param_names": names,
            "selected_trial_id": int(selected.trial_id),
            "medoid_trial_id": int(medoid.trial_id),
            "medoid_params": dict(medoid.params),
            "centroid_params": centroid_params,
            "centroid_normalized": [float(x) for x in centroid.tolist()],
            "requires_evaluation": requires_evaluation,
            "cluster_size": int(len(best_cluster)),
            "top_trials": int(top_n),
            "eps": float(config.flat_eps),
            "min_samples": int(config.flat_min_samples),
            "plateau_quantile": float(config.plateau_quantile),
            "plateau_median_weight": float(config.plateau_median_weight),
            "plateau_std_penalty": float(config.plateau_std_penalty),
            "plateau_size_bonus": float(config.plateau_size_bonus),
            "is_subperiods": int(config.is_subperiods),
            "q25_weight": float(config.q25_weight),
            "dispersion_penalty": float(config.dispersion_penalty),
            "temporal_weight": float(config.temporal_weight),
            "plateau_weight": float(config.plateau_weight),
            "use_bootstrap_penalty": bool(config.use_bootstrap_penalty),
            "use_complexity_penalty": bool(config.use_complexity_penalty),
            "cluster_method": cluster_method,
        },
    )


def select_full_sample_robust_record(
    records: Sequence[WalkForwardTrialRecord],
    param_ranges: Dict[str, Any],
    config: WalkForwardConfig,
) -> WalkForwardTrialRecord:
    """
    Select params for full-sample robust calibration.

    This is not an OOS validation selector.  The whole supplied history is
    treated as one calibration sample, then top trials are filtered by temporal
    subperiod robustness and parameter-surface plateau robustness.
    """
    metric = config.candidate_selection_metric
    completed = [record for record in records if not record.pruned and np.isfinite(record.objective)]
    if not completed:
        raise ValueError("full-sample robust selection received no completed trials")
    ranked = sorted(completed, key=lambda record: record.objective, reverse=True)

    if metric == "full_best":
        return _with_selection_metadata(
            ranked[0],
            {
                **ranked[0].selection_metadata,
                "objective_mode": config.optimization_mode,
                "selected_by": "full_best",
                "selector": "best_full_sample_objective",
                "oos_used_for_selection": False,
                "full_sample_used_for_selection": True,
                "validation_claim": "none_full_sample_calibration",
                "candidate_selection_complete": True,
            },
        )

    if metric == "full_temporal_robust":
        top_n = _candidate_count(len(ranked), config)
        top = ranked[:top_n]
        selected = _best_temporal_record(top)
        return _with_selection_metadata(
            selected,
            {
                **selected.selection_metadata,
                "objective_mode": config.optimization_mode,
                "selected_by": "full_temporal_robust",
                "selector": "best_full_sample_temporal_score",
                "oos_used_for_selection": False,
                "full_sample_used_for_selection": True,
                "validation_claim": "none_full_sample_calibration",
                "top_trials": int(top_n),
                "candidate_selection_complete": True,
            },
        )

    if metric == "full_plateau_robust":
        selected = select_is_plateau_robust_record(completed, param_ranges, config=config)
        selected_by = "full_plateau_robust"
    else:
        selected = select_is_only_robust_record(completed, param_ranges, config=config)
        selected_by = "full_robust"

    return _with_selection_metadata(
        selected,
        {
            **selected.selection_metadata,
            "objective_mode": config.optimization_mode,
            "selected_by": selected_by,
            "oos_used_for_selection": False,
            "full_sample_used_for_selection": True,
            "validation_claim": "none_full_sample_calibration",
            "candidate_selection_complete": True,
        },
    )


def _select_is_candidate_records(
    records: Sequence[WalkForwardTrialRecord],
    param_ranges: Dict[str, Any],
    config: WalkForwardConfig,
) -> List[WalkForwardTrialRecord]:
    completed = [record for record in records if not record.pruned and np.isfinite(record.objective)]
    if not completed:
        raise ValueError("anti-leakage optimization completed no valid in-sample trials")
    ranked = sorted(completed, key=lambda record: record.objective, reverse=True)
    top_n = _candidate_count(len(ranked), config)
    top = ranked[:top_n]
    if config.optimization_mode == "mode_5_full_robust":
        full = select_full_sample_robust_record(completed, param_ranges, config=config)
        return [full, *top]
    if config.candidate_selection_metric == "is_only_robust" or config.optimization_mode == "mode_4_is_only_robust":
        robust = select_is_only_robust_record(completed, param_ranges, config=config)
        return [robust, *top]
    if config.candidate_selection_metric == "is_plateau_robust":
        plateau = select_is_plateau_robust_record(completed, param_ranges, config=config)
        return [plateau, *top]
    if config.optimization_mode == "mode_3_flat_minima":
        flat = select_flat_minima_record(completed, param_ranges, config=config)
        return [flat, *top]
    return top


def _candidate_count(n_records: int, config: WalkForwardConfig) -> int:
    if n_records <= 0:
        return 0
    if config.top_is_k is not None:
        return max(1, min(n_records, int(config.top_is_k)))
    return max(1, min(n_records, int(np.ceil(n_records * float(config.top_is_fraction)))))


def _best_temporal_record(records: Sequence[WalkForwardTrialRecord]) -> WalkForwardTrialRecord:
    return max(
        records,
        key=lambda record: (
            float(record.selection_metadata.get("temporal_score", record.mean_is_sharpe)),
            float(record.selection_metadata.get("temporal_q25", record.mean_is_sharpe)),
            float(record.objective),
        ),
    )


def _split_index_into_subperiods(index: pd.DatetimeIndex, n_parts: int) -> List[pd.DatetimeIndex]:
    idx = validate_datetime(index)
    if len(idx) == 0:
        return []
    n = max(1, min(int(n_parts), len(idx)))
    return [pd.DatetimeIndex(part) for part in np.array_split(idx, n) if len(part) > 0]


def _collect_subperiod_sharpes(fold_metrics: Sequence[Dict[str, Any]]) -> List[float]:
    values: List[float] = []
    for metrics in fold_metrics:
        for value in metrics.get("is_subperiod_sharpes", []) or []:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if np.isfinite(numeric):
                values.append(numeric)
    return values


def _temporal_robustness_stats(
    values,
    q25_weight: float,
    dispersion_penalty: float,
    fallback: float,
) -> Dict[str, float]:
    arr = np.asarray(list(values), dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        fallback_value = float(fallback)
        return {
            "temporal_score": fallback_value,
            "temporal_median": fallback_value,
            "temporal_q25": fallback_value,
            "temporal_mad": 0.0,
            "temporal_count": 0.0,
        }
    median = float(np.median(arr))
    q25 = float(np.quantile(arr, 0.25))
    mad = float(np.median(np.abs(arr - median)))
    score = median + float(q25_weight) * q25 - float(dispersion_penalty) * mad
    return {
        "temporal_score": float(score),
        "temporal_median": median,
        "temporal_q25": q25,
        "temporal_mad": mad,
        "temporal_count": float(arr.size),
    }


def _select_oos_candidate_record(
    records: Sequence[WalkForwardTrialRecord],
    config: WalkForwardConfig,
) -> WalkForwardTrialRecord:
    metric = config.candidate_selection_metric
    if metric == "robust_decay":
        key = lambda record: record.objective
    elif metric == "mean_oos_sharpe":
        key = lambda record: record.mean_oos_sharpe
    elif metric == "mean_is_sharpe":
        key = lambda record: record.mean_is_sharpe
    elif metric == "is_plateau_robust":
        selected = next(
            (
                record
                for record in records
                if record.selection_metadata.get("selected_by") == "is_plateau_robust"
            ),
            None,
        )
        if selected is None:
            key = lambda record: record.selection_metadata.get("plateau_score", record.mean_is_sharpe)
            selected = max(records, key=key)
        return _with_selection_metadata(
            selected,
            {
                **selected.selection_metadata,
                "selected_by": metric,
                "candidate_selection_complete": True,
                "oos_seen_by_optuna": False,
                "oos_used_for_selection": False,
            },
        )
    elif metric == "is_only_robust":
        selected = next(
            (
                record
                for record in records
                if record.selection_metadata.get("selected_by") == "is_only_robust"
            ),
            None,
        )
        if selected is None:
            key = lambda record: record.selection_metadata.get("is_only_robust_score", record.selection_metadata.get("temporal_score", record.mean_is_sharpe))
            selected = max(records, key=key)
        return _with_selection_metadata(
            selected,
            {
                **selected.selection_metadata,
                "selected_by": metric,
                "candidate_selection_complete": True,
                "oos_seen_by_optuna": False,
                "oos_used_for_selection": False,
            },
        )
    else:  # pragma: no cover - validated in config
        raise ValueError(f"unsupported candidate_selection_metric: {metric}")
    selected = max(records, key=key)
    return _with_selection_metadata(
        selected,
        {
            **selected.selection_metadata,
            "selected_by": metric,
            "candidate_selection_complete": True,
            "oos_seen_by_optuna": False,
        },
    )


def _with_selection_metadata(record: WalkForwardTrialRecord, metadata: Dict[str, Any]) -> WalkForwardTrialRecord:
    return WalkForwardTrialRecord(
        trial_id=record.trial_id,
        params=dict(record.params),
        objective=record.objective,
        mean_is_sharpe=record.mean_is_sharpe,
        mean_oos_sharpe=record.mean_oos_sharpe,
        mean_decay=record.mean_decay,
        std_decay=record.std_decay,
        fold_metrics=list(record.fold_metrics),
        pruned=record.pruned,
        selection_metadata=dict(metadata),
    )


def _without_fold_metrics(record: WalkForwardTrialRecord) -> WalkForwardTrialRecord:
    """Compact a completed trial ledger row after all selectors have finished."""
    if not record.fold_metrics:
        return record
    return WalkForwardTrialRecord(
        trial_id=int(record.trial_id),
        params=dict(record.params),
        objective=float(record.objective),
        mean_is_sharpe=float(record.mean_is_sharpe),
        mean_oos_sharpe=float(record.mean_oos_sharpe),
        mean_decay=float(record.mean_decay),
        std_decay=float(record.std_decay),
        fold_metrics=[],
        pruned=bool(record.pruned),
        selection_metadata=dict(record.selection_metadata),
    )


def _param_matrix(
    records: Sequence[WalkForwardTrialRecord],
    param_ranges: Dict[str, Any],
) -> Tuple[np.ndarray, List[str]]:
    names = [name for name in param_ranges.keys() if _is_clusterable_param(name, param_ranges[name], records)]
    if not names:
        return np.zeros((len(records), 0), dtype=np.float64), []
    matrix = np.zeros((len(records), len(names)), dtype=np.float64)
    for col, name in enumerate(names):
        spec = param_ranges[name]
        values = [record.params.get(name) for record in records]
        matrix[:, col] = _normalize_param_values(values, spec)
    return matrix, names


def _is_clusterable_param(name: str, spec: Any, records: Sequence[WalkForwardTrialRecord]) -> bool:
    values = [record.params.get(name) for record in records]
    return any(value is not None for value in values) and len(set(map(str, values))) > 1


def _normalize_param_values(values: Sequence[Any], spec: Any) -> np.ndarray:
    if isinstance(spec, tuple) and len(spec) in (2, 3) and all(_is_number(x) for x in spec):
        low = float(spec[0])
        high = float(spec[1])
        denom = high - low
        if denom == 0.0:
            return np.zeros(len(values), dtype=np.float64)
        return np.array([(float(value) - low) / denom for value in values], dtype=np.float64)
    if isinstance(spec, (list, tuple)):
        choices = list(spec)
        denom = max(1, len(choices) - 1)
        encoded = []
        for value in values:
            try:
                encoded.append(float(choices.index(value)) / float(denom))
            except ValueError:
                encoded.append(0.0)
        return np.array(encoded, dtype=np.float64)
    numeric = np.array([float(value) if _is_number(value) else 0.0 for value in values], dtype=np.float64)
    span = float(np.max(numeric) - np.min(numeric))
    if span == 0.0:
        return np.zeros(len(values), dtype=np.float64)
    return (numeric - float(np.min(numeric))) / span


def _centroid_params(
    centroid: np.ndarray,
    names: Sequence[str],
    param_ranges: Dict[str, Any],
    base_params: Dict[str, Any],
) -> Dict[str, Any]:
    params = dict(base_params)
    for value, name in zip(centroid, names):
        params[name] = _denormalize_param_value(float(value), param_ranges[name])
    return params


def _denormalize_param_value(value: float, spec: Any) -> Any:
    clipped = min(1.0, max(0.0, float(value)))
    if isinstance(spec, tuple) and len(spec) in (2, 3) and all(_is_number(x) for x in spec):
        low = float(spec[0])
        high = float(spec[1])
        raw = low + clipped * (high - low)
        step = spec[2] if len(spec) == 3 else None
        if step is not None:
            step_f = float(step)
            if step_f > 0.0:
                raw = low + round((raw - low) / step_f) * step_f
        raw = min(high, max(low, raw))
        if _looks_int(spec[0]) and _looks_int(spec[1]) and (step is None or _looks_int(step)):
            return int(round(raw))
        return float(raw)
    if isinstance(spec, (list, tuple)):
        choices = list(spec)
        if not choices:
            raise ValueError("cannot denormalize an empty categorical parameter range")
        idx = int(round(clipped * (len(choices) - 1)))
        return choices[min(len(choices) - 1, max(0, idx))]
    return spec


def _dbscan_cluster_labels(matrix: np.ndarray, eps: float, min_samples: int) -> Tuple[np.ndarray, str]:
    try:
        from sklearn.cluster import DBSCAN

        labels = DBSCAN(eps=float(eps), min_samples=int(min_samples), metric="euclidean").fit_predict(matrix)
        return labels.astype(np.int64), "sklearn.DBSCAN"
    except Exception:
        return _density_cluster_labels(matrix, eps=float(eps), min_samples=int(min_samples)), "numpy_dbscan_fallback"


def _density_cluster_labels(matrix: np.ndarray, eps: float, min_samples: int) -> np.ndarray:
    n = matrix.shape[0]
    labels = np.full(n, -1, dtype=np.int64)
    visited = np.zeros(n, dtype=bool)
    cluster_id = 0
    for point in range(n):
        if visited[point]:
            continue
        visited[point] = True
        neighbors = _region_query(matrix, point, eps)
        if len(neighbors) < min_samples:
            continue
        labels[point] = cluster_id
        seeds = list(neighbors)
        cursor = 0
        while cursor < len(seeds):
            neighbor = seeds[cursor]
            if not visited[neighbor]:
                visited[neighbor] = True
                neighbor_neighbors = _region_query(matrix, int(neighbor), eps)
                if len(neighbor_neighbors) >= min_samples:
                    for candidate in neighbor_neighbors:
                        if int(candidate) not in seeds:
                            seeds.append(int(candidate))
            if labels[neighbor] < 0:
                labels[neighbor] = cluster_id
            cursor += 1
        cluster_id += 1
    return labels


def _region_query(matrix: np.ndarray, point: int, eps: float) -> List[int]:
    diff = matrix - matrix[int(point)]
    distances = np.sqrt((diff * diff).sum(axis=1))
    return [int(i) for i in np.flatnonzero(distances <= eps)]


def stitch_oos_outputs(
    outputs: Sequence[StrategyOutput],
    folds: Sequence[WalkForwardFold],
    full_index: Union[pd.DatetimeIndex, pd.Series],
    fill_value: float = 0.0,
) -> Optional[StrategyOutput]:
    """Stitch per-fold OOS strategy output into one full-index object."""
    idx = validate_datetime(full_index)
    if len(outputs) != len(folds):
        raise ValueError("outputs and folds must have the same length")
    if not outputs:
        return None

    first = outputs[0]
    if isinstance(first, pd.DataFrame):
        columns = list(first.columns)
        stitched = pd.DataFrame(fill_value, index=idx, columns=columns, dtype=float)
        for out, fold in zip(outputs, folds):
            frame = _normalize_frame_output(out, columns)
            stitched.loc[fold.test_index, columns] = frame.reindex(fold.test_index).fillna(fill_value).values
        return stitched

    if isinstance(first, dict):
        symbols = list(first.keys())
        stitched = {symbol: pd.Series(fill_value, index=idx, dtype=float) for symbol in symbols}
        for out, fold in zip(outputs, folds):
            if not isinstance(out, dict) or set(out.keys()) != set(symbols):
                raise TypeError("all walk-forward dict outputs must have the same symbol keys")
            for symbol in symbols:
                series = _normalize_series_output(out[symbol])
                stitched[symbol].loc[fold.test_index] = series.reindex(fold.test_index).fillna(fill_value).values
        return stitched

    stitched = pd.Series(fill_value, index=idx, dtype=float)
    for out, fold in zip(outputs, folds):
        series = _normalize_series_output(out)
        stitched.loc[fold.test_index] = series.reindex(fold.test_index).fillna(fill_value).values
    return stitched


def _infer_datetime_index(data, datetime_index) -> pd.DatetimeIndex:
    if datetime_index is not None:
        return validate_datetime(datetime_index)
    if isinstance(data, pd.DataFrame):
        return validate_datetime(data.index)
    if isinstance(data, dict):
        if not data:
            raise ValueError("walk-forward data dict is empty")
        first = next(iter(data.values()))
        if isinstance(first, pd.DataFrame) or isinstance(first, pd.Series):
            return validate_datetime(first.index)
    raise ValueError("datetime_index is required when data has no DatetimeIndex")


def _align_data_to_datetime_index(data, idx: pd.DatetimeIndex):
    """
    Return a data view/copy whose timestamp index matches WFO fold indices.

    `validate_datetime` normalizes fold indices to UTC. Real research frames
    are often tz-naive; passing them unchanged into a strategy makes common
    code like `series.reindex(test_index)` silently return all NaN. Alignment is
    length-preserving and does not inspect future values.
    """
    if isinstance(data, pd.DataFrame):
        if len(data) != len(idx):
            return data
        out = data.copy()
        out.index = idx
        return out
    if isinstance(data, pd.Series):
        if len(data) != len(idx):
            return data
        out = data.copy()
        out.index = idx
        return out
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if isinstance(value, pd.DataFrame) and len(value) == len(idx):
                item = value.copy()
                item.index = idx
                out[key] = item
            elif isinstance(value, pd.Series) and len(value) == len(idx):
                item = value.copy()
                item.index = idx
                out[key] = item
            else:
                out[key] = value
        return out
    return data


def _slice_strategy_data_through(data, end: pd.Timestamp):
    """Expose no market rows after the declared fold evaluation boundary."""
    cutoff = pd.Timestamp(end)
    if isinstance(data, (pd.DataFrame, pd.Series)):
        return data.loc[data.index <= cutoff]
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if isinstance(value, (pd.DataFrame, pd.Series)) and isinstance(value.index, pd.DatetimeIndex):
                out[key] = value.loc[value.index <= cutoff]
            else:
                out[key] = value
        return out
    return data


def _slice_strategy_data_by_stop(
    data,
    *,
    stop: int,
    end: pd.Timestamp,
    strategy_copy: bool,
):
    """Integer-slice prepared data while preserving strategy mutation isolation."""
    if isinstance(data, (pd.DataFrame, pd.Series)):
        sliced = data.iloc[:stop]
        return sliced.copy(deep=True) if strategy_copy else sliced
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if isinstance(value, (pd.DataFrame, pd.Series)) and isinstance(value.index, pd.DatetimeIndex):
                item_stop = int(value.index.searchsorted(pd.Timestamp(end), side="right"))
                sliced = value.iloc[:item_stop]
                out[key] = sliced.copy(deep=True) if strategy_copy else sliced
            else:
                out[key] = value
        return out
    return data


def _derive_fold_seed(base_seed: int, fold_id: int) -> int:
    """Return a deterministic independent uint32-compatible study seed."""
    return int((int(base_seed) + int(fold_id) * 1_000_003) % (2**32))


def _fold_boundary_table(
    stitched: Optional[StrategyOutput],
    folds: Sequence[WalkForwardFold],
    full_index: pd.DatetimeIndex,
    fill_value: float = 0.0,
) -> pd.DataFrame:
    """Describe target continuity at adjacent fold boundaries without trading."""
    columns = [
        "previous_fold_id",
        "fold_id",
        "previous_test_end",
        "test_start",
        "gap_bars",
        "gap_policy",
        "gap_fill_value",
        "target_before",
        "target_after",
        "changed_targets",
        "position_policy",
    ]
    if stitched is None or len(folds) < 2:
        return pd.DataFrame(columns=columns)

    idx = validate_datetime(full_index)
    rows = []
    for previous, current in zip(folds[:-1], folds[1:]):
        previous_position = int(idx.get_indexer([previous.test_end])[0])
        current_position = int(idx.get_indexer([current.test_start])[0])
        if previous_position < 0 or current_position < 0:
            raise ValueError("walk-forward boundary timestamp is missing from the stitched index")
        before = _target_snapshot(stitched, previous.test_end)
        after = _target_snapshot(stitched, current.test_start)
        rows.append(
            {
                "previous_fold_id": int(previous.fold_id),
                "fold_id": int(current.fold_id),
                "previous_test_end": previous.test_end,
                "test_start": current.test_start,
                "gap_bars": max(0, current_position - previous_position - 1),
                "gap_policy": "fill_value" if current_position - previous_position > 1 else "contiguous",
                "gap_fill_value": float(fill_value),
                "target_before": before,
                "target_after": after,
                "changed_targets": _changed_target_count(before, after),
                "position_policy": "carry",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _target_snapshot(output: StrategyOutput, timestamp: pd.Timestamp):
    if isinstance(output, pd.Series):
        return float(output.loc[timestamp])
    if isinstance(output, pd.DataFrame):
        return {str(key): float(value) for key, value in output.loc[timestamp].items()}
    if isinstance(output, dict):
        return {str(key): float(series.loc[timestamp]) for key, series in output.items()}
    raise TypeError("unsupported stitched walk-forward target type")


def _changed_target_count(before, after, tolerance: float = 1e-12) -> int:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = set(before) | set(after)
        return int(
            sum(abs(float(after.get(key, 0.0)) - float(before.get(key, 0.0))) > tolerance for key in keys)
        )
    return int(abs(float(after) - float(before)) > tolerance)


def _inner_validation_metadata(config: WalkForwardConfig) -> Optional[Dict[str, Any]]:
    """Return the explicit nested-validation contract, when Mode 1 uses it."""
    if not (
        config.optimization_mode == "mode_1_decay"
        and config.optimization_schedule == "per_fold_causal"
    ):
        return None
    return {
        "enabled": True,
        "selection_scope": "outer_is_only",
        "inner_split_frequency": config.inner_split_frequency,
        "inner_window_mode": config.inner_window_mode,
        "inner_train_window": config.inner_train_window,
        "inner_min_folds": int(config.inner_min_folds),
        "outer_oos_used_for_selection": False,
    }


def _build_inner_folds(outer_fold: WalkForwardFold, config: WalkForwardConfig) -> List[WalkForwardFold]:
    """Build nested chronological folds strictly inside one outer IS window."""
    if (
        config.inner_split_frequency is None
        or config.inner_window_mode is None
        or config.inner_train_window is None
    ):
        raise ValueError(
            "causal Mode 1 nested validation is missing inner fold configuration"
        )

    idx = validate_datetime(outer_fold.train_index)
    minimum_train_end = idx[0] + pd.Timedelta(config.inner_train_window)
    first_position = int(idx.searchsorted(minimum_train_end, side="left"))
    if first_position >= len(idx):
        raise ValueError(
            "causal Mode 1 outer fold "
            f"{outer_fold.fold_id} has no room for an inner OOS window after "
            f"inner_train_window={config.inner_train_window!r}"
        )

    first_oos = idx[first_position]
    frequency = str(config.inner_split_frequency)
    window_mode = str(config.inner_window_mode)
    train_window = pd.Timedelta(config.inner_train_window)
    folds: List[WalkForwardFold] = []

    if frequency == "single":
        train_start = idx[0] if window_mode == "expanding" else first_oos - train_window
        train_index = idx[(idx >= train_start) & (idx < first_oos)]
        test_index = idx[idx >= first_oos]
        if len(train_index) >= config.min_train_bars and len(test_index) >= config.min_test_bars:
            folds.append(
                WalkForwardFold(
                    fold_id=0,
                    train_start=train_index[0],
                    train_end=train_index[-1],
                    test_start=test_index[0],
                    test_end=test_index[-1],
                    train_index=train_index,
                    test_index=test_index,
                )
            )
    else:
        step = _frequency_offset(frequency)
        test_start = first_oos
        inner_fold_id = 0
        while test_start <= idx[-1]:
            test_stop = test_start + step
            test_index = idx[(idx >= test_start) & (idx < test_stop)]
            if len(test_index) < config.min_test_bars:
                test_start = test_stop
                continue

            train_start = idx[0] if window_mode == "expanding" else test_start - train_window
            train_index = idx[(idx >= train_start) & (idx < test_start)]
            if len(train_index) >= config.min_train_bars:
                folds.append(
                    WalkForwardFold(
                        fold_id=inner_fold_id,
                        train_start=train_index[0],
                        train_end=train_index[-1],
                        test_start=test_index[0],
                        test_end=test_index[-1],
                        train_index=train_index,
                        test_index=test_index,
                    )
                )
                inner_fold_id += 1
            test_start = test_stop

    if len(folds) < int(config.inner_min_folds):
        raise ValueError(
            "causal Mode 1 outer fold "
            f"{outer_fold.fold_id} produced {len(folds)} inner folds; "
            f"inner_min_folds={config.inner_min_folds} is required. "
            "Use an earlier outer OOS start, a shorter inner_train_window, "
            "or a coarser inner_split_frequency."
        )
    if any(inner_fold.test_end > outer_fold.train_end for inner_fold in folds):
        raise RuntimeError("nested Mode 1 construction leaked beyond the outer IS boundary")
    return folds


def _inner_fold_audit_rows(
    *,
    outer_fold: WalkForwardFold,
    inner_folds: Sequence[WalkForwardFold],
) -> List[Dict[str, Any]]:
    """Create immutable provenance rows for nested Mode 1 validation."""
    return [
        {
            "outer_fold_id": int(outer_fold.fold_id),
            "outer_train_start": outer_fold.train_start,
            "outer_train_end": outer_fold.train_end,
            "outer_test_start": outer_fold.test_start,
            "inner_fold_id": int(inner_fold.fold_id),
            "inner_train_start": inner_fold.train_start,
            "inner_train_end": inner_fold.train_end,
            "inner_test_start": inner_fold.test_start,
            "inner_test_end": inner_fold.test_end,
            "outer_oos_used_for_selection": False,
        }
        for inner_fold in inner_folds
    ]


def _first_oos_timestamp(split_mode) -> pd.Timestamp:
    if isinstance(split_mode, int):
        ts = pd.Timestamp(year=int(split_mode), month=1, day=1, tz="UTC")
    else:
        raw = str(split_mode)
        if raw.startswith("walk_forward_"):
            raw = raw.replace("walk_forward_", "", 1)
        if raw.isdigit() and len(raw) == 4:
            ts = pd.Timestamp(year=int(raw), month=1, day=1, tz="UTC")
        else:
            ts = pd.Timestamp(raw)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _frequency_offset(split_frequency: str) -> pd.DateOffset:
    if split_frequency == "yearly":
        return pd.DateOffset(years=1)
    if split_frequency == "semi_yearly":
        return pd.DateOffset(months=6)
    if split_frequency == "quarterly":
        return pd.DateOffset(months=3)
    if split_frequency == "monthly":
        return pd.DateOffset(months=1)
    if split_frequency == "weekly":
        return pd.DateOffset(weeks=1)
    raise ValueError("unsupported split_frequency")


def _default_params_from_ranges(param_ranges: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for key, value in param_ranges.items():
        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                raise ValueError(f"param_ranges[{key!r}] is empty")
            params[key] = value[0]
        else:
            params[key] = value
    return params


def _slice_output_to_test(output: StrategyOutput, test_index: pd.DatetimeIndex) -> StrategyOutput:
    if isinstance(output, pd.DataFrame):
        return _normalize_frame_output(output).reindex(test_index).fillna(0.0)
    if isinstance(output, dict):
        return {key: _normalize_series_output(value).reindex(test_index).fillna(0.0) for key, value in output.items()}
    return _normalize_series_output(output).reindex(test_index).fillna(0.0)


def _normalize_series_output(output) -> pd.Series:
    if not isinstance(output, pd.Series):
        output = pd.Series(output)
    series = output.copy()
    if isinstance(series.index, pd.DatetimeIndex):
        series.index = series.index.tz_localize("UTC") if series.index.tz is None else series.index.tz_convert("UTC")
    return series[~series.index.duplicated(keep="first")].astype(float)


def _normalize_frame_output(output, columns: Optional[List[str]] = None) -> pd.DataFrame:
    if not isinstance(output, pd.DataFrame):
        raise TypeError("walk-forward output must be a pandas DataFrame")
    frame = output.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        frame.index = frame.index.tz_localize("UTC") if frame.index.tz is None else frame.index.tz_convert("UTC")
    frame = frame[~frame.index.duplicated(keep="first")]
    if columns is not None:
        missing = set(columns) - set(frame.columns)
        if missing:
            raise ValueError(f"walk-forward output missing columns: {sorted(missing)}")
        frame = frame[columns]
    return frame.astype(float)


def _fold_table(folds: Sequence[WalkForwardFold]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fold_id": fold.fold_id,
                "train_start": fold.train_start,
                "train_end": fold.train_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "train_bars": len(fold.train_index),
                "test_bars": len(fold.test_index),
            }
            for fold in folds
        ]
    )


def _sample_params(trial, param_ranges: Dict[str, Any]) -> Dict[str, Any]:
    return _optimization_suggest_params(trial, param_ranges)


def _looks_int(value: Any) -> bool:
    return isinstance(value, (int, np.integer)) or (isinstance(value, float) and float(value).is_integer())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating))


def _trial_table(records: Sequence[WalkForwardTrialRecord]) -> pd.DataFrame:
    return pd.DataFrame([_trial_to_dict(record, include_fold_metrics=False) for record in records])


def _optuna_record_count(records: Sequence[WalkForwardTrialRecord]) -> int:
    return int(
        sum(
            record.pruned or record.selection_metadata.get("stage") in {"is_search", "sbb_search"}
            for record in records
        )
    )


def _trial_to_dict(record: WalkForwardTrialRecord, include_fold_metrics: bool = True) -> Dict[str, Any]:
    out = {
        "trial_id": record.trial_id,
        "params": record.params,
        "objective": record.objective,
        "mean_is_sharpe": record.mean_is_sharpe,
        "mean_oos_sharpe": record.mean_oos_sharpe,
        "mean_decay": record.mean_decay,
        "std_decay": record.std_decay,
        "pruned": record.pruned,
    }
    if include_fold_metrics:
        out["fold_metrics"] = record.fold_metrics
    if record.selection_metadata:
        out["selection_metadata"] = record.selection_metadata
        for key in (
            "temporal_score",
            "temporal_median",
            "temporal_q25",
            "temporal_mad",
            "temporal_count",
            "is_subperiod_count",
            "is_only_robust_score",
            "plateau_score",
            "schedule_fold_id",
            "study_id",
            "fold_seed",
            "outer_oos_used_for_selection",
        ):
            if key in record.selection_metadata:
                out[key] = record.selection_metadata[key]
    return out


def _close_map_from_data(data) -> Dict[str, pd.Series]:
    if isinstance(data, pd.DataFrame):
        if "close" not in data.columns:
            raise ValueError("walk-forward scoring requires a close column")
        return {"DEFAULT": _series_utc(data["close"])}
    if isinstance(data, dict):
        out: Dict[str, pd.Series] = {}
        for key, value in data.items():
            if isinstance(value, pd.DataFrame):
                if "close" not in value.columns:
                    raise ValueError(f"walk-forward scoring data[{key!r}] requires a close column")
                out[key] = _series_utc(value["close"])
            elif isinstance(value, pd.Series):
                out[key] = _series_utc(value)
            else:
                raise TypeError("walk-forward scoring dict values must be DataFrame or Series")
        if not out:
            raise ValueError("walk-forward scoring data dict is empty")
        return out
    raise TypeError("walk-forward scoring requires DataFrame or dict data")


def _series_utc(series: pd.Series) -> pd.Series:
    out = series.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        out.index = out.index.tz_localize("UTC") if out.index.tz is None else out.index.tz_convert("UTC")
    return out[~out.index.duplicated(keep="first")].astype(float)


def _data_hash(data) -> str:
    try:
        if isinstance(data, pd.DataFrame):
            idx = validate_datetime(data.index)
            payload = {"kind": "frame", "rows": len(data), "start": str(idx[0]), "end": str(idx[-1]), "columns": list(data.columns)}
        elif isinstance(data, dict):
            payload = {"kind": "dict", "keys": sorted(data.keys())}
            spans = {}
            for key, value in data.items():
                if isinstance(value, (pd.DataFrame, pd.Series)):
                    idx = validate_datetime(value.index)
                    spans[key] = {"rows": len(value), "start": str(idx[0]), "end": str(idx[-1])}
            payload["spans"] = spans
        else:
            payload = {"kind": type(data).__name__}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    except Exception:
        return "unavailable"


def _complete_data_hash(data) -> str:
    """Hash all timestamped values which can affect a prepared WFO replay."""
    digest = hashlib.sha256()

    def update(value, label: str) -> None:
        digest.update(label.encode("utf-8"))
        digest.update(type(value).__name__.encode("utf-8"))
        if isinstance(value, pd.DataFrame):
            digest.update(json.dumps([str(column) for column in value.columns]).encode("utf-8"))
            hashed = pd.util.hash_pandas_object(value, index=True, categorize=True)
            digest.update(np.ascontiguousarray(hashed.to_numpy(dtype=np.uint64)).tobytes())
        elif isinstance(value, pd.Series):
            digest.update(str(value.name).encode("utf-8"))
            hashed = pd.util.hash_pandas_object(value, index=True, categorize=True)
            digest.update(np.ascontiguousarray(hashed.to_numpy(dtype=np.uint64)).tobytes())
        elif isinstance(value, dict):
            for key in sorted(value, key=lambda item: str(item)):
                update(value[key], f"{label}.{key}")
        else:
            digest.update(json.dumps(value, sort_keys=True, default=str).encode("utf-8"))

    try:
        update(data, "market")
        return digest.hexdigest()
    except Exception:
        # Object-heavy research columns can be unhashable to pandas. Preserve a
        # deterministic fallback rather than permitting an identity-only cache.
        digest = hashlib.sha256()
        digest.update(_data_hash(data).encode("utf-8"))
        digest.update(repr(data).encode("utf-8"))
        return digest.hexdigest()


def _config_hash(config: WalkForwardConfig) -> str:
    payload = {
        "split_mode": str(config.split_mode),
        "split_frequency": config.split_frequency,
        "window_mode": config.window_mode,
        "train_window": config.train_window,
        "min_train_bars": config.min_train_bars,
        "min_test_bars": config.min_test_bars,
        "target_mode": config.target_mode,
        "optimization_mode": config.optimization_mode,
        "optimization_schedule": config.optimization_schedule,
        "fold_boundary_position_policy": config.fold_boundary_position_policy,
        "optuna_trials": config.optuna_trials,
        "optuna_early_stopping": config.optuna_early_stopping,
        "random_seed": config.random_seed,
        "decay_lambda": config.decay_lambda,
        "decay_gamma": config.decay_gamma,
        "top_is_fraction": config.top_is_fraction,
        "top_is_k": config.top_is_k,
        "candidate_selection_metric": config.candidate_selection_metric,
        "candidate_decay_lambda": config.candidate_decay_lambda,
        "candidate_decay_gamma": config.candidate_decay_gamma,
        "sbb_samples": config.sbb_samples,
        "sbb_block_length": config.sbb_block_length,
        "sbb_decay_lambda": config.sbb_decay_lambda,
        "sbb_std_penalty": config.sbb_std_penalty,
        "sbb_simulation": config.sbb_simulation,
        "regime_count": config.regime_count,
        "regime_lookback": config.regime_lookback,
        "regime_weights": config.regime_weights,
        "stress_vol_multiplier": config.stress_vol_multiplier,
        "garch_p": config.garch_p,
        "garch_q": config.garch_q,
        "garch_dist": config.garch_dist,
        "garch_vol_multiplier": config.garch_vol_multiplier,
        "flat_top_fraction": config.flat_top_fraction,
        "flat_eps": config.flat_eps,
        "flat_min_samples": config.flat_min_samples,
        "flat_selector": config.flat_selector,
        "plateau_quantile": config.plateau_quantile,
        "plateau_median_weight": config.plateau_median_weight,
        "plateau_std_penalty": config.plateau_std_penalty,
        "plateau_size_bonus": config.plateau_size_bonus,
        "is_subperiods": config.is_subperiods,
        "q25_weight": config.q25_weight,
        "dispersion_penalty": config.dispersion_penalty,
        "temporal_weight": config.temporal_weight,
        "plateau_weight": config.plateau_weight,
        "use_bootstrap_penalty": config.use_bootstrap_penalty,
        "use_complexity_penalty": config.use_complexity_penalty,
        "scoring_backend": config.scoring_backend,
        "scoring_trading_days": config.scoring_trading_days,
        "min_trades_per_year": config.min_trades_per_year,
        "trade_penalty_factor": config.trade_penalty_factor,
        "use_numba": config.use_numba,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
