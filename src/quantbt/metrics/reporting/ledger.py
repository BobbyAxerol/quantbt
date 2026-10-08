"""Net closed-population statistics from authoritative recorded outcomes only."""

import json
from functools import lru_cache

import numpy as np

from .drawdown import DAY_NS
from .results import MetricBuilder, ReportingResult


CORE_KEYS = ("closed_count", "win_count", "loss_count", "breakeven_count", "win_rate", "net_pnl",
             "avg_profit", "avg_loss", "avg_pnl", "expected_payoff", "profit_factor", "payoff_ratio",
             "largest_win", "largest_loss", "median_pnl", "top_profit_concentration", "max_win_streak", "max_loss_streak")
EXTRA_KEYS = ("open_at_observation_end_count", "mean_holding_days", "mean_holding_bars", "mean_return", "mean_r_multiple",
              "mean_mfe_net_pnl", "mean_mae_net_pnl", "allocated_fee", "allocated_funding_cost",
              "allocated_slippage_cost", "open_realized_net_pnl", "open_unrealized_pnl")


def recorded_net(row, slippage_basis):
    if row.net_pnl is not None:
        return row.net_pnl
    if row.gross_pnl is None or row.allocated_fee is None or row.allocated_funding_cost is None:
        raise LookupError("net outcome or complete recorded gross/cost allocation missing")
    value = row.gross_pnl - row.allocated_fee - row.allocated_funding_cost
    if slippage_basis == "recorded_separate_cost":
        if row.allocated_slippage_cost is None:
            raise LookupError("separate slippage allocation missing")
        value -= row.allocated_slippage_cost
    return value


def _streaks(values, tolerance):
    streak, previous, best_win, best_loss = 0, 0, 0, 0
    for value in values:
        side = 1 if value > tolerance else -1 if value < -tolerance else 0
        streak = streak + 1 if side and side == previous else 1 if side else 0
        if side > 0:
            best_win = max(best_win, streak)
        if side < 0:
            best_loss = max(best_loss, streak)
        previous = side
    return best_win, best_loss


@lru_cache(maxsize=1)
def _compiled_streaks():
    from numba import njit
    return njit(cache=False, fastmath=False)(_streaks)


def _statistics(builder, prefix, values, tolerance, backend):
    n = len(values)
    wins, losses = values[values > tolerance], values[values < -tolerance]
    gain = float(np.maximum(values, 0).sum())
    loss = float(-np.minimum(values, 0).sum())
    net = float(values.sum())
    for name, value in (("closed_count", n), ("win_count", len(wins)), ("loss_count", len(losses)),
                        ("breakeven_count", n - len(wins) - len(losses))):
        builder.add(prefix + name, value, unit="count", count=n)
    currency = builder.contract.currency
    builder.add(prefix + "net_pnl", net, unit=currency, count=n)
    builder.add(prefix + "win_rate", len(wins) / n if n else None, count=n)
    builder.add(prefix + "avg_profit", float(wins.mean()) if len(wins) else None, unit=currency, count=len(wins))
    builder.add(prefix + "avg_loss", float(losses.mean()) if len(losses) else None, unit=currency, count=len(losses))
    for name in ("avg_pnl", "expected_payoff"):
        builder.add(prefix + name, net / n if n else None, unit=currency, count=n)
    builder.ratio(prefix + "profit_factor", gain, loss, count=n)
    if len(wins) and len(losses):
        builder.add(prefix + "payoff_ratio", float(wins.mean() / -losses.mean()), count=n)
    else:
        builder.add(prefix + "payoff_ratio", count=n, reason="both winning and losing populations required")
    for name, value, count in (("largest_win", float(wins.max()) if len(wins) else None, len(wins)),
                               ("largest_loss", float(losses.min()) if len(losses) else None, len(losses)),
                               ("median_pnl", float(np.median(values)) if n else None, n)):
        builder.add(prefix + name, value, unit=currency, count=count)
    builder.add(prefix + "top_profit_concentration", float(wins.max()) / gain if len(wins) and gain else None, count=n)
    scan_values = memoryview(values) if backend == "python" else values
    best_win, best_loss = (_streaks if backend == "python" else _compiled_streaks())(scan_values, tolerance)
    builder.add(prefix + "max_win_streak", best_win, unit="count", count=n)
    builder.add(prefix + "max_loss_streak", best_loss, unit="count", count=n)


