"""Cold, calendar-preserving views for full-development diagnostic accounts."""

from dataclasses import dataclass

import numpy as np

from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_diagnostics.evidence import FrozenBuffer
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.statistics.analysis import partition_pnl
from quantbt.mode5.statistics.moments import moments
from quantbt.mode5.statistics.tails import expected_shortfall
from tools.mode5_environments.labels import FeatureTape, fit_partition

HOUR = 3_600_000_000_000
DAY = 24 * HOUR


@dataclass(frozen=True)
class DailyObservations:
    times: FrozenBuffer
    pnl: FrozenBuffer
    returns: FrozenBuffer
    valid_returns: FrozenBuffer
    equity_before: FrozenBuffer
    equity_after: FrozenBuffer
    exposed_bars: FrozenBuffer
    fees: FrozenBuffer | None

    @classmethod
    def from_account(cls, arrays, *, initial_capital):
        times = np.asarray(arrays["times_ns"])
        equity, positions = np.asarray(arrays["equity"]), np.asarray(arrays["positions"])
        if (times.ndim != 1 or times.dtype.kind not in "iu" or not len(times)
                or times[0] % DAY or (times[-1] + HOUR) % DAY or len(times) % 24
                or np.any(np.diff(times) != HOUR) or equity.shape != times.shape
                or positions.shape != times.shape or not np.isfinite(equity).all()
                or not np.isfinite(positions).all()):
            raise ValueError("complete hourly account and aligned finite marks required")
        ends = np.arange(23, len(times), 24)
        parts = partition_pnl(equity, initial_equity=initial_capital,
            block_ends=tuple(int(i) for i in ends))
        valid = np.array([p["simple_return"] is not None for p in parts])
        returns = np.array([p["simple_return"] if p["simple_return"] is not None else 0. for p in parts])
        fields = dict(times=times[::24], pnl=np.array([p["money_pnl"] for p in parts]),
            returns=returns, valid_returns=valid,
            equity_before=np.array([p["pre_block_equity"] for p in parts]),
            equity_after=equity[ends], exposed_bars=(positions != 0).reshape(-1, 24).sum(axis=1))
        fees = arrays.get("fees")
        if fees is not None:
            fees = np.asarray(fees)
            if fees.shape != times.shape or not np.isfinite(fees).all():
                raise ValueError("available fees must align with actual account")
            fees = FrozenBuffer.from_array("fees", fees.reshape(-1, 24).sum(axis=1))
        return cls(**{k: FrozenBuffer.from_array(k, v) for k, v in fields.items()}, fees=fees)

    def attribute(self, labels):
        labels = np.asarray(labels)
        if labels.shape != self.times.array().shape or labels.dtype.kind not in "iu" or np.any(labels < -1):
            raise ValueError("one state per UTC account day, -1 explicitly unknown")
        pnl, returns, valid, exposure = (getattr(self, k).array()
            for k in ("pnl", "returns", "valid_returns", "exposed_bars"))
        rows = []
        for state in np.unique(labels):
            mask = labels == state
            r = returns[mask]
            stats = moments(r) if valid[mask].all() else None
            es = expected_shortfall(-r, .95) if valid[mask].all() else None
            steps = np.flatnonzero(mask)
            episodes = int(np.count_nonzero(np.r_[True, np.diff(steps) > 1]))
            rows.append(dict(state=int(state), days=int(mask.sum()), episodes=episodes,
                pnl=float(pnl[mask].sum()), exposed_bars=int(exposure[mask].sum()),
                fees=None if self.fees is None else float(self.fees.array()[mask].sum()),
                conditional_period_sharpe=None if stats is None else stats.sharpe_period,
                daily_loss_es=None if es is None else es.value,
                tail_mass_days=.05 * int(mask.sum()),
                top_positive_day_pnl=float(max(0., np.max(pnl[mask]))),
                top_negative_day_pnl=float(min(0., np.min(pnl[mask]))),
                return_status="BANKRUPT" if stats is None else stats.status,
                annualized_sharpe=None,
                status="UNKNOWN" if state == -1 else "NO_CLOSE_MARK_EXPOSURE" if not exposure[mask].any() else "OBSERVED",
                estimand="conditional actual daily account marks; no reset or price splice"))
        whole = float(pnl.sum())
        return dict(rows=rows, whole_pnl=whole, grouped_pnl=float(sum(row["pnl"] for row in rows)),
            conservation_residual=float(sum(row["pnl"] for row in rows) - whole),
            whole_days=len(labels), overlapping_families_independent=False)


