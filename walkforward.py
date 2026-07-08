"""
quantbt.walkforward
-------------------
Phase 1 WalkForwardEngine foundation.

This module intentionally stays orchestration-focused. It builds time-safe
folds, calls a strategy adapter, stitches OOS signals/positions, and leaves the
final market simulation to existing QuantBT endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd

from .core.preprocessor import validate_datetime


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


@dataclass
class WalkForwardResult:
    """Phase 1 walk-forward artifact returned before/after final backtest."""

    folds: List[WalkForwardFold]
    oos_output: Optional[StrategyOutput]
    fold_table: pd.DataFrame
    params: Dict[str, Any]
    backtest_result: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def oos_positions(self) -> Optional[StrategyOutput]:
        """Alias for `oos_output` used by portfolio-style callers."""
        return self.oos_output


class WalkForwardEngine:
    """
    Time-safe walk-forward splitter and OOS stitcher.

    Phase 1 does not optimize parameters. It receives fixed `params`, or derives
    a deterministic default from `param_ranges`, then produces stitched OOS
    output. The endpoint layer can pass that output into the correct QuantBT
    backtest route.
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
        chosen_params = dict(params or _default_params_from_ranges(param_ranges or {}))
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
            metadata={
                "engine": "walk_forward_phase1",
                "split_mode": str(self.config.split_mode),
                "split_frequency": self.config.split_frequency,
                "window_mode": self.config.window_mode,
                "target_mode": self.config.target_mode,
                "n_folds": len(folds),
                **self.config.metadata,
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
        strategy = self.strategy() if isinstance(self.strategy, type) else self.strategy
        if hasattr(strategy, "build_signal"):
            return strategy.build_signal(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.test_index,
                fold=fold,
            )
        if hasattr(strategy, "generate_signal"):
            return strategy.generate_signal(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.test_index,
                fold=fold,
            )
        if callable(strategy):
            return strategy(
                data=data,
                params=params,
                train_index=fold.train_index,
                test_index=fold.test_index,
                fold=fold,
            )
        raise TypeError("strategy must be callable or expose build_signal/generate_signal")


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
