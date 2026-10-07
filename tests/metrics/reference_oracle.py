"""Small, slow independent specification oracle; never imported by production.

No QuantBT/NumPy/QuantStats reducer supplies expected values. This observes
recorded marks and already-attributed outcomes; it does not match/replay fills.
"""

from datetime import datetime, timezone
import math
from statistics import median


DAY_NS = 86_400_000_000_000


def utc_ns(text):
    date = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("explicit timezone required")
    delta = date.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000


def validate_path(times, equity, baseline, baseline_time):
    if len(times) != len(equity) or not times:
        raise ValueError("nonempty aligned path required")
    if type(baseline_time) is not int or any(type(t) is not int for t in times):
        raise ValueError("UTC nanosecond integers required")
    if times[0] < baseline_time or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("ordered path at/after baseline required")
    if not math.isfinite(baseline) or baseline <= 0 or any(not math.isfinite(e) for e in equity):
        raise ValueError("finite marks and positive baseline required")


def account_growth(times, equity, baseline, baseline_time, *, year_days=365.25,
                   minimum_days=1., cashflows=()):
    validate_path(times, equity, baseline, baseline_time)
    if any(cashflows):
        raise NotImplementedError("external cashflow valuation contract missing")
    growth = equity[-1] / baseline
    days = (times[-1] - baseline_time) / DAY_NS
    cagr = None
    if growth > 0 and days >= minimum_days and days > 0:
        try:
            cagr = math.expm1(math.log(growth) / (days / year_days))
        except OverflowError:
            pass
    return {"total_return": growth - 1, "cagr_elapsed": cagr, "elapsed_days": days}


