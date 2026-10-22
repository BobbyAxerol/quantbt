"""Prepared, reset-flat diagnostics for exogenous decision-time intrabar tapes.

The parent owns prefix feature/intent compilation and the financial schedule.
This sidecar executes one original account, then observes it twice: the current
public raw metric (daily preferred, first day excluded) and the floor selector's
daily account returns (first day measured against initial capital). Neither is
an alternate account engine or a continuous WFO assembly implementation.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, fields
from time import perf_counter
from typing import Any, Mapping

import numpy as np
import pandas as pd

from quantbt import (
    AccountConfig, ExecutionContract, InstrumentSpec, IntrabarIntentTape,
    IntrabarLevelMode, IntrabarSessionTape, QuantBTEndpoint, SessionExecutionPolicy,
)
from quantbt.core.constraints import build_quantity_constraints
from quantbt.core.results import BacktestResultV2
from quantbt.endpoint import PreparedIntrabarRunner
from quantbt.metrics.report_contracts import ReportingContractV1
from quantbt.metrics.reporting.inputs import derived_returns
from quantbt.optimization.meta_selection.common import digest, freeze, frozen_array
from quantbt.optimization.meta_selection.observer import (
    ResultMetricAdapter, canonical_metric_contract, economics_identity,
)
from quantbt.optimization.meta_selection.records import MetricObservation
from quantbt.optimization.meta_selection.witness import PreparedMetricWitness

from .contracts import DailyAccountReturn


FIRST_ACTION_CONVENTION = "reset_flat_first_scored_close_then_next_open_v1"
_DAY = pd.Timedelta(days=1)


@dataclass(frozen=True)
class IntrabarEvaluation:
    original_result: BacktestResultV2
    meta_observation: MetricObservation
    daily_returns: tuple[DailyAccountReturn, ...]
    params: Mapping[str, Any]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class _PreparedWindow:
    runner: PreparedIntrabarRunner
    input_signature: str
    economics_id: str
    days: tuple[tuple[pd.Timestamp, int, int, bool], ...]


class IntrabarEvaluationContext:
    """Run-owned immutable market/calendar/header reuse, never account reuse.

    ``evaluate(full_intent, index, params, is_window=True)`` accepts an unshifted
    IntrabarIntentTape aligned to the first N rows of this context's market.
    N may be the permitted prefix or the full length; it must cover ``index``.
    The exact contiguous market subset is sliced, with NO prior decision row.
    There is no pending intent/position on its first scored bar. Its first
    close can act only at the next scored open, as in WfoExecutionWindow.
    The final close flattens; a final-bar decision has no activation in-window.

    ``params`` is provenance only, not an endpoint override or compiler input.
    ``is_window`` requires 365 UTC days, with a full first/last day envelope.
    Missing/partial days are unavailable, not forward-filled floor returns.
    The market uses the public endpoint's close timestamp semantics, with each
    UTC date labelling that date's scored bars. Default cadence is one hour.

    Sequential owner only: use a separate context per worker. Handles are LRU
    bounded, all executions are fresh accounts, results belong to the caller.
    Close (or use ``with``) to release prepared/native and witness references.
    Explicit Rust only: unavailable/incompatible extensions fail, not fallback.
    """

    def __init__(self, data: pd.DataFrame, *, symbol: str,
                 instrument: InstrumentSpec | None = None,
                 bar_interval: pd.Timedelta = pd.Timedelta(hours=1),
                 max_windows: int = 8):
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data must be an OHLCV DataFrame")
        index = self._calendar(data.index)
        interval = pd.Timedelta(bar_interval)
        if (pd.isna(interval) or interval <= pd.Timedelta(0)
                or _DAY.value % interval.value or np.any(index.asi8 % interval.value)):
            raise ValueError("bar_interval must divide a UTC day and align every bar")
        if type(max_windows) is not int or max_windows < 1:
            raise ValueError("max_windows must be a positive integer")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol is required")
        if instrument is not None and instrument.symbol != symbol:
            raise ValueError("instrument must match symbol")
        self._instrument = deepcopy(instrument or InstrumentSpec(symbol))
        columns = ["open", "high", "low", "close", "volume"]
        if not data.columns.is_unique or not set(columns).issubset(data.columns):
            raise ValueError("unique lowercase OHLCV columns required")
        # Bytes-backed arrays detach caller storage and cannot regain writeability.
        self._data = pd.DataFrame({c: frozen_array(data[c].to_numpy()) for c in columns},
                                  index=index, copy=False)
        self._symbol, self._interval = symbol, interval
        self._max_windows = max_windows
        self._windows: OrderedDict[tuple[int, int, str], _PreparedWindow] = OrderedDict()
        self._adapter = ResultMetricAdapter(canonical_metric_contract(trading_days=365))
        self._witness = PreparedMetricWitness(self._data, config=self._endpoint().config)
        self._closed = False
        self._preparations = self._hits = self._executions = 0

    @staticmethod
    def _calendar(index):
        if (not isinstance(index, pd.DatetimeIndex) or not len(index)
                or index.tz is None or index.hasnans or not index.is_unique
                or not index.is_monotonic_increasing):
            raise ValueError("nonempty, aware, unique chronological DatetimeIndex required")
        return pd.DatetimeIndex(pd.array(frozen_array(index.as_unit("ns").asi8,
            dtype=np.int64), dtype="datetime64[ns, UTC]", copy=False))

    def _endpoint(self, level_mode=IntrabarLevelMode.PERCENT_DISTANCE):
        return QuantBTEndpoint.intrabar_bracket_rust(
            account=AccountConfig(initial_capital=20_000., leverage=1., maintenance_ratio=.005),
            symbols=[self._symbol], instruments=[deepcopy(self._instrument)],
            contract_size=self._instrument.contract_size, alloc_per_trade=2_000.,
            intrabar_sizing_mode="fixed_notional", level_mode=level_mode,
            fee_rate=.0004, slippage_bps=0., use_funding=False, funding_rate=0.,
            execution_contract=ExecutionContract.intrabar_bracket(close_on_last_bar=True),
            session_policy=SessionExecutionPolicy(entry_position_policy="flat_only",
                                                 cancel_pending_on_session_change=False),
            report_level="minimal")

    def _prepare(self, start, stop, level_mode):
        key = start, stop, level_mode.value
        if key in self._windows:
            self._hits += 1
            self._windows.move_to_end(key)
            return self._windows[key], True
        index = self._data.index[start:stop]
        n = len(index)
        endpoint = self._endpoint(level_mode)
        # A single session, no quotas and no forced daily reset/flattening.
        session = IntrabarSessionTape(np.zeros(n, np.int64), np.ones(n, bool), np.zeros(n, bool))
        runner = endpoint.prepare_intrabar(data=self._data.iloc[start:stop], session_tape=session)
        days = []
        for day in pd.date_range(index[0].normalize(), index[-1].normalize(), freq="D"):
            a, b = int(index.searchsorted(day)), int(index.searchsorted(day + _DAY))
            complete = b - a == _DAY // self._interval
            days.append((day, a, b, complete))
        prepared = _PreparedWindow(runner,
            self._witness.market_signature(self._data, index),
            economics_identity(endpoint.config, symbols=[self._symbol]), tuple(days))
        if len(self._windows) >= self._max_windows:
            self._release(self._windows.popitem(last=False)[1])
        self._windows[key] = prepared
        self._preparations += 1
        return prepared, False

    @staticmethod
    def _release(window):
        cache = window.runner.rust_prepared_market.cache
        cache.clear()

    def _daily(self, result, window):
        rows = []
        index, equity = result.equity.index, result.equity.to_numpy(dtype=float)
        liquidation_day = (index[result.liquidation_bar].normalize()
                           if result.liquidated else None)
        previous_complete = True
        for number, (day, a, b, complete) in enumerate(window.days):
            status, reason, value = "VALID", None, None
            baseline = result.initial_capital if number == 0 else (equity[a - 1] if a else np.nan)
            if liquidation_day is not None and day >= liquidation_day:
                status, reason = "BANKRUPT", "account liquidated; no selector support from this day"
            elif not complete or not previous_complete:
                status, reason = "UNAVAILABLE", "incomplete UTC day or preceding daily valuation"
            elif not np.isfinite(equity[a:b]).all() or not np.isfinite(baseline):
                status, reason = "INVALID", "nonfinite account valuation"
            elif baseline <= 0 or equity[b - 1] <= 0:
                status, reason = "BANKRUPT", "nonpositive account valuation"
            else:
                contract = ReportingContractV1(scope="scoped", unit="account_period",
                    currency=window.runner.endpoint.config.account.base_currency,
                    baseline_equity=float(baseline), baseline_time_ns=day.value,
                    scope_end_ns=index[b - 1].value, sampling="observed_daily_utc",
                    annual_periods=365., equity_clock="daily_close")
                observed = derived_returns(index[b - 1:b].asi8, equity[b - 1:b], contract,
                    partial_mask=np.zeros(1, bool), witness=FIRST_ACTION_CONVENTION)
                value = float(observed.values[0])
            rows.append(DailyAccountReturn(day, value, status, reason))
            previous_complete = complete
        return tuple(rows)

    def evaluate(self, full_intent: IntrabarIntentTape, index: pd.DatetimeIndex,
                 params: Mapping[str, Any], *, is_window: bool = False,
                 report_level: str = "minimal") -> IntrabarEvaluation:
        if self._closed:
            raise RuntimeError("IntrabarEvaluationContext is closed")
        if not isinstance(full_intent, IntrabarIntentTape):
            raise TypeError("precomputed full-prefix IntrabarIntentTape required")
        if not isinstance(params, Mapping):
            raise TypeError("params must be a mapping, separate from the intent tape")
        if report_level not in {"minimal", "standard", "audit"}:
            raise ValueError("report_level must be minimal, standard or audit")
        params = freeze(params)
        index = self._calendar(index)
        start = int(self._data.index.searchsorted(index[0]))
        stop = start + len(index)
        if not self._data.index[start:stop].equals(index):
            raise ValueError("index must be an exact contiguous subset of the owned market calendar")
        if is_window and (index[0] != index[0].normalize()
                or index[-1] + self._interval != index[0] + pd.Timedelta(days=365)):
            raise ValueError("IS must span exactly 365 complete UTC days")
        if not stop <= len(full_intent.entry_side) <= len(self._data):
            raise ValueError("full-prefix tape must cover the window and align to the market origin")
        started = perf_counter()
        arrays = {f.name: (None if getattr(full_intent, f.name) is None else
                          frozen_array(getattr(full_intent, f.name)[start:stop],
                                       dtype=np.asarray(getattr(full_intent, f.name)).dtype))
                  for f in fields(full_intent) if f.name != "level_mode"}
        intent = IntrabarIntentTape(**arrays, level_mode=IntrabarLevelMode(full_intent.level_mode))
        window, hit = self._prepare(start, stop, intent.level_mode)
        prepared_at = perf_counter()
        self._executions += 1
        try:
            result = window.runner.run(intent, report_level=report_level)
        finally:
            # Public runners retain their last result/kernel for convenience.
            # Do not turn that convenience into candidate-account cache state.
            window.runner.endpoint.result = None
            window.runner.endpoint.engine = None
        executed_at = perf_counter()
        if result.metadata.get("rust_intrabar_authority") is not True:
            raise RuntimeError("explicit native intrabar authority was not reported")
        # The public runner shallow-copies this reporting profile. Detach its
        # nested dictionaries so a returned audit cannot mutate the next one.
        result.metadata["profile_metadata"] = deepcopy(result.metadata["profile_metadata"])
        # Match the public WFO helper's canonical constraints representation.
        result.metadata["quantity_constraints"] = build_quantity_constraints(
            [self._symbol], instruments=[self._instrument]).as_dict()
        observation = self._adapter.observe(result, expected_index=index,
            economics_id=window.economics_id, input_signature=window.input_signature,
            prepared_witness=self._witness)
        daily = self._daily(result, window)
        metadata = dict(schema="m51161.prepared-intrabar-evaluation.v1",
            first_action_convention=FIRST_ACTION_CONVENTION,
            prior_intent_injected=False, diagnostic_account="reset_flat",
            continuous_wfo_claim=False, intent_shift_bars=0, engine_activation="next_open",
            raw_metric_policy=self._adapter.contract.sample_policy,
            floor_daily_policy="utc_complete_days_initial_capital_first_day_v1",
            raw_and_floor_same_physical_account=True, physical_account_runs=1,
            window_start=index[0], window_end=index[-1], scored_bars=len(index),
            params_id=digest(params), window_cache_hit=hit,
            intent_slice_bytes=sum(a.nbytes for a in arrays.values() if a is not None),
            boundary_calls=result.metadata.get("boundary_calls"),
            python_callbacks=result.metadata.get("python_callbacks"),
            source_market_bytes=result.metadata.get("source_market_bytes"),
            boundary_transferred_bytes=None,
            boundary_bytes_limitation="public runner exposes market storage, not exact wire bytes",
            native_preparation=window.runner.rust_prepared_market.cache.diagnostics,
            preparation_seconds=prepared_at - started,
            execution_seconds=executed_at - prepared_at,
            reduction_seconds=perf_counter() - executed_at)
        return IntrabarEvaluation(result, observation, daily, params, freeze(metadata))

    @property
    def metadata(self):
        return dict(closed=self._closed, prepared_windows=len(self._windows),
            preparations=self._preparations, window_hits=self._hits,
            physical_account_attempts=self._executions, witness=self._witness.metadata)

    def close(self):
        for window in self._windows.values():
            self._release(window)
        self._windows.clear()
        self._witness.close()
        self._data = None
        self._closed = True

    def __enter__(self):
        if self._closed:
            raise RuntimeError("IntrabarEvaluationContext is closed")
        return self

    def __exit__(self, *_):
        self.close()
