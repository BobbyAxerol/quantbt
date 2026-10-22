"""Cold verification and allowlisted public evidence; no financial execution."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import median


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "data/local/qms-real-review"
OUTPUT = REPO / "benchmarks/optimization/meta_selection/qms_real_review_evidence.json"
ARMS = ("off", "shadow", "active_rust", "active_reference")
RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def registration_digest(value):
    # The private runner registered indented-space JSON, not the QMS wire format.
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def trial_trace(sample):
    keys = ("trial_id", "params", "objective", "mean_is_sharpe", "pruned", "fold_id")
    return [{k: r.get(k) for k in keys} for r in sample["trials"]]


def numeric_summary(snapshots):
    require(bool(snapshots), "missing native telemetry")
    # Decision metadata snapshots hold run-cumulative counters, not fold deltas.
    for earlier, later in zip(snapshots, snapshots[1:]):
        for field in ("ffi_calls", "input_owned_copy_bytes", "qualification_calls"):
            require(earlier[field] <= later[field], "native cumulative counter rewound")
    latest = snapshots[-1]
    return {
        "counter_scope": "latest run-cumulative snapshot; not summed across decisions",
        "ffi_calls": latest["ffi_calls"], "qualification_calls": latest["qualification_calls"],
        "input_owned_copy_bytes": latest["input_owned_copy_bytes"],
        "cache_hits": latest["exact_work_cache"]["hits"],
        "cache_misses": latest["exact_work_cache"]["misses"],
        "latest_cache": latest["exact_work_cache"],
        "selected_backend_by_block": latest["selected_backend_by_block"],
    }


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_counts(sample, attempts, folds):
    counts = sample["counts"]
    studies = sample["sampler_studies"]
    require(sample["folds"] == folds and len(studies) == folds, "fold count")
    for key, state in (("completed", "COMPLETE"), ("pruned", "PRUNED"), ("failed", "FAIL")):
        require(counts[key] == sum(s["states"].get(state, 0) for s in studies), "state counts")
    require(counts["attempted"] == attempts == sum(s["attempts"] for s in studies), "attempt count")
    require(sum(counts[k] for k in ("completed", "pruned", "failed")) == attempts, "terminal counts")
    require(counts["failed"] == sample["observer_failures"] == 0, "execution failures")
    require(all(s["warm_start_attempts"] == 0 for s in studies), "unexpected warm start")
    require(all(sample["checks"].values()), "worker reconciliation failed")


def verify_lineage(sample, witnesses):
    import pandas as pd

    records, tasks = sample["records"], witnesses["tasks"]
    require(len(records) == len(tasks) == 28, "missing real tasks")
    revisions = {digest({"schema": "qms-revision-v1", "record": r}): r
                 for r in witnesses["revisions"]}
    require(len(revisions) == 28, "missing/duplicate terminal revisions")
    for row, task in zip(records, tasks):
        cutoff, action = pd.Timestamp(task["data_cutoff"]), pd.Timestamp(task["first_forward_action_at"])
        require(cutoff < action, "current forward intersects selection cutoff")
        require(not row["current_outer_oos_used_for_selection"], "current OOS used for selection")
        require(pd.Timestamp(row["information_as_of"]) == cutoff, "snapshot cutoff changed")
        require(pd.Timestamp(row["ready_at"]) <= action, "effect before readiness")
        ids = row["training_revision_ids"]
        require(len(set(ids)) == row["matured_origins"], "origin support mismatch")
        for rid in ids:
            require(rid in revisions, "snapshot references absent revision")
            revision = revisions[rid]
            require(pd.Timestamp(revision["revision_available_at"]) <= cutoff, "unavailable revision")
            require(pd.Timestamp(revision["task"]["forward_end"]) <= cutoff, "future label")
        candidates = {c["evaluation_id"]: c for c in task["candidates"]}
        anchor, selected = row["native_selected_evaluation_id"], row["selected_evaluation_id"]
        require(anchor == task["anchor_candidate_evaluation_id"], "native anchor mismatch")
        require(anchor in candidates and selected in candidates, "selection outside current pool")
        require(anchor in row["panel_members"] and selected in row["panel_members"], "missing panel member")
        require(candidates[selected]["effective_params"] == row["selected_params"], "selected params mismatch")
        require(row["selected_params"] == sample["params"][str(row["fold_id"])], "params not applied")
        for candidate in candidates.values():
            observation = candidate["observation"]
            require(observation["verification"] == "original_result", "proxy IS metric")
            require(pd.Timestamp(observation["input_frontier"]) <= cutoff, "future IS observation")
    require(sum(r["observer_evaluations"] for r in records) == sample["observer_attempts"], "observer count")


def verify_pair(left, right, left_arrays, right_arrays):
    import numpy as np

    require(trial_trace(left) == trial_trace(right), "trial sequence mismatch")
    require(left["params"] == right["params"], "fold params mismatch")
    differences = {}
    require(set(left_arrays) == set(right_arrays) == {"positions", "equity", "returns"}, "array fields")
    for name in left_arrays:
        a, b = left_arrays[name], right_arrays[name]
        np.testing.assert_allclose(a, b, rtol=1e-10, atol=1e-10)
        differences[name] = float(np.max(np.abs(a - b)))
    return differences


def build(root=ROOT):
    import numpy as np

    def read(name):
        return json.loads((root / name).read_text())
    summary, registration = read("summary.json"), read("registration.json")
    require(summary["registration"] == registration, "registration changed")
    hashes = {}
    for name, expected in summary["private_artifacts"].items():
        if name == "remaining_progress.json":
            continue  # Queue terminal status is not an immutable run input.
        actual = sha256((root / name).read_bytes()).hexdigest()
        require(actual == expected, f"private artifact changed: {name}")
        hashes[name] = actual
    samples, arrays, main = {}, {}, {}
    for arm in ARMS:
        worker = read(f"meta_{arm}_tpe_legacy.json")
        require(worker["registration_digest"] == registration_digest(registration), "worker registration")
        require("site-packages" in worker["core_origin"], "source-shadow worker")
        require(worker["versions"] == summary["versions"], "worker versions")
        require(len(worker["samples"]) == 1, "unregistered timing repeats")
        sample = worker["samples"][0]
        verify_counts(sample, 3584, 28)
        if arm != "off":
            verify_lineage(sample, read(f"meta_{arm}_tpe_legacy_0_witness.json"))
        with np.load(root / f"meta_{arm}_tpe_legacy_0.npz") as stored:
            arrays[arm] = {k: stored[k] for k in stored.files}
        for name, values in arrays[arm].items():
            require(sha256(np.ascontiguousarray(values).tobytes()).hexdigest() ==
                    sample["arrays_sha256"][name], "saved account buffer changed")
        samples[arm] = sample
        main[arm] = {k: sample[k] for k in summary["meta"][arm]}
        require(main[arm] == summary["meta"][arm], "main cost summary mismatch")
        main[arm]["cold_two_fold_warmup_seconds"] = worker["cold_warmup_seconds"]
        main[arm]["arrays_sha256"] = sample["arrays_sha256"]
    parity = {f"{a}_vs_{b}": verify_pair(samples[a], samples[b], arrays[a], arrays[b])
              for a, b in (("off", "shadow"), ("active_rust", "active_reference"))}
    require(parity == summary["parity"], "parity summary mismatch")
    fixed = read("fixed_replay.json")
    for value in fixed.values():
        require(value["regenerated_folds"] == 28 and value["params_actually_applied"], "fixed replay scope")
        require(value["optimization_attempts"] == value["meta_fit_calls"] == 0, "fixed replay searched")
        require(all(d == 0 for d in value["maximum_differences"].values()), "fixed replay changed account")
    samplers = {}
    for recipe in RECIPES:
        worker = read(f"sampler_off_{recipe}.json")
        require(worker["registration_digest"] == registration_digest(registration), "sampler registration")
        runs = worker["samples"]
        require(len(runs) == 3, "sampler repeats")
        for s in runs:
            verify_counts(s, 64, 2)
            require(s["params"] == runs[0]["params"] and trial_trace(s) == trial_trace(runs[0]), "sampler repeat changed")
            require(s["arrays_sha256"] == runs[0]["arrays_sha256"], "sampler account changed")
        require(median(s["wall_seconds"] for s in runs) == summary["samplers"][recipe]["median_seconds"],
                "sampler median mismatch")
        samplers[recipe] = dict(summary["samplers"][recipe])
        samplers[recipe]["resolved_settings"] = {
            k: runs[0]["sampler_studies"][0][k] for k in (
                "sampler_class", "kwargs", "startup_policy", "relative_proposal_trials",
                "qmc_sequence_position", "group_decomposition",
            )
        }
    profile = read("witness_profile.json")
    require(profile["original_native_params_preserved"], "profile changed native selection")
    owners = []
    for f in profile["functions"]:
        if "/quantbt/optimization/meta_selection/" in f["file"]:
            owners.append({**f, "file": "quantbt/optimization/meta_selection/" +
                           f["file"].split("/quantbt/optimization/meta_selection/", 1)[1]})
    hashes.update({name: sha256((root / name).read_bytes()).hexdigest()
                   for name in ("summary.json", "witness_profile.json", "fixed_replay.json")})
    pairs = {k: v for k, v in summary["supported_pairs"].items() if k != "rows"}
    pairs["uncertainty"] = summary["uncertainty"]
    paired_by_id = {r["fold_id"]: r for r in summary["all_pairs"]["rows"]}
    fold_metrics = []
    for row in samples["active_rust"]["paired"]:
        fold_metrics.append({k: row[k] for k in ("fold_id", "start", "end", "matured_origins", "reason",
                                                "native", "meta")} | {
            k: paired_by_id[row["fold_id"]][k] for k in ("status", "r", "q", "is_difference")
        })
    records = samples["active_rust"]["records"]
    numeric = [r["numeric_backend"] for r in records if r["past_matured_forward_used_for_selection"]]
    require(len(numeric) == summary["learned_folds"] == 15, "learned support changed")
    require(all(n["selected_backend_by_block"]["gram_solve"] == "rust" for n in numeric), "fake Rust fit")
    return {
        "schema": "qms-real-review-public-v1", "status": "PASS_REAL_ETH_OWNER_REVIEW_PENDING",
        "protocol": {k: registration[k] for k in (
            "alpha", "symbol", "timeframe", "notebook_sha256", "alpha_sha256", "market", "account",
            "canonical_one_way_fee_rate", "calendar", "main_trials_per_fold", "minimum_origins", "seed",
            "sampler_trials_per_fold", "sampler_repeats", "research_exposure", "scientific_claim",
        )},
        "versions": summary["versions"], "financial_authority": "numba",
        "main_timing_repeats": 1, "rss_scope": "process execution high-water before cold JSON export",
        "main": main, "samplers": samplers, "parity": parity, "fixed_replay": fixed,
        "supported_pairs": pairs, "all_calendar_pairs": {
            k: v for k, v in summary["all_pairs"].items() if k != "rows"
        },
        "fold_metrics": fold_metrics, "actual_param_switches": summary["switches"],
        "numeric": numeric_summary(numeric),
        "profile": {"wall_seconds": profile["wall_seconds"], "scope": profile["scope"],
                    "owners": owners, "original_native_params_preserved": True},
        "physical_full_run_evaluator_calls": "NOT_INSTRUMENTED; profiler counts are separate",
        "claims": {"primary_BTC_certified": False, "live_certified": False,
                   "universal_edge": False, "release_authorized": False},
        "private_artifact_sha256": hashes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    evidence = build()
    if args.check:
        require(json.loads(OUTPUT.read_text()) == evidence, "public receipt changed")
    else:
        require(not OUTPUT.exists(), "preserve already-published evidence")
        OUTPUT.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    print("real-alpha saved metrics, chronology, counters, buffers and public allowlist verified")


if __name__ == "__main__":
    main()
