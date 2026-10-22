"""Verify original search ledgers to supplement prefix coverage metadata."""

from collections import Counter

from .admission import BASE, ROOTS, READBACK_SHA256, pin, read_verified
from .protocol import GROUPS


def search_inventory():
    readback = read_verified(
        BASE / "four-alpha-closeout-v1/readback.json", expected_sha256=READBACK_SHA256
    )
    allowed = {p["path"]: p for p in readback["input_pins"]}
    groups, inputs = {}, []
    for group in GROUPS:
        rows = []
        for fold in range(57):
            directory = ROOTS[group] / f"folds/{fold:02d}"
            refs = [allowed[str((directory / "search.json.gz").resolve())]]
            if any(pin(r["path"]) != r for r in refs):
                raise ValueError("original search ledger pin changed")
            inputs += refs
            search = read_verified(
                refs[0]["path"],
                expected_sha256=refs[0]["sha256"],
                expected_bytes=refs[0]["bytes"],
            )
            sampler = search["sampler"]
            attempts = sampler["rows"]
            trials = {r["trial_id"]: r for r in search["trials"]}
            states = Counter(a["state"] for a in attempts)
            if (
                len(attempts) != 128
                or len({a["trial_id"] for a in attempts}) != 128
                or len(trials) != 128
                or any(
                    a["trial_id"] not in trials
                    or trials[a["trial_id"]]["pruned"] != (a["state"] == "PRUNED")
                    for a in attempts
                )
                or dict(states) != sampler["states"]
                or sampler["recipe"] not in {"tpe", "tpe_legacy"}
                or sampler["kwargs"].get("multivariate", False)
                or sampler["kwargs"].get("group", False)
                or search["current_oos_used_for_search"] is not False
            ):
                raise ValueError("attempt/pool sampling identity differs")
            rows.append(
                dict(
                    fold=fold,
                    attempted=128,
                    states=dict(states),
                    unique_effective=sampler["unique_effective_candidates"],
                    duplicate_attempts=sampler["duplicate_attempts"],
                    feasible_complete=sampler["feasible_complete"],
                    relative_proposals=sampler["relative_proposal_trials"],
                    selected_native_selector=search["native"]["selection_metadata"].get(
                        "selector"
                    ),
                    native_reason=search["native"]["selection_metadata"].get("reason"),
                    sampler_wall_seconds=sampler["sampler_wall_seconds"],
                    source_refs=[
                        dict(bytes=r["bytes"], sha256=r["sha256"]) for r in refs
                    ],
                    authority="sealed original search trial and sampler rows; not inferred from eligible pool size",
                )
            )
        groups[group] = dict(
            rows=rows,
            attempted=sum(r["attempted"] for r in rows),
            states=dict(sum((Counter(r["states"]) for r in rows), Counter())),
            native_selector_counts=dict(
                Counter(r["selected_native_selector"] for r in rows)
            ),
            duplicate_attempts=sum(r["duplicate_attempts"] for r in rows),
            min_unique=min(r["unique_effective"] for r in rows),
            max_unique=max(r["unique_effective"] for r in rows),
            sampler_wall_seconds=sum(r["sampler_wall_seconds"] for r in rows),
        )
    return dict(
        schema="m4.ml06.search-inventory.v1",
        groups=groups,
        input_pins=inputs,
        new_optimizer_proposals=0,
        new_financial_calls=0,
        new_fits=0,
    )
