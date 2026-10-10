"""Historical diagnostic views, not an account engine or selection policy."""

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class YearView:
    year: int
    start_ns: int
    stop_ns: int
    bars: int
    days: int
    complete_year: bool
    baseline_equity: float
    equity: tuple[float, ...]
    account_mode: str = "CONTINUOUS_ACCOUNT_VIEW"


def continuous_year_views(times_ns, equity, *, initial_capital):
    """Partition actual marks; retain the preceding mark, never reset inventory."""
    raw_times = np.asarray(times_ns)
    if raw_times.dtype.kind not in "iu" or raw_times.dtype.itemsize > 8:
        raise ValueError("exact integer nanosecond timestamps required")
    if raw_times.dtype.kind == "u" and np.any(raw_times > np.iinfo(np.int64).max):
        raise ValueError("nanosecond timestamps must fit signed int64 without wrapping")
    times = np.asarray(raw_times, dtype=np.int64)
    marks = np.asarray(equity, dtype=np.float64)
    hour = 3_600_000_000_000
    if (times.ndim != 1 or len(times) == 0 or marks.shape != times.shape
            or not np.isfinite(marks).all() or not math.isfinite(initial_capital)
            or initial_capital <= 0 or (times % hour).any()
            or (np.diff(times) != hour).any()):
        raise ValueError("finite complete, aligned contiguous hourly observations required")
    index = pd.to_datetime(times, utc=True)
    if index[0].hour != 0 or index[-1].hour != 23:
        raise ValueError("complete UTC days required")
    outputs = []
    for year in sorted(set(index.year)):
        rows = np.flatnonzero(index.year == year)
        first, last = int(rows[0]), int(rows[-1])
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        stop = pd.Timestamp(f"{year+1}-01-01", tz="UTC")
        full = times[first] == start.value and times[last]+hour == stop.value
        outputs.append(YearView(int(year), int(times[first]), int(times[last])+hour,
            len(rows), len(rows)//24, bool(full),
            float(initial_capital if first == 0 else marks[first-1]),
            tuple(float(v) for v in marks[rows])))
    return tuple(outputs)


def eligibility_breakdown(total_return, drawdown, daily_es, *, daily_count,
                          minimum_days=91, maximum_drawdown=.5):
    """Explain the existing equal-weight mandate without relaxing its gate."""
    if (type(daily_count) is not int or daily_count < 0 or type(minimum_days) is not int
            or minimum_days <= 0 or not math.isfinite(maximum_drawdown)
            or not 0 <= maximum_drawdown <= 1):
        raise ValueError("explicit support/risk contract required")
    defined = all(v is not None and math.isfinite(v) for v in (total_return, drawdown, daily_es))
    if defined and drawdown < 0:
        raise ValueError("drawdown uses positive fractional depth, not a signed loss")
    utility = total_return-drawdown-daily_es if defined else None
    return dict(net_return=total_return, drawdown_cost=drawdown, daily_tail_cost=daily_es,
        utility=utility, defined=defined, profitable=bool(defined and total_return > 0),
        risk_pass=bool(defined and drawdown <= maximum_drawdown),
        quality_pass=bool(defined and utility > 0), support_pass=daily_count >= minimum_days,
        reason=("UNDEFINED" if not defined else "QUALITY_FAIL" if utility <= 0
                else "RISK_FAIL" if drawdown > maximum_drawdown else
                "SUPPORT_FAIL" if daily_count < minimum_days else "ELIGIBLE"))
