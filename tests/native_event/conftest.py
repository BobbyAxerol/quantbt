from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from quantbt import OrderCommand, QuantBTEndpoint


SEED = 20260801


def bars(n: int = 18, *, start: str = "2024-01-01", freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    base = 100.0 + np.sin(np.arange(n, dtype=np.float64) / 3.0) * 3.0 + np.arange(n) * 0.15
    close = pd.Series(base, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 2.5,
            "low": close - 2.5,
            "close": close,
            "volume": 1_000.0 + np.arange(n, dtype=np.float64),
        },
        index=idx,
    )


def multi_bars(n: int = 18) -> Mapping[str, pd.DataFrame]:
    left = bars(n)
    right = bars(n).copy()
    right[["open", "high", "low", "close"]] *= 1.12
    right["volume"] *= 1.5
    return {"BTC": left, "ETH": right}


class ScheduledCommandStrategy:
    def __init__(self, schedule: Mapping[int, Sequence[OrderCommand]]):
        self.schedule = {int(k): tuple(v) for k, v in schedule.items()}
        self.seen = []

    def initialize(self, context):
        self.seen.append(("initialize", context.bar_index, context.timestamp))
        return list(self.schedule.get(-1, ()))

    def on_bar_close(self, context):
        self.seen.append(("on_bar_close", context.bar_index, context.timestamp))
        return list(self.schedule.get(context.bar_index, ()))

    def finalize(self, context):
        self.seen.append(("finalize", context.bar_index, context.timestamp))
        return list(self.schedule.get(10**9, ()))


def run_reactive(mode: str, strategy, data=None, symbols=None, **kwargs):
    data = bars() if data is None else data
    symbols = ["BTC"] if symbols is None else list(symbols)
    datetime_index = kwargs.pop("datetime_index", None)
    if datetime_index is None and isinstance(data, Mapping):
        datetime_index = next(iter(data.values())).index
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=kwargs.pop("initial_capital", 10_000),
        leverage=kwargs.pop("leverage", 10),
        use_funding=kwargs.pop("use_funding", False),
        fee_rate=kwargs.pop("fee_rate", 0.0002),
        report_level=kwargs.pop("report_level", "audit"),
        reactive_execution_mode=kwargs.pop("reactive_execution_mode", "audit"),
        reactive_kernel_mode=mode,
        **kwargs,
    )
    return endpoint.simulate(data=data, strategy=strategy, symbols=symbols, datetime_index=datetime_index)


def assert_accounting_equal(candidate, oracle) -> None:
    pd.testing.assert_series_equal(candidate.equity, oracle.equity, check_names=True)
    pd.testing.assert_series_equal(candidate.returns, oracle.returns, check_names=True)
    pd.testing.assert_frame_equal(candidate.positions, oracle.positions)
    pd.testing.assert_series_equal(candidate.fees, oracle.fees, check_names=True)
    pd.testing.assert_series_equal(candidate.funding, oracle.funding, check_names=True)
    pd.testing.assert_frame_equal(candidate.margin, oracle.margin)
    assert candidate.liquidated == oracle.liquidated
    assert candidate.liquidation_bar == oracle.liquidation_bar


def _stable_value(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if np.isnan(value):
            return "NaN"
        if np.isposinf(value):
            return "Inf"
        if np.isneginf(value):
            return "-Inf"
        return format(value, ".17g")
    if is_dataclass(value):
        return {k: _stable_value(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _stable_value(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_stable_value(v) for v in value]
    return value


def _frame_records(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    ordered = frame.copy()
    if "original_index" in ordered.columns:
        ordered = ordered.sort_values("original_index")
    elif "bar" in ordered.columns:
        ordered = ordered.sort_values(list(c for c in ("bar", "command_index") if c in ordered.columns))
    ordered = ordered.reindex(sorted(ordered.columns), axis=1)
    return [{col: _stable_value(row[col]) for col in ordered.columns} for _, row in ordered.iterrows()]


def _fill_records(fills: Iterable) -> list[dict]:
    records = []
    for fill in fills or ():
        records.append(
            {
                "timestamp": _stable_value(getattr(fill, "timestamp", None)),
                "symbol": getattr(fill, "symbol", None),
                "side": _stable_value(getattr(fill, "side", None)),
                "qty": _stable_value(float(getattr(fill, "qty", 0.0))),
                "price": _stable_value(float(getattr(fill, "price", 0.0))),
                "fee": _stable_value(float(getattr(fill, "fee", 0.0))),
                "order_id": getattr(fill, "order_id", None),
            }
        )
    return records


def native_event_fingerprint(result) -> str:
    h = hashlib.sha256()
    for frame in (result.positions, result.margin):
        arr = np.ascontiguousarray(frame.to_numpy(dtype=np.float64))
        h.update(arr.shape.__repr__().encode())
        h.update(arr.tobytes())
    for series in (result.equity, result.fees, result.funding):
        arr = np.ascontiguousarray(series.to_numpy(dtype=np.float64))
        h.update(arr.shape.__repr__().encode())
        h.update(arr.tobytes())
    payload = {
        "liquidated": bool(result.liquidated),
        "liquidation_bar": int(result.liquidation_bar),
        "fills": _fill_records(getattr(result, "fills", ())),
        "command_report": _frame_records(result.metadata.get("command_report")),
        "order_events": _frame_records(result.metadata.get("order_events")),
        "derived_counts": {
            "fills": len(_fill_records(getattr(result, "fills", ()))),
            "command_report_rows": len(_frame_records(result.metadata.get("command_report"))),
            "order_event_rows": len(_frame_records(result.metadata.get("order_events"))),
        },
    }
    h.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()


def assert_native_event_full_parity(candidate, oracle) -> None:
    assert_accounting_equal(candidate, oracle)
    assert _fill_records(candidate.fills) == _fill_records(oracle.fills)
    pd.testing.assert_frame_equal(
        candidate.metadata.get("command_report", pd.DataFrame()).reset_index(drop=True),
        oracle.metadata.get("command_report", pd.DataFrame()).reset_index(drop=True),
        check_like=True,
    )
    pd.testing.assert_frame_equal(
        candidate.metadata.get("order_events", pd.DataFrame()).reset_index(drop=True),
        oracle.metadata.get("order_events", pd.DataFrame()).reset_index(drop=True),
        check_like=True,
    )
    assert native_event_fingerprint(candidate) == native_event_fingerprint(oracle)
