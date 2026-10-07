"""Observed-equity episode reduction, not an intrabar extrema reconstruction."""

from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np


DAY_NS = 86_400_000_000_000
INT_COLUMNS = ("peak_time_ns", "first_underwater_time_ns", "last_underwater_time_ns",
               "trough_time_ns", "end_time_ns", "elapsed_ns", "observed_underwater_marks",
               "observed_underwater_days", "inclusive_underwater_calendar_days", "recovered")
FLOAT_COLUMNS = ("peak_equity", "trough_equity", "depth")


@dataclass(frozen=True)
class DrawdownEpisodes:
    integers: np.ndarray
    numbers: np.ndarray

    @property
    def retained_bytes(self):
        return self.integers.nbytes + self.numbers.nbytes

    def to_rows(self):
        rows = []
        for integers, numbers in zip(self.integers, self.numbers):
            row = dict(zip(INT_COLUMNS, map(int, integers)))
            row.update(zip(FLOAT_COLUMNS, map(float, numbers)))
            row["recovered"] = bool(row["recovered"])
            row["recovery_time_ns"] = row["end_time_ns"] if row["recovered"] else None
            rows.append(row)
        return rows


def _scan(times, equity, baseline, start, tolerance, detail):
    n = len(equity)
    integers = np.empty((n // 2 + 1 if detail else 0, 10), np.int64)
    numbers = np.empty((n // 2 + 1 if detail else 0, 3), np.float64)
    peak, peak_time = baseline, start
    active = False
    ep_peak, ep_peak_time, first, last, trough_time, trough, ep_depth = baseline, start, start, start, start, baseline, 0.
    marks, days, last_day = 0, 0, 0
    count, recovered_count, positive_count = 0, 0, 0
    max_depth, sum_positive, sum_squared, sum_episode, sum_recovered = 0., 0., 0., 0., 0.
    longest, longest_recovered, current, deepest_duration = 0, 0, 0, 0
    sum_durations = 0.
    deepest_index, longest_index = -1, -1
    deepest_depth = -1.
    for i in range(n):
        timestamp, mark = times[i], equity[i]
        peak = max(peak, mark)
        depth = 1. - mark / peak
        max_depth = max(max_depth, depth)
        sum_squared += depth * depth
        if depth > 0.:
            sum_positive += depth
            positive_count += 1
        recovered = mark >= peak * (1. - tolerance)
        if not recovered:
            if not active:
                active = True
                ep_peak, ep_peak_time, first = peak, peak_time, timestamp
                trough_time, trough, ep_depth = timestamp, mark, depth
                marks, days, last_day = 0, 0, timestamp // DAY_NS - 1
            last = timestamp
            marks += 1
            day = timestamp // DAY_NS
            if day != last_day:
                days += 1
                last_day = day
            if depth > ep_depth:
                trough_time, trough, ep_depth = timestamp, mark, depth
        if active and (recovered or i == n - 1):
            elapsed = timestamp - ep_peak_time
            if detail:
                integers[count] = (ep_peak_time, first, last, trough_time, timestamp, elapsed,
                                   marks, days, last // DAY_NS - first // DAY_NS + 1, int(recovered))
                numbers[count] = (ep_peak, trough, ep_depth)
            sum_episode += ep_depth
            sum_durations += elapsed
            if ep_depth > deepest_depth:
                deepest_depth, deepest_index = ep_depth, count
                deepest_duration = elapsed
            if longest_index < 0 or elapsed > longest:
                longest, longest_index = elapsed, count
            if recovered:
                recovered_count += 1
                sum_recovered += elapsed
                longest_recovered = max(longest_recovered, elapsed)
            else:
                current = elapsed
            count += 1
            active = False
        if recovered and mark >= peak:
            peak_time = timestamp
    summary = np.array((max_depth, sum_positive / positive_count if positive_count else np.nan,
                        sum_episode / count if count else np.nan,
                        sum_recovered / recovered_count if recovered_count else np.nan,
                        float(longest_recovered), float(current), math.sqrt(sum_squared / n),
                        float(longest), float(count), float(recovered_count),
                        float(deepest_index), float(longest_index), float(deepest_duration),
                        sum_durations / count if count else np.nan, depth, float(positive_count)))
    return summary, integers[:count if detail else 0], numbers[:count if detail else 0]


@lru_cache(maxsize=1)
def _compiled():
    from numba import njit
    return njit(cache=False, fastmath=False)(_scan)


def scan_drawdown(observations, contract, *, backend="python", retain_episodes=False):
    observations.validate_contract(contract)
    if backend not in {"python", "numba"}:
        raise NotImplementedError("only Python/Numba reporting V1 are certified; native V2 is not V1")
    kernel = _scan if backend == "python" else _compiled()
    summary, integers, numbers = kernel(observations.times_ns, observations.equity,
        contract.baseline_equity, contract.baseline_time_ns, contract.recovery_relative_tolerance, retain_episodes)
    episodes = None
    if retain_episodes:
        integers = np.frombuffer(integers.tobytes(), np.int64).reshape(-1, 10)
        numbers = np.frombuffer(numbers.tobytes(), np.float64).reshape(-1, 3)
        episodes = DrawdownEpisodes(integers, numbers)
    return summary, episodes
