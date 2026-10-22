"""Whole chronological decision sequences, not just a kernel/last equity."""

from dataclasses import replace

import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import digest, wire
from tests.meta_selection import pre_e06_02_support as original
from tests.meta_selection import pre_e06_03_support as nested
from tools.qms_pre05_reference import baseline_blocks
from tools.qms_pre05_workloads import audit_value


def logical(value):
    records = value.meta["records"]
    current = {r["observer_revision_id"]: r for r in records}
    revisions, aliases = {}, {}
    for revision in value.context.history._revisions.values():
        updated = revision
        if revision.revision_id in current:
            elapsed = current[revision.revision_id]["observer_seconds"]
            nominal = revision.task.forward_end + pd.Timedelta(days=1)
            actual = nominal + pd.Timedelta(seconds=elapsed)
            assert actual == revision.revision_available_at
            assert all(o.label_available_at == actual for o in revision.outcomes)
            updated = replace(
                revision,
                revision_available_at=nominal,
                outcomes=tuple(
                    replace(o, label_available_at=nominal) for o in revision.outcomes
                ),
            )
        updated = replace(
            updated,
            task=replace(
                updated.task, wall_generated_at=pd.Timestamp("2026-10-07", tz="UTC")
            ),
        )
        revisions[revision.task.task_id] = wire(updated)
        aliases[revision.revision_id] = digest(updated)
    for snapshot in value.meta["snapshots"]:
        assert all(
            r.revision_available_at <= snapshot.information_as_of
            for r in snapshot.revisions
        )
        aliases[snapshot.snapshot_id] = digest(
            dict(
                as_of=wire(snapshot.information_as_of),
                family=snapshot.family_id,
                authorized_corpora=snapshot.authorized_corpora,
                origins=snapshot.outcome_origins,
                exposures=snapshot.research_exposures,
                revisions=[revisions[r.task.task_id] for r in snapshot.revisions],
            )
        )

    def normalize(payload):
        if isinstance(payload, str):
            return aliases.get(payload, payload)
        if isinstance(payload, dict):
            return {
                k: normalize(v)
                for k, v in payload.items()
                if k
                not in {
                    "wall_generated_at",
                    "auxiliary_outer_is_seconds",
                    "observer_seconds",
                    "elapsed_seconds",
                    "fit_seconds",
                    "rank_seconds",
                    "search_elapsed_seconds",
                }
            }
        if isinstance(payload, list):
            return [normalize(v) for v in payload]
        return payload

    decisions = []
    for record in records:
        decisions.append(
            {
                k: audit_value(record[k])
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
        proposal = record["proposal"]
        decisions[-1]["proposal"] = wire(
            {
                k: getattr(proposal, k)
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
    result = dict(
        decisions=decisions,
        tasks=wire(value.meta["tasks"]),
        revisions=revisions,
        models=[wire(m) for m in value.meta["models"].values()],
        trials=audit_value(value.result.metadata["walk_forward"]["trial_table"]),
    )
    return normalize(result)


@pytest.mark.parametrize("helper", [original, nested], ids=["mode4", "nested-mode1"])
def test_twelve_folds_preserve_all_decisions_labels_rng_and_account(helper):
    with baseline_blocks():
        initial = helper.run(
            "pct_equity", data=original.tape("pct_equity", end="2022-04-30")
        )
    data = original.tape("pct_equity", end="2023-04-30")
    kwargs = dict(mode="active", data=data, start="2022-05-01", numeric="require")
    with baseline_blocks():
        previous = helper.run(
            "pct_equity",
            history=original.clone_history(initial.context.history),
            **kwargs,
        )
    current = helper.run(
        "pct_equity", history=original.clone_history(initial.context.history), **kwargs
    )
    assert len(previous.meta["records"]) == len(current.meta["records"]) == 12
    assert all(r["matured_origins"] >= 12 for r in current.meta["records"])
    assert previous.meta["observer_failures"] == current.meta["observer_failures"] == 0
    assert logical(previous) == logical(current)
    original.account_equal(previous.result, current.result)
    assert audit_value(previous.result.full_report()) == audit_value(
        current.result.full_report()
    )
    original.account_equal(current.result, original.rebuild_final(current))
    cache = current.meta["witness_reuse"]
    assert cache["entries"] > 0
    assert cache["entries"] <= cache["max_entries"]
    assert cache["retained_bytes"] <= cache["max_bytes"] == 8_000_000
