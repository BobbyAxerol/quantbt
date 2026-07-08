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
import operator
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from .core.preprocessor import validate_datetime

try:  # optional acceleration; Python/NumPy baseline remains available
    from numba import njit
except Exception:  # pragma: no cover - optional dependency guard
    njit = None

_NUMBA_AVAILABLE = njit is not None

try:  # optional at import time; required only when optimization runs
    import optuna as _optuna
except Exception:  # pragma: no cover - optional dependency guard
    _optuna = None


StrategyOutput = Union[pd.Series, pd.DataFrame, Dict[str, pd.Series]]


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
class WalkForwardConfig:
    """
    Configuration for Phase 1 walk-forward splitting and stitching.

    Parameters
    ----------
    split_mode:
        String such as `walk_forward_2022`, an integer year, or a timestamp-like
        value marking the first OOS period.
    split_frequency:
        `yearly`, `semi_yearly`, or `quarterly`.
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
    optuna_trials: int = 0
    optuna_early_stopping: Optional[int] = None
    random_seed: int = 42
    decay_lambda: float = 0.5
    decay_gamma: float = 0.5
    sbb_samples: int = 256
    sbb_block_length: int = 20
    sbb_decay_lambda: float = 0.5
    sbb_std_penalty: float = 0.1
    flat_top_fraction: float = 0.1
    flat_eps: float = 0.15
    flat_min_samples: int = 3
    flat_selector: str = "medoid"
    use_numba: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        freq = self.split_frequency.lower().strip()
        if freq not in {"yearly", "semi_yearly", "quarterly"}:
            raise ValueError("split_frequency must be yearly, semi_yearly, or quarterly")
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
        if opt_mode not in {"none", "mode_1_decay", "mode_2_sbb", "mode_3_flat_minima"}:
            raise NotImplementedError(
                "optimization_mode must be one of: none, mode_1_decay, mode_2_sbb, mode_3_flat_minima"
            )
        object.__setattr__(self, "optimization_mode", opt_mode)
        if self.optuna_trials < 0:
            raise ValueError("optuna_trials must be >= 0")
        if self.optuna_early_stopping is not None and self.optuna_early_stopping <= 0:
            raise ValueError("optuna_early_stopping must be > 0")
        if self.sbb_samples <= 0:
            raise ValueError("sbb_samples must be > 0")
        if self.sbb_block_length <= 0:
            raise ValueError("sbb_block_length must be > 0")
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


@dataclass
class WalkForwardResult:
    """Phase 1 walk-forward artifact returned before/after final backtest."""

    folds: List[WalkForwardFold]
    oos_output: Optional[StrategyOutput]
    fold_table: pd.DataFrame
    params: Dict[str, Any]
    backtest_result: Any = None
    trial_table: pd.DataFrame = field(default_factory=pd.DataFrame)
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


class EarlyStoppingCallback:
    """Stop Optuna if best value does not improve after N trials."""

    def __init__(self, early_stopping_rounds: int, direction: str = "maximize"):
        self.early_stopping_rounds = int(early_stopping_rounds)
        self._iter = 0
        if direction == "minimize":
            self._operator = operator.lt
            self._score = np.inf
        elif direction == "maximize":
            self._operator = operator.gt
            self._score = -np.inf
        else:
            raise ValueError("direction must be maximize or minimize")

    def __call__(self, study, trial) -> None:
        if self._operator(study.best_value, self._score):
            self._iter = 0
            self._score = study.best_value
        else:
            self._iter += 1
        if self._iter >= self.early_stopping_rounds:
            study.stop()


class DuplicatePruner(_optuna.pruners.BasePruner if _optuna is not None else object):
    """Optuna pruner that avoids running duplicate parameter sets."""

    def __init__(self):
        if _optuna is None:  # pragma: no cover - dependency guard
            raise ImportError("DuplicatePruner requires optuna")
        self.trial_params = set()

    def prune(self, study, trial) -> bool:
        params_key = tuple(sorted(trial.params.items()))
        if params_key in self.trial_params:
            return True
        self.trial_params.add(params_key)
        return False


def logging_callback(study, frozen_trial) -> None:
    """Record previous best value when Optuna improves."""
    previous_best_value = study.user_attrs.get("previous_best_value", None)
    if previous_best_value != study.best_value:
        study.set_user_attr("previous_best_value", study.best_value)


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
    ):
        if strategy is None:
            raise ValueError("WalkForwardEngine requires a strategy callable or strategy class/object")
        self.strategy = strategy
        self.config = config or WalkForwardConfig()

    def run(
        self,
        data,
        params: Optional[Dict[str, Any]] = None,
        param_ranges: Optional[Dict[str, Any]] = None,
        datetime_index: Optional[Union[pd.DatetimeIndex, pd.Series]] = None,
    ) -> WalkForwardResult:
        """Build folds, call the strategy per fold, and stitch OOS output."""
        idx = _infer_datetime_index(data, datetime_index)
        folds = self.build_folds(idx)
        trial_records: List[WalkForwardTrialRecord] = []
        if params is not None:
            chosen_params = dict(params)
            selected_record = self.evaluate_params(data=data, folds=folds, params=chosen_params, trial_id=0)
            trial_records.append(selected_record)
        elif self.config.optimization_mode in {"mode_1_decay", "mode_2_sbb", "mode_3_flat_minima"} and self.config.optuna_trials > 0:
            selected_record, trial_records = self.optimize_params(
                data=data,
                folds=folds,
                param_ranges=param_ranges or {},
            )
            chosen_params = dict(selected_record.params)
        else:
            chosen_params = dict(_default_params_from_ranges(param_ranges or {}))
            selected_record = self.evaluate_params(data=data, folds=folds, params=chosen_params, trial_id=0)
            trial_records.append(selected_record)

        outputs: List[StrategyOutput] = []

        for fold in folds:
            out = self._call_strategy(data=data, params=chosen_params, fold=fold)
            outputs.append(_slice_output_to_test(out, fold.test_index))

        stitched = stitch_oos_outputs(
            outputs=outputs,
            folds=folds,
            full_index=idx,
            fill_value=self.config.fill_value,
        )
        fold_table = _fold_table(folds)
        return WalkForwardResult(
            folds=folds,
            oos_output=stitched,
            fold_table=fold_table,
            params=chosen_params,
            trial_table=_trial_table(trial_records),
            best_trial=_trial_to_dict(selected_record),
            metadata={
                "engine": "walk_forward_phase3",
                "split_mode": str(self.config.split_mode),
                "split_frequency": self.config.split_frequency,
                "window_mode": self.config.window_mode,
                "target_mode": self.config.target_mode,
                "optimization_mode": self.config.optimization_mode,
                "n_folds": len(folds),
                "n_trials": len(trial_records),
                "data_hash": _data_hash(data),
                "config_hash": _config_hash(self.config),
                "random_seed": self.config.random_seed,
                "numba_enabled": bool(self.config.use_numba and _NUMBA_AVAILABLE),
                **self.config.metadata,
            },
        )

    def optimize_params(
        self,
        data,
        folds: Sequence[WalkForwardFold],
        param_ranges: Dict[str, Any],
    ) -> tuple[WalkForwardTrialRecord, List[WalkForwardTrialRecord]]:
        """Run Optuna optimization and return the selected trial plus ledger."""
        if not param_ranges:
            raise ValueError(f"{self.config.optimization_mode} optimization requires param_ranges")
        try:
            import optuna
        except ImportError as exc:  # pragma: no cover - environment guard
            raise ImportError("WalkForwardEngine optimization requires optuna") from exc

        records: List[WalkForwardTrialRecord] = []
        seen_params = set()

        def objective(trial):
            params = _sample_params(trial, param_ranges)
            params_key = tuple(sorted(params.items()))
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
                record = self.evaluate_params(data=data, folds=folds, params=params, trial_id=trial.number)
            records.append(record)
            trial.set_user_attr("fold_metrics", record.fold_metrics)
            trial.set_user_attr("params", record.params)
            trial.set_user_attr("mean_is_sharpe", record.mean_is_sharpe)
            trial.set_user_attr("mean_oos_sharpe", record.mean_oos_sharpe)
            trial.set_user_attr("mean_decay", record.mean_decay)
            trial.set_user_attr("std_decay", record.std_decay)
            return record.objective

        sampler = optuna.samplers.TPESampler(seed=int(self.config.random_seed))
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
        if self.config.optimization_mode == "mode_3_flat_minima":
            best = select_flat_minima_record(records, param_ranges, config=self.config)
            if best.selection_metadata.get("requires_evaluation"):
                evaluated = self.evaluate_params(data=data, folds=folds, params=best.params, trial_id=-1)
                best = _with_selection_metadata(
                    evaluated,
                    {
                        **best.selection_metadata,
                        "evaluated_after_selection": True,
                    },
                )
                records.append(best)
        else:
            best_params = dict(study.best_params)
            best = next((record for record in records if record.params == best_params), None)
            if best is None:
                if self.config.optimization_mode == "mode_2_sbb":
                    best = self.evaluate_params_sbb(data=data, folds=folds, params=best_params, trial_id=study.best_trial.number)
                else:
                    best = self.evaluate_params(data=data, folds=folds, params=best_params, trial_id=study.best_trial.number)
                records.append(best)
        return best, records

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
            )
            oos_output = self._call_strategy_for_indices(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.test_index,
                fold=fold,
            )
            is_metrics = score_strategy_output(data, is_output, fold.train_index)
            oos_metrics = score_strategy_output(data, oos_output, fold.test_index)
            d = is_metrics["sharpe"] - oos_metrics["sharpe"]
            is_scores.append(is_metrics["sharpe"])
            oos_scores.append(oos_metrics["sharpe"])
            decay.append(d)
            fold_metrics.append(
                {
                    "fold_id": fold.fold_id,
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "is_sharpe": is_metrics["sharpe"],
                    "oos_sharpe": oos_metrics["sharpe"],
                    "decay": d,
                    "is_turnover": is_metrics["turnover"],
                    "oos_turnover": oos_metrics["turnover"],
                }
            )

        mean_oos = float(np.mean(oos_scores)) if oos_scores else 0.0
        mean_is = float(np.mean(is_scores)) if is_scores else 0.0
        mean_decay = float(np.mean(decay)) if decay else 0.0
        std_decay = float(np.std(decay, ddof=1)) if len(decay) > 1 else 0.0
        objective = (
            mean_oos
            - float(self.config.decay_lambda) * std_decay
            - float(self.config.decay_gamma) * max(0.0, mean_decay)
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
        Score params with stationary block bootstrap synthetic OOS robustness.

        The strategy is evaluated on each train fold, then its train return
        proxy is resampled with seeded stationary block bootstrap. The selected
        objective rewards high synthetic Sharpe and penalizes estimated decay
        from original IS Sharpe to synthetic Sharpe.
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
            )
            is_metrics = score_strategy_output(
                data,
                is_output,
                fold.train_index,
                use_numba=self.config.use_numba,
            )
            returns = strategy_return_series(data, is_output, fold.train_index).to_numpy(dtype=np.float64)
            seed = int(self.config.random_seed) + int(trial_id) * 100_003 + int(fold.fold_id) * 9_176
            boot = stationary_bootstrap_sharpes(
                returns=returns,
                n_samples=int(self.config.sbb_samples),
                block_length=int(self.config.sbb_block_length),
                seed=seed,
                use_numba=bool(self.config.use_numba),
            )
            synthetic_mean = float(np.mean(boot)) if len(boot) else 0.0
            synthetic_std = float(np.std(boot, ddof=1)) if len(boot) > 1 else 0.0
            d = float(is_metrics["sharpe"] - synthetic_mean)
            fold_objective = (
                synthetic_mean
                - float(self.config.sbb_decay_lambda) * max(0.0, d)
                - float(self.config.sbb_std_penalty) * synthetic_std
            )
            is_scores.append(is_metrics["sharpe"])
            synthetic_scores.append(synthetic_mean)
            synthetic_stds.append(synthetic_std)
            decay.append(d)
            fold_metrics.append(
                {
                    "fold_id": fold.fold_id,
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "is_sharpe": is_metrics["sharpe"],
                    "synthetic_oos_sharpe": synthetic_mean,
                    "synthetic_oos_std": synthetic_std,
                    "decay": d,
                    "sbb_objective": float(fold_objective),
                    "sbb_samples": int(self.config.sbb_samples),
                    "sbb_block_length": int(self.config.sbb_block_length),
                    "is_turnover": is_metrics["turnover"],
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
                "objective_mode": "mode_2_sbb",
                "sbb_samples": int(self.config.sbb_samples),
                "sbb_block_length": int(self.config.sbb_block_length),
            },
        )

    def build_folds(self, idx: pd.DatetimeIndex) -> List[WalkForwardFold]:
        """Return chronological train/OOS folds without lookahead."""
        idx = validate_datetime(idx)
        if len(idx) == 0:
            raise ValueError("walk-forward datetime index is empty")

        first_oos = _first_oos_timestamp(self.config.split_mode)
        if first_oos <= idx[0]:
            raise ValueError("first OOS timestamp must be after the first data timestamp")
        if first_oos > idx[-1]:
            raise ValueError("first OOS timestamp is after the available data")

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
    ) -> StrategyOutput:
        strategy = self.strategy() if isinstance(self.strategy, type) else self.strategy
        if hasattr(strategy, "build_signal"):
            return strategy.build_signal(
                data=data,
                params=params,
                train_index=train_index,
                test_index=test_index,
                fold=fold,
            )
        if hasattr(strategy, "generate_signal"):
            return strategy.generate_signal(
                data=data,
                params=params,
                train_index=train_index,
                test_index=test_index,
                fold=fold,
            )
        if callable(strategy):
            return strategy(
                data=data,
                params=params,
                train_index=train_index,
                test_index=test_index,
                fold=fold,
            )
        raise TypeError("strategy must be callable or expose build_signal/generate_signal")


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
        mean, sd, sharpe, turnover = _score_returns_positions_numba(returns_arr, pos_arr, float(trading_days))
    else:
        mean, sd, sharpe, turnover = _score_returns_positions_python(returns_arr, pos_arr, float(trading_days))
    return {
        "sharpe": float(sharpe),
        "turnover": float(turnover),
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
    """Return the transparent shifted-position return proxy used by WFO scoring."""
    idx = validate_datetime(index)
    if len(idx) == 0:
        return pd.Series(dtype=float, index=idx)
    close_map = _close_map_from_data(data)
    if isinstance(output, pd.DataFrame):
        symbols = list(output.columns)
        pos = _normalize_frame_output(output, symbols).reindex(idx).fillna(0.0)
        returns = pd.DataFrame({s: close_map[s].reindex(idx).pct_change().fillna(0.0) for s in symbols})
        strat_returns = (pos.shift(1).fillna(0.0) * returns).mean(axis=1)
    elif isinstance(output, dict):
        symbols = list(output.keys())
        pos = pd.DataFrame({s: _normalize_series_output(output[s]).reindex(idx).fillna(0.0) for s in symbols})
        returns = pd.DataFrame({s: close_map[s].reindex(idx).pct_change().fillna(0.0) for s in symbols})
        strat_returns = (pos.shift(1).fillna(0.0) * returns).mean(axis=1)
    else:
        series = _normalize_series_output(output).reindex(idx).fillna(0.0)
        close = next(iter(close_map.values())).reindex(idx)
        strat_returns = series.shift(1).fillna(0.0) * close.pct_change().fillna(0.0)
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


def _score_returns_positions_python(
    returns: np.ndarray,
    positions: np.ndarray,
    trading_days: float,
) -> Tuple[float, float, float, float]:
    returns = np.asarray(returns, dtype=np.float64)
    positions = np.asarray(positions, dtype=np.float64)
    if returns.size == 0:
        return 0.0, 0.0, 0.0, 0.0
    mean = float(np.mean(returns))
    sd = float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0
    sharpe = (mean / sd) * float(np.sqrt(trading_days)) if sd > 0.0 else 0.0
    turnover = 0.0
    if positions.ndim == 1:
        positions = positions.reshape((-1, 1))
    if positions.shape[0] > 1:
        turnover = float(np.abs(np.diff(positions, axis=0)).sum())
    return mean, sd, sharpe, turnover


def _bootstrap_sharpes_python(returns: np.ndarray, indices: np.ndarray, trading_days: float) -> np.ndarray:
    out = np.empty(indices.shape[0], dtype=np.float64)
    for i in range(indices.shape[0]):
        sample = returns[indices[i]]
        mean = float(np.mean(sample))
        sd = float(np.std(sample, ddof=1)) if sample.size > 1 else 0.0
        out[i] = (mean / sd) * float(np.sqrt(trading_days)) if sd > 0.0 else 0.0
    return out


if _NUMBA_AVAILABLE:

    @njit(cache=True)
    def _score_returns_positions_numba(returns, positions, trading_days):  # pragma: no cover - compared via tests
        n = returns.shape[0]
        if n == 0:
            return 0.0, 0.0, 0.0, 0.0
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
        if positions.shape[0] > 1:
            for i in range(1, positions.shape[0]):
                for j in range(positions.shape[1]):
                    diff = positions[i, j] - positions[i - 1, j]
                    turnover += abs(diff)
        return mean, sd, sharpe, turnover

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

else:

    def _score_returns_positions_numba(returns, positions, trading_days):  # pragma: no cover - fallback alias
        return _score_returns_positions_python(returns, positions, trading_days)

    def _bootstrap_sharpes_numba(returns, indices, trading_days):  # pragma: no cover - fallback alias
        return _bootstrap_sharpes_python(returns, indices, trading_days)


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
    params: Dict[str, Any] = {}
    for name, spec in param_ranges.items():
        if isinstance(spec, tuple) and len(spec) in (2, 3) and all(_is_number(x) for x in spec):
            low = spec[0]
            high = spec[1]
            step = spec[2] if len(spec) == 3 else None
            if _looks_int(low) and _looks_int(high) and (step is None or _looks_int(step)):
                params[name] = trial.suggest_int(name, int(low), int(high), step=1 if step is None else int(step))
            else:
                if step is None:
                    params[name] = trial.suggest_float(name, float(low), float(high))
                else:
                    params[name] = trial.suggest_float(name, float(low), float(high), step=float(step))
        elif isinstance(spec, list):
            if not spec:
                raise ValueError(f"param_ranges[{name!r}] is empty")
            params[name] = trial.suggest_categorical(name, spec)
        elif isinstance(spec, tuple):
            if not spec:
                raise ValueError(f"param_ranges[{name!r}] is empty")
            params[name] = trial.suggest_categorical(name, list(spec))
        else:
            params[name] = spec
    return params


def _looks_int(value: Any) -> bool:
    return isinstance(value, (int, np.integer)) or (isinstance(value, float) and float(value).is_integer())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating))


def _trial_table(records: Sequence[WalkForwardTrialRecord]) -> pd.DataFrame:
    return pd.DataFrame([_trial_to_dict(record, include_fold_metrics=False) for record in records])


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
        "optuna_trials": config.optuna_trials,
        "optuna_early_stopping": config.optuna_early_stopping,
        "random_seed": config.random_seed,
        "decay_lambda": config.decay_lambda,
        "decay_gamma": config.decay_gamma,
        "sbb_samples": config.sbb_samples,
        "sbb_block_length": config.sbb_block_length,
        "sbb_decay_lambda": config.sbb_decay_lambda,
        "sbb_std_penalty": config.sbb_std_penalty,
        "flat_top_fraction": config.flat_top_fraction,
        "flat_eps": config.flat_eps,
        "flat_min_samples": config.flat_min_samples,
        "flat_selector": config.flat_selector,
        "use_numba": config.use_numba,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