def reduce_ledger(observations, contract, *, backend="python", retain_population=False):
    if backend not in {"python", "numba"}:
        raise NotImplementedError("only Python/Numba reporting V1 reducers are certified")
    if contract.unit not in {"closed_trade", "closed_action"}:
        raise ValueError("ledger reducer requires a closed-population contract")
    if contract.matching != observations.matching:
        raise ValueError("executed matching witness differs from reporting policy")
    prefix = contract.unit + "."
    builder = MetricBuilder(contract, observations.coverage)
    reason = observations.coverage.reason if observations.coverage.ledger != "complete" else None
    if any(row.currency != contract.currency for row in observations.records):
        reason = "recorded currency conversion required; mixed currencies cannot be summed"
    if contract.ledger_scope != "closed_in_scope_lifetime":
        reason = "in-scope attribution requires recorded scope-entry marks and allocated boundary costs"
    population, selected_rows, adjustments = [], [], 0.
    closed_rows = [row for row in observations.records if row.closed_at_ns is not None]
    if contract.unit == "closed_action" and not reason:
        records = {row.trade_id: row for row in observations.records}
        rosters = {roster.action_id: roster for roster in observations.rosters}
        if observations.records and (not rosters or any(row.action_id not in rosters for row in observations.records)):
            reason = "complete authoritative action roster missing"
        else:
            represented = set()
            for roster in observations.rosters:
                members = [records.get(name) for name in roster.outcome_ids]
                if any(row is None or row.action_id != roster.action_id for row in members):
                    reason = "action roster contains missing or inconsistent obligations"
                    break
                represented.update(roster.outcome_ids)
                if all(row.closed_at_ns is not None for row in members):
                    final = max(members, key=lambda row: (row.closed_at_ns, row.close_sequence))
                    if contract.baseline_time_ns <= final.closed_at_ns <= contract.scope_end_ns:
                        try:
                            value = sum(recorded_net(row, contract.slippage_basis) for row in members) + roster.shared_net_adjustment
                        except LookupError as error:
                            reason = str(error)
                            break
                        population.append((final.closed_at_ns, final.close_sequence, value, members))
                        selected_rows.extend(members)
                        adjustments += roster.shared_net_adjustment
            if represented != set(records) and not reason:
                reason = "authoritative roster does not cover the entire declared outcome population"
    elif not reason:
        for row in closed_rows:
            if contract.baseline_time_ns <= row.closed_at_ns <= contract.scope_end_ns:
                try:
                    value = recorded_net(row, contract.slippage_basis)
                except LookupError as error:
                    reason = str(error)
                    break
                population.append((row.closed_at_ns, row.close_sequence, value, [row]))
                selected_rows.append(row)
    metadata = dict(contract=contract.to_metadata(), executed_matching=observations.matching,
                    costs="authoritative net; embedded slippage never subtracted twice",
                    action_roster_count=len(observations.rosters), backend="numpy/" + backend,
                    raw_records=len(observations.records), population_complete=reason is None,
                    close_order="timestamp_ns then recorded unique close sequence")
    if reason:
        for name in CORE_KEYS + EXTRA_KEYS:
            builder.add(prefix + name, status="unavailable", reason=reason)
        metadata["unavailable_reason"] = reason
    else:
        population.sort(key=lambda row: (row[0], row[1]))
        values = np.ascontiguousarray([item[2] for item in population], dtype=np.float64)
        _statistics(builder, prefix, values, contract.breakeven_currency_tolerance, backend)
        n = len(population)
        holdings = []
        for timestamp, sequence, value, members in population:
            if len(members) == 1:
                opened = members[0].opened_at_ns
                if opened is not None:
                    holdings.append((timestamp - opened) / DAY_NS)
            elif all(row.opened_at_ns is not None for row in members):
                holdings.append((timestamp - min(row.opened_at_ns for row in members)) / DAY_NS)
        builder.add(prefix + "mean_holding_days", sum(holdings) / n if n and len(holdings) == n else None,
                    unit="elapsed_days", count=n, status=None if n and len(holdings) == n else "unavailable",
                    reason=None if n and len(holdings) == n else "recorded opening/closure boundaries missing or empty population")
        # Multi-leg bars, excursions and risk denominators are not additive.
        extras = {"mean_holding_bars": "holding_bars", "mean_return": "return_denominator",
                  "mean_r_multiple": "initial_risk", "mean_mfe_net_pnl": "mfe_net_pnl", "mean_mae_net_pnl": "mae_net_pnl"}
        for name, field in extras.items():
            available = contract.unit == "closed_trade" and n and all(getattr(row, field) is not None for row in selected_rows)
            if name in {"mean_mfe_net_pnl", "mean_mae_net_pnl"}:
                available = available and all(row.excursion_witness for row in selected_rows)
            if available:
                if field in {"initial_risk", "return_denominator"}:
                    number = sum(recorded_net(row, contract.slippage_basis) / getattr(row, field) for row in selected_rows) / n
                else:
                    number = sum(getattr(row, field) for row in selected_rows) / n
                builder.add(prefix + name, number, unit="bars" if field == "holding_bars" else contract.currency if "net_pnl" in name else "ratio", count=n)
            else:
                builder.add(prefix + name, status="unavailable", reason="recorded per-population marks/risk/denominator coverage required", count=n)
        for field in ("allocated_fee", "allocated_funding_cost", "allocated_slippage_cost"):
            available = all(getattr(row, field) is not None for row in selected_rows)
            builder.add(prefix + field, sum(getattr(row, field) for row in selected_rows) if available else None,
                        unit=contract.currency, count=len(selected_rows), status=None if available else "unavailable",
                        reason=None if available else "recorded cost allocation missing")
        open_rows = [row for row in observations.records if row.closed_at_ns is None]
        open_observed = observations.valuation_time_ns == contract.scope_end_ns
        open_count = len(open_rows) if contract.unit == "closed_trade" else len({row.action_id for row in open_rows})
        builder.add(prefix + "open_at_observation_end_count", open_count if open_observed else None,
                    unit="count", count=len(observations.records), status=None if open_observed else "unavailable",
                    reason=None if open_observed else "matched observation-end roster witness missing")
        open_realized = open_unrealized = None
        open_adjustment = 0.
        if open_observed and contract.scope == "full":
            realized_rows = open_rows
            if contract.unit == "closed_action":
                # An unfinished action retains realized PnL from its closed legs.
                open_ids = {row.action_id for row in open_rows}
                realized_rows = [row for row in observations.records if row.action_id in open_ids]
                open_adjustment = sum(roster.shared_net_adjustment for roster in observations.rosters
                                      if roster.action_id in open_ids)
            try:
                open_realized = sum(recorded_net(row, contract.slippage_basis) for row in realized_rows) + open_adjustment
            except LookupError:
                pass
            if all(row.open_unrealized_pnl is not None for row in open_rows):
                open_unrealized = sum(row.open_unrealized_pnl for row in open_rows)
        for name, value in (("open_realized_net_pnl", open_realized), ("open_unrealized_pnl", open_unrealized)):
            builder.add(prefix + name, value, unit=contract.currency, count=open_count,
                        status=None if value is not None else "unavailable",
                        reason=None if value is not None else "matched scope-end valuation and complete recorded allocation required")
        symbol_pnl = {}
        for row in selected_rows:
            symbol_pnl[row.symbol] = symbol_pnl.get(row.symbol, 0.) + recorded_net(row, contract.slippage_basis)
        if retain_population:
            metadata["closed_population_ids"] = [[row.trade_id for row in item[3]] for item in population]
        metadata.update(population_detail_retained=retain_population,
                        open_realized_basis="open outcomes, or all members of unfinished actions, plus recorded shared adjustment once",
                        open_shared_net_adjustment=open_adjustment,
                        symbol_closed_pnl=symbol_pnl, shared_net_adjustment=adjustments,
                        leg_net_sum=sum(symbol_pnl.values()), population_net_sum=float(values.sum()),
                        reconciliation_basis="selected closed-population lifetime only; not scope account return",
                        population_reason_counts={reason: sum(row.close_reason == reason for row in selected_rows)
                                                  for reason in sorted({row.close_reason for row in selected_rows if row.close_reason is not None})})
    return ReportingResult(contract_identity=builder.contract_identity, input_identity=observations.identity,
                           metrics=tuple(builder.metrics), provenance_json=json.dumps(metadata, sort_keys=True, allow_nan=False))
