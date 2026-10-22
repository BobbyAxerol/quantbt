"""Registered public software workloads; no private alpha or economic tuning."""

from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from collections.abc import Mapping
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.persistence import (
    dumps_revision,
    loads_revision,
)
from tests.meta_selection import pre_e06_02_support as ordinary
from tests.meta_selection import pre_e06_03_support as nested
from tools import qms01_baseline as legacy

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "d0cd95a"
PREPARED = ("signal_notional", "notional", "unit", "pct_equity")


@dataclass(frozen=True)
class Cell:
    group: str
    route: str
    mode: str = "off"
    optimization: str = "mode_4_is_only_robust"
    schedule: str = "per_fold_causal"
    prepared: bool = False
    conditional: bool = False

    @property
    def identity(self):
        return "-".join(str(v).lower() for v in asdict(self).values())


def cells():
    result = [
        Cell("legacy", "signal_notional", optimization=m, schedule=s)
        for m, s in legacy.ROUTES
    ]
    result += [
        Cell("domain", r, m)
        for r in ordinary.ROUTES
        for m in ("off", "shadow", "active")
    ]
    result += [
        Cell("prepared", r, m, prepared=True)
        for r in PREPARED
        for m in ("off", "shadow", "active")
    ]
    result += [
        Cell("nested", r, m, optimization="mode_1_decay")
        for r in nested.ROUTES
        for m in ("off", "shadow", "active")
    ]
    result += [
        Cell("conditional", "pct_equity", conditional=True),
        Cell(
            "conditional",
            "pct_equity",
            optimization="mode_5_full_robust",
            schedule="global",
            conditional=True,
        ),
    ]
    return tuple(result)


def history_path(lane, cell):
    return (
        lane
        / "history"
        / (
            ("nested" if cell.group == "nested" else "domain")
            + "-"
            + cell.route
            + ".json"
        )
    )


