"""Saved-output receipt negatives, using only synthetic non-alpha records."""

from copy import deepcopy

import numpy as np
import pytest

from tools.qms_real_evidence import digest, numeric_summary, verify_counts, verify_lineage, verify_pair


def sample_counts():
    return {
        "folds": 2, "counts": {"attempted": 10, "completed": 8, "pruned": 2, "failed": 0},
        "sampler_studies": [{"states": {"COMPLETE": 4, "PRUNED": 1}, "attempts": 5,
                             "warm_start_attempts": 0} for _ in range(2)],
        "observer_failures": 0, "checks": {"reconciliation": True},
    }


def test_counts_verify_and_reject_bad_scope():
    sample = sample_counts()
    verify_counts(sample, 10, 2)
    with pytest.raises(ValueError, match="fold count"):
        verify_counts(sample, 10, 3)
    sample["counts"]["completed"] = 9
    with pytest.raises(ValueError, match="state counts"):
        verify_counts(sample, 10, 2)


@pytest.mark.parametrize("field", ["warm", "checks", "observer"])
def test_failed_checks_not_counted_as_pass(field):
    sample = sample_counts()
    if field == "warm":
        sample["sampler_studies"][0]["warm_start_attempts"] = 1
    elif field == "checks":
        sample["checks"]["reconciliation"] = False
    else:
        sample["observer_failures"] = 1
    with pytest.raises(ValueError):
        verify_counts(sample, 10, 2)


def lineage():
    tasks, records, revisions = [], [], []
    for i in range(28):
        task = {
            "data_cutoff": "2023-01-31T23:00:00+00:00",
            "first_forward_action_at": "2023-02-01T00:00:00+00:00",
            "anchor_candidate_evaluation_id": "anchor",
            "candidates": [{"evaluation_id": "anchor", "effective_params": {"p": 1},
                            "observation": {"verification": "original_result",
                                            "input_frontier": "2023-01-31T23:00:00+00:00"}}],
        }
        revision = {"task": {"forward_end": "2022-12-31T23:00:00+00:00", "origin": i},
                    "revision_available_at": "2023-01-01T00:00:00+00:00"}
        row = {
            "fold_id": i, "current_outer_oos_used_for_selection": False,
            "information_as_of": task["data_cutoff"],
            "ready_at": "2023-01-31T23:00:01+00:00",
            "training_revision_ids": [digest({"schema": "qms-revision-v1", "record": revision})],
            "matured_origins": 1, "native_selected_evaluation_id": "anchor",
            "selected_evaluation_id": "anchor", "selected_params": {"p": 1},
            "panel_members": ["anchor"], "observer_evaluations": 1,
        }
        tasks.append(task)
        records.append(row)
        revisions.append(revision)
    return ({"records": records, "params": {str(i): {"p": 1} for i in range(28)},
             "observer_attempts": 28}, {"tasks": tasks, "revisions": revisions})


def test_saved_chronology_and_application():
    sample, witness = lineage()
    verify_lineage(sample, witness)
    sample["params"]["0"] = {"p": 2}
    with pytest.raises(ValueError, match="params not applied"):
        verify_lineage(sample, witness)


@pytest.mark.parametrize("problem", ["current_oos", "readiness", "panel", "proxy", "unavailable"])
def test_saved_lineage_tamper(problem):
    sample, witness = lineage()
    row, task = sample["records"][0], witness["tasks"][0]
    if problem == "current_oos":
        row["current_outer_oos_used_for_selection"] = True
    elif problem == "readiness":
        row["ready_at"] = "2023-02-01T00:00:01+00:00"
    elif problem == "panel":
        row["panel_members"] = []
    elif problem == "proxy":
        task["candidates"][0]["observation"]["verification"] = "proxy"
    else:
        revision = witness["revisions"][0]
        revision["revision_available_at"] = "2023-02-01T00:00:00+00:00"
        row["training_revision_ids"] = [digest({"schema": "qms-revision-v1", "record": revision})]
    with pytest.raises(ValueError):
        verify_lineage(sample, witness)


def test_pair_ignores_clocks_not_economics():
    sample = {"params": {"0": {"p": 1}}, "trials": [{"trial_id": 0, "params": {"p": 1},
                                                       "objective": 1.0, "elapsed": 10}]}
    right = deepcopy(sample)
    right["trials"][0]["elapsed"] = 20
    arrays = {k: np.ones(2) for k in ("positions", "equity", "returns")}
    assert all(v == 0 for v in verify_pair(sample, right, arrays, arrays).values())
    right["trials"][0]["objective"] = 0.9
    with pytest.raises(ValueError, match="trial sequence mismatch"):
        verify_pair(sample, right, arrays, arrays)


def test_numeric_cumulative_counters_are_not_double_charged():
    snapshots = [{"ffi_calls": calls, "input_owned_copy_bytes": calls * 100,
                  "qualification_calls": 3, "selected_backend_by_block": {"gram_solve": "rust"},
                  "exact_work_cache": {"hits": 0, "misses": calls // 2}} for calls in (4, 8, 12)]
    summary = numeric_summary(snapshots)
    assert summary["ffi_calls"] == 12 and summary["qualification_calls"] == 3
    assert summary["input_owned_copy_bytes"] == 1200 and summary["cache_misses"] == 6
    with pytest.raises(ValueError, match="counter rewound"):
        numeric_summary(snapshots[::-1])
