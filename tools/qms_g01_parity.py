"""Compare scientific witnesses without confusing execution clocks with data."""

import json
from pathlib import Path

import numpy as np


def equal_values(left, right, path="witness"):
    if isinstance(left, dict):
        assert isinstance(right, dict) and set(left) == set(right), path
        for key in left:
            equal_values(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list):
        assert isinstance(right, list) and len(left) == len(right), path
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            equal_values(a, b, f"{path}[{index}]")
    elif isinstance(left, float) and isinstance(right, (int, float)):
        np.testing.assert_allclose(left, right, rtol=1e-9, atol=1e-9, err_msg=path)
    else:
        assert type(left) is type(right) and left == right, path


def logical_witness(payload):
    from quantbt.optimization.meta_selection.common import wire
    from quantbt.optimization.meta_selection.persistence import task_from_payload

    tasks, revisions = [], []
    for task in payload["tasks"]:
        # The existing strict decoder validates clocks, candidates and data roles.
        task_from_payload(task)
        ids = {c["evaluation_id"]: c["native_trial_id"] for c in task["candidates"]}
        row = {k: v for k, v in task.items() if k not in {
            "candidates", "anchor_candidate_evaluation_id", "roles", "search_completed_at",
            "anchor_selected_at", "decision_sealed_at", "wall_generated_at"}}
        row["candidates"] = [{k: observation(c[k]) if k == "observation" else v
            for k, v in c.items() if k not in {"evaluation_id", "resolved_at"}}
            for c in task["candidates"]]
        row["anchor_trial"] = ids[task["anchor_candidate_evaluation_id"]]
        row["roles"] = [{**r, "evaluation_id": ids[r["evaluation_id"]]} for r in task["roles"]]
        tasks.append(row)
    for revision in payload["revisions"]:
        task = task_from_payload(revision["task"])
        ids = {c.evaluation_id: c.native_trial_id for c in task.candidates}
        panel = revision["panel"]
        row = dict(origin=wire(task.origin), base_cap=panel["base_cap"], policy_id=panel["policy_id"],
            base_members=[ids[e] for e in panel["base_members"]],
            required_members=sorted(ids[e] for e in panel["required_members"]),
            extra_union_members=sorted(ids[e] for e in panel["extra_union_members"]),
            quota_roles=[[role, ids[e]] for role, e in panel["quota_roles"]],
            publication_order=revision["publication_order"],
            correction_reason=revision["correction_reason"],
            has_parent_revision=revision["parent_revision_id"] is not None,
            outcomes=sorted([dict(trial_id=ids[o["evaluation_id"]],
                observation=observation(o["observation"]),
                reporting_lag_seconds=o["reporting_lag_seconds"],
                publication_order=o["publication_order"]) for o in revision["outcomes"]],
                key=lambda o: o["trial_id"]))
        revisions.append(row)
    return dict(tasks=tasks, revisions=sorted(revisions, key=lambda r: r["origin"]))


def observation(value):
    # Same-pass native and original-result hashes intentionally bind different
    # physical artifacts. Keep all raw metrics and financial/data identities.
    return {k: v for k, v in value.items() if k not in {"output_ref", "verification"}}


def witness_parity(left, right):
    a, b = [json.loads(Path(p).read_text()) for p in (left, right)]
    equal_values(logical_witness(a), logical_witness(b))
    return dict(task_count=len(a["tasks"]), revision_count=len(a["revisions"]),
        all_is_and_forward_observations=True, ordered_base_panels=True,
        exact_trial_candidate_params_data_roles=True,
        physical_output_hashes_and_elapsed_clocks="retained_in_original_receipts_not_expected_equal")