def export_history(lane, *, group, route):
    helper = nested if group == "nested" else ordinary
    path = lane / "history" / (group + "-" + route + ".json")
    if path.exists():
        raise ValueError("refuse to overwrite frozen history")
    value = helper.run(route, data=ordinary.tape(route, end="2022-05-31"))
    revisions = tuple(value.context.history._revisions.values())
    payload = dict(
        schema="pre05-frozen-history-v1",
        route=route,
        group=group,
        revisions=[
            dict(revision_id=r.revision_id, json=dumps_revision(r)) for r in revisions
        ],
        original_output_witnesses={
            o.output_ref: digest(o)
            for r in revisions
            for o in (
                *(c.observation for c in r.task.candidates),
                *(o.observation for o in r.outcomes),
            )
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    return dict(
        route=route,
        group=group,
        revisions=len(revisions),
        bytes=path.stat().st_size,
        sha256=sha256(path.read_bytes()).hexdigest(),
    )


def load_history(path):
    payload = json.loads(path.read_text())
    history = MetaHistory()
    for row in payload["revisions"]:
        history.append(
            loads_revision(
                row["json"],
                reviewed_revision_ids=(row["revision_id"],),
                verified_output_witnesses=payload["original_output_witnesses"],
            )
        )
    return history


def prepare(cell, lane, *, frozen_history=None):
    if cell.group == "legacy":
        return (
            legacy.endpoint(cell.optimization, cell.schedule),
            legacy.market(),
            None,
            {"window": (3, 31, 2)},
        )
    data = ordinary.current(ordinary.tape(cell.route), ordinary.CUTOFFS[0])
    helper = nested if cell.group == "nested" else ordinary
    bt = helper.endpoint(
        cell.route,
        data,
        cell.mode,
        start="2022-05-01",
        prepared=cell.prepared,
        numeric="require",
    )
    ctx = None
    if cell.mode != "off":
        h = (
            load_history(history_path(lane, cell))
            if frozen_history is None
            else ordinary.clone_history(frozen_history)
        )
        ctx = MetaHistoryContext(
            h,
            "pre-e06-public-synthetic",
            "pre-e06-" + cell.route,
            "1D",
            "pre-e06-software-v1",
            clock=ordinary.replay_clock,
        )
    if cell.conditional:
        from quantbt.optimization import SamplerConfig

        wf = replace(
            bt.config.walkforward_config,
            optimization_mode=cell.optimization,
            optimization_schedule=cell.schedule,
            sampler_config=SamplerConfig(
                name="sobol", sobol_policy="conditional_numeric_latent_v1"
            ),
            flat_selector="feasible_support_projection_v1",
            candidate_selection_metric="full_plateau_robust"
            if cell.optimization == "mode_5_full_robust"
            else "is_only_robust",
        )
        bt = QuantBTEndpoint(replace(bt.config, walkforward_config=wf))
        ranges = {
            "window": (3, 9, 2),
            "use_filter": [True, False],
            "filter_length": {
                "kind": "integer",
                "low": 3,
                "high": 9,
                "step": 2,
                "active_if": {"use_filter": [True]},
            },
        }
    else:
        ranges = ordinary.RANGES
    return bt, data, ctx, ranges


def execute(prepared, cell):
    bt, data, ctx, ranges = prepared
    kwargs = dict(param_ranges=ranges)
    if cell.route != "reactive_reset":
        kwargs["data"] = data
    if ctx is not None:
        kwargs["meta_history"] = ctx
    try:
        return bt.backtest(**kwargs)
    finally:
        if cell.route == "reactive_reset":
            bt.close()


def metadata(result, cell):
    return (
        result.metadata
        if cell.route == "reactive_reset"
        else result.metadata["walk_forward"]
    )


def audit_value(value):
    """Lossless report shape, labels and values, with explicit nonfinite tokens."""
    if isinstance(value, Enum):
        return audit_value(value.value)
    if is_dataclass(value):
        return {f.name: audit_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, pd.DataFrame):
        return dict(
            index=legacy.safe(value.index.tolist()),
            columns=legacy.safe(value.columns.tolist()),
            dtypes=[str(d) for d in value.dtypes],
            values=legacy.safe(value.to_numpy()),
        )
    if isinstance(value, Mapping):
        return {str(k): audit_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [audit_value(v) for v in value]
    return legacy.safe(value)


def semantic(result, cell, context):
    """Exact logical work/measurement/account; physical generation clocks excluded."""
    wf = metadata(result, cell)
    meta = wf.get("meta_selection", {})
    if cell.mode != "off":
        if not meta.get("models") or any(
            r["matured_origins"] < 12 for r in meta["records"]
        ):
            raise ValueError(
                "matched enabled workload did not actually fit mature history"
            )
        if meta["observer_failures"]:
            raise ValueError("observer failure cannot be cost/economic evidence")
    arrays = []
    accounts = (
        [f.result for f in result.fold_results]
        if cell.route == "reactive_reset"
        else [result]
    )
    for account in accounts:
        arrays.append(
            {
                k: None
                if getattr(account, k, None) is None
                else dict(
                    values=sha256(
                        getattr(account, k).to_numpy(dtype="<f8").tobytes()
                    ).hexdigest(),
                    shape=getattr(account, k).shape,
                    index=[str(t) for t in getattr(account, k).index],
                )
                for k in ("equity", "returns", "positions", "fees", "funding", "margin")
            }
        )
        arrays[-1]["audit"] = audit_value(
            {
                k: getattr(account, k, None)
                for k in (
                    "closes",
                    "symbols",
                    "initial_capital",
                    "leverage",
                    "liquidated",
                    "liquidation_bar",
                    "orders",
                    "fills",
                    "trades",
                    "diagnostics",
                )
            }
        )
        arrays[-1]["reports"] = audit_value(
            {
                k: v
                for k, v in account.metadata.items()
                if k.endswith(("_report", "_ledger"))
            }
        )
        arrays[-1]["metrics"] = audit_value(account.full_report(trading_days=365))
    # These fields are elapsed telemetry, not information/measurement or params.
    elapsed = {
        "auxiliary_outer_is_seconds",
        "observer_seconds",
        "elapsed_seconds",
        "fit_seconds",
        "rank_seconds",
        "search_elapsed_seconds",
        "sampler_wall_seconds",
        "wall_generated_at",
    }

    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k not in elapsed}
        if isinstance(value, (tuple, list)):
            return [stable(v) for v in value]
        return value

    rows = []
    for r in meta.get("records", ()):
        rows.append(
            wire(
                {
                    k: r[k]
                    for k in (
                        "fold_id",
                        "family_id",
                        "training_snapshot_id",
                        "training_revision_ids",
                        "matured_origins",
                        "selected_params",
                        "selected_evaluation_id",
                        "native_selected_evaluation_id",
                        "panel_members",
                        "final_selection_reason",
                    )
                }
            )
        )
        p = r["proposal"]
        rows[-1]["proposal"] = wire(
            {
                k: getattr(p, k)
                for k in (
                    "status",
                    "guard",
                    "proposed_evaluation_id",
                    "proposed_params",
                    "tie_set",
                    "ranked_ids",
                    "predictions",
                )
            }
        )
    trials = result.trial_table if cell.route == "reactive_reset" else wf["trial_table"]
    models = [
        wire(
            {
                k: getattr(m, k)
                for k in ("coefficients", "schema", "scaler", "fit_row_references")
            }
        )
        for m in meta.get("models", {}).values()
    ]
    revisions = {}
    current = {r["observer_revision_id"]: r for r in meta.get("records", ())}
    if context is not None:
        for revision in context.history._revisions.values():
            payload = stable(wire(revision))
            if revision.revision_id in current:
                record = current[revision.revision_id]
                nominal = revision.task.forward_end + pd.Timedelta(
                    seconds=meta["config"]["reporting_lag_seconds"]
                )
                actual = nominal + pd.Timedelta(seconds=record["observer_seconds"])
                assert revision.revision_available_at == actual
                assert all(o.label_available_at == actual for o in revision.outcomes)
                # Only today's physical elapsed clock varies between paired runs.
                # Historical availability remains byte-exact and gates fitting.
                payload["revision_available_at"] = wire(nominal)
                for outcome in payload["outcomes"]:
                    outcome["label_available_at"] = wire(nominal)
            revisions[revision.task.task_id] = payload
    from tools.qms01_baseline import safe

    value = dict(
        accounts=arrays,
        trials=stable(safe(trials)),
        params=result.params_by_fold
        if cell.route == "reactive_reset"
        else wf["params_by_fold"],
        sampler=stable(wf.get("sampler_studies", [])),
        records=rows,
        models=models,
        tasks=stable(wire(meta.get("tasks", ()))),
        revisions=revisions,
        observer_attempts=meta.get("observer_attempts", 0),
    )
    if cell.route == "reactive_reset":
        assert wf["fold_account_policy"] == "reset_flat"
        assert not wf["continuous_equity_available"] and result.oos_output is None
        value["reactive_contract"] = dict(
            fold_table=audit_value(result.fold_table),
            candidate_table=stable(safe(result.candidate_table)),
            best_trial=stable(safe(result.best_trial)),
            fold_accounts=[
                dict(
                    fold_id=f.fold_id,
                    params=dict(f.params),
                    score_metrics=dict(f.score_metrics),
                    task=audit_value(f.task),
                    strategy_state_fingerprint=audit_value(
                        f.strategy_state_fingerprint
                    ),
                )
                for f in result.fold_results
            ],
        )
    value = safe(value)
    return digest(value), value