def feature_partitions(times_ns, close, volume, *, window=168, cutoff_ns,
                       purpose, fit_start_ns, fit_stop_ns, quantiles=(.25, .75)):
    """Reuse frozen provider rights; features at bar open use prior closed bars."""
    import pandas as pd

    times = np.asarray(times_ns, dtype=np.int64)
    close, volume = np.asarray(close, dtype=float), np.asarray(volume, dtype=float)
    if (len(times) < window + 2 or close.shape != times.shape or volume.shape != times.shape
            or np.any(np.diff(times) != HOUR) or np.any(close <= 0)
            or not np.isfinite(close).all() or not np.isfinite(volume).all()
            or type(window) is not int or window < 2 or purpose not in
            {"decision_vintage", "asof_calibration_descriptive"}
            or fit_start_ns >= fit_stop_ns or fit_stop_ns > cutoff_ns):
        raise ValueError("aligned market, declared past-feature window and fit interval required")
    prices, activity = pd.Series(close), pd.Series(volume)
    values = dict(
        volatility=np.log(prices).diff().rolling(window).std(ddof=1).shift(1).to_numpy(),
        trend=prices.pct_change(window, fill_method=None).shift(1).to_numpy(),
        activity=activity.rolling(window).mean().shift(1).to_numpy())
    result = {}
    for name, raw in values.items():
        valid = np.isfinite(raw)
        provider = digest(dict(feature=name, window=window, clock="UTC_HOURLY_BAR_OPEN",
            availability="previous closed bars", version="m5114_market_features_v1"))
        tape = FeatureTape.from_arrays(provider, times, raw, times,
            np.where(valid, 0, 3).astype(np.int8))
        manifest = digest(dict(provider=provider, fit_start=fit_start_ns, fit_stop=fit_stop_ns))
        witness = AccessWitness(manifest, "diagnostic_development", fit_start_ns, fit_stop_ns, fit_stop_ns)
        policy = AccessPolicy("m5114-feature-fit", (witness.role,), (manifest,), cutoff_ns, "diagnostic")
        snapshot = fit_partition(tape, witness, policy,
            namespace="m5114/" + purpose + "/" + name, quantiles=quantiles)
        labels = snapshot.label(tape, purpose=purpose)
        result[name] = dict(labels=labels.labels.array(), valid=labels.valid.array(),
            label_identity=labels.identity, fit_identity=snapshot.identity,
            provider_identity=provider, feature_window=window, fit_start_ns=fit_start_ns,
            fit_stop_ns=fit_stop_ns, cutoff_ns=cutoff_ns, purpose=purpose,
            thresholds=list(snapshot.thresholds), mean=snapshot.mean, scale=snapshot.scale,
            fit_count=snapshot.count,
            availability="prior closed OHLCV; available at current bar open")
    return result


def finite_panel_environment_comparison(candidate_ids, environment_ids, utilities, *, tolerance=.05):
    """Common-panel ranks/overlap/regret and retrospective leave-out selection."""
    from scipy.stats import rankdata

    x = np.asarray(utilities, dtype=float)
    if (x.shape != (len(candidate_ids), len(environment_ids)) or len(candidate_ids) < 2
            or len(environment_ids) < 2
            or len(set(candidate_ids)) != len(candidate_ids) or len(set(environment_ids)) != len(environment_ids)
            or not np.isfinite(tolerance) or tolerance < 0):
        raise ValueError("distinct fixed panel identities and registered tolerance required")
    pairs = []
    for a, left in enumerate(environment_ids):
        for b, right in enumerate(environment_ids):
            mask = np.isfinite(x[:, a]) & np.isfinite(x[:, b])
            l, r = x[mask, a], x[mask, b]
            if len(l) < 2 or np.ptp(l) == 0 or np.ptp(r) == 0:
                correlation = None
            else:
                correlation = float(np.corrcoef(rankdata(l), rankdata(r))[0, 1])
            ids = np.asarray(candidate_ids)[mask]
            lt = set(ids[l >= l.max() - tolerance]) if len(l) else set()
            rt = set(ids[r >= r.max() - tolerance]) if len(r) else set()
            pairs.append(dict(left=left, right=right, common_candidates=int(mask.sum()),
                spearman=correlation, near_optimal_intersection=sorted(lt & rt),
                near_optimal_jaccard=len(lt & rt)/len(lt | rt) if lt | rt else None,
                tolerance=tolerance, eligibility="finite outcomes only; no annual positivity filter"))
    leave_out = []
    for omitted, name in enumerate(environment_ids):
        keep = [i for i in range(len(environment_ids)) if i != omitted]
        valid = np.isfinite(x[:, keep]).all(axis=1)
        ids = np.flatnonzero(valid)
        if len(ids) and keep:
            index = min(ids, key=lambda i: (-float(x[i, keep].min()), candidate_ids[i]))
            value = float(x[index, omitted]) if np.isfinite(x[index, omitted]) else None
            leave_out.append(dict(omitted=name, candidate_id=candidate_ids[index], held_utility=value,
                kept_floor=float(x[index, keep].min()),
                held_quality_used_for_selection=False,
                claim="retrospective fixed-panel leave-out; not chronological forecasting"))
        else:
            leave_out.append(dict(omitted=name, candidate_id=None, held_utility=None,
                status="NO_FINITE_KEPT_POOL"))
    regret = []
    for i, candidate_id in enumerate(candidate_ids):
        observations = []
        for j, environment_id in enumerate(environment_ids):
            finite = np.isfinite(x[:, j])
            benchmark = float(x[finite, j].max()) if finite.any() else None
            available = bool(np.isfinite(x[i, j])) and benchmark is not None
            observations.append(dict(environment=environment_id,
                finite_panel_benchmark=benchmark,
                finite_candidates=int(finite.sum()),
                regret=float(benchmark-x[i, j]) if available else None,
                status="OBSERVED" if available else "MISSING_OUTCOME"))
        complete = all(r["regret"] is not None for r in observations)
        regret.append(dict(candidate_id=candidate_id, environments=observations,
            max_regret=max(r["regret"] for r in observations) if complete else None,
            complete=complete, benchmark_scope="registered finite panel, not global optimum"))
    return dict(pairs=pairs, leave_out=leave_out, regret=regret,
        independent_oos=False, sampler_advantage=False, whole_path_from_year_mean=False)