def drawdown_episodes(times, equity, baseline, baseline_time, *, recovery_tolerance=0.):
    validate_path(times, equity, baseline, baseline_time)
    if not 0 <= recovery_tolerance < 1:
        raise ValueError("invalid recovery tolerance")
    peak, peak_time = baseline, baseline_time
    episodes, depths, episode = [], [], None

    def finish(end_time, recovered):
        episode["end_time_ns"] = end_time
        episode["recovery_time_ns"] = end_time if recovered else None
        episode["recovered"] = recovered
        episode["elapsed_ns"] = end_time - episode["peak_time_ns"]
        days = episode.pop("underwater_dates")
        episode["observed_underwater_days"] = len(days)
        episode["inclusive_underwater_calendar_days"] = max(days) - min(days) + 1
        episodes.append(episode.copy())

    for timestamp, mark in zip(times, equity):
        peak = max(peak, mark)
        depth = 1 - mark / peak
        depths.append(depth)
        recovered = mark >= peak * (1 - recovery_tolerance)
        if recovered:
            if episode is not None:
                finish(timestamp, True)
                episode = None
            if mark >= peak:
                peak_time = timestamp
            continue
        if episode is None:
            episode = dict(peak_time_ns=peak_time, peak_equity=peak,
                           first_underwater_time_ns=timestamp, trough_time_ns=timestamp,
                           trough_equity=mark, depth=depth, observed_underwater_marks=0,
                           underwater_dates=set())
        episode["last_underwater_time_ns"] = timestamp
        episode["observed_underwater_marks"] += 1
        episode["underwater_dates"].add(timestamp // DAY_NS)
        if depth > episode["depth"]:
            episode.update(depth=depth, trough_time_ns=timestamp, trough_equity=mark)
    if episode is not None:
        finish(times[-1], False)
    positive = [d for d in depths if d > 0]
    recovered = [e for e in episodes if e["recovered"]]
    deepest = max(episodes, key=lambda e: e["depth"], default=None)
    longest = max(episodes, key=lambda e: e["elapsed_ns"], default=None)
    return dict(
        depths=depths, episodes=episodes, max_depth=max(depths),
        deepest=deepest, longest=longest,
        mean_underwater_depth=sum(positive) / len(positive) if positive else None,
        mean_episode_depth=sum(e["depth"] for e in episodes) / len(episodes) if episodes else None,
        mean_recovered_duration_ns=sum(e["elapsed_ns"] for e in recovered) / len(recovered) if recovered else None,
        longest_recovered_duration_ns=max((e["elapsed_ns"] for e in recovered), default=0),
        current_open_duration_ns=episodes[-1]["elapsed_ns"] if episodes and not episodes[-1]["recovered"] else 0,
        ulcer_index=math.sqrt(sum(d * d for d in depths) / len(depths)),
    )


def period_statistics(returns, *, annual_periods=1., ddof=1, rf=0., mar=0.,
                      omega_threshold=0., conditional_downside=False):
    r = list(returns)
    if not r or any(not math.isfinite(x) for x in r):
        raise ValueError("explicit finite nonempty return sample required")
    if ddof not in (0, 1) or annual_periods <= 0:
        raise ValueError("invalid variance/annualization")
    n, mean = len(r), sum(r) / len(r)
    gains = [x for x in r if x > 0]
    losses = [x for x in r if x < 0]

    def ratio(g, loss):
        return g / loss if loss else math.inf if g > 0 else None

    variance = sum((x - mean) ** 2 for x in r) / (n - ddof) if n > ddof else 0.
    sharpe = (mean - rf) / math.sqrt(variance) * math.sqrt(annual_periods) if variance else None
    downside = [x - mar for x in r if x < mar]
    denominator = len(downside) if conditional_downside else n
    rms = math.sqrt(sum(x * x for x in downside) / denominator) if denominator else 0.
    sortino = ratio(mean - mar, rms) * math.sqrt(annual_periods) if rms or mean > mar else None
    geometric = math.expm1(sum(math.log1p(x) for x in r) / n) if all(x > -1 for x in r) else None
    omega_g = sum(max(x - omega_threshold, 0) for x in r)
    omega_l = sum(max(omega_threshold - x, 0) for x in r)
    growth = math.prod(1 + x for x in r)
    return dict(
        count=n, mean_arithmetic=mean, mean_geometric=geometric, sharpe=sharpe,
        sortino=sortino, omega=ratio(omega_g, omega_l), profit_factor=ratio(sum(gains), -sum(losses)),
        avg_win=sum(gains) / len(gains) if gains else None,
        avg_loss=sum(losses) / len(losses) if losses else None,
        win_rate=len(gains) / n,
        nonzero_win_rate=len(gains) / (len(gains) + len(losses)) if gains or losses else None,
        cagr_period_count=math.expm1(math.log(growth) * annual_periods / n) if growth > 0 and all(x > -1 for x in r) else None,
    )


def recorded_net_pnl(record, *, slippage_basis="included_in_fill_price"):
    if "net_pnl" in record:
        value = record["net_pnl"]
    else:
        required = {"gross_pnl", "allocated_fee", "allocated_funding_cost"}
        if not required.issubset(record):
            raise ValueError("complete recorded cost allocation required")
        value = record["gross_pnl"] - record["allocated_fee"] - record["allocated_funding_cost"]
        if slippage_basis == "recorded_separate_cost":
            if "allocated_slippage_cost" not in record:
                raise ValueError("separate slippage allocation missing")
            value -= record["allocated_slippage_cost"]
        elif slippage_basis != "included_in_fill_price":
            raise ValueError("unknown slippage policy")
    if not math.isfinite(value):
        raise ValueError("nonfinite recorded PnL")
    return value


def closed_outcomes(records, *, currency, unit="closed_trade", complete=True,
                    scope=None, tolerance=0.):
    if not complete:
        return {"status": "unavailable", "closed_count": None, "reason": "ledger incomplete"}
    if unit not in {"closed_trade", "closed_action"} or tolerance < 0:
        raise ValueError("invalid population")
    if len({r["trade_id"] for r in records}) != len(records):
        raise ValueError("duplicate closed-outcome identity")
    if any(r["currency"] != currency for r in records):
        raise ValueError("recorded currency conversion required")
    population = []
    if unit == "closed_action":
        grouped = {}
        for row in records:
            if not row.get("action_id"):
                raise ValueError("authoritative action identity required")
            grouped.setdefault(row["action_id"], []).append(row)
        for rows in grouped.values():
            if all(r["closed_at_ns"] is not None for r in rows):
                final = max(rows, key=lambda r: (r["closed_at_ns"], r["close_sequence"]))
                population.append((final["closed_at_ns"], final["close_sequence"], sum(recorded_net_pnl(r) for r in rows)))
    else:
        population = [(r["closed_at_ns"], r["close_sequence"], recorded_net_pnl(r)) for r in records if r["closed_at_ns"] is not None]
    if scope is not None:
        population = [p for p in population if scope[0] <= p[0] <= scope[1]]
    population.sort(key=lambda p: (p[0], p[1]))
    values = [p[2] for p in population]
    n = len(values)
    wins, losses = [x for x in values if x > tolerance], [x for x in values if x < -tolerance]
    g, loss = sum(max(x, 0) for x in values), sum(max(-x, 0) for x in values)
    streaks, streak, previous = {1: 0, -1: 0}, 0, 0
    for x in values:
        side = 1 if x > tolerance else -1 if x < -tolerance else 0
        streak = streak + 1 if side and side == previous else 1 if side else 0
        if side:
            streaks[side] = max(streaks[side], streak)
        previous = side
    return dict(
        status="valid" if n else "unavailable", closed_count=n, values=values,
        win_count=len(wins), loss_count=len(losses), breakeven_count=n - len(wins) - len(losses),
        win_rate=len(wins) / n if n else None, net_pnl=sum(values),
        avg_profit=sum(wins) / len(wins) if wins else None,
        avg_loss=sum(losses) / len(losses) if losses else None,
        payoff_ratio=(sum(wins) / len(wins)) / (-sum(losses) / len(losses)) if wins and losses else None,
        avg_pnl=sum(values) / n if n else None,
        expected_payoff=sum(values) / n if n else None,
        profit_factor=g / loss if loss else math.inf if g else None,
        largest_win=max(wins) if wins else None, largest_loss=min(losses) if losses else None,
        median_pnl=median(values) if values else None,
        top_profit_concentration=max(wins) / g if wins and g else None,
        max_win_streak=streaks[1], max_loss_streak=streaks[-1],
    )
