"""Sanitize sealed real-portfolio outcomes; never expose private alpha/params."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tools.qms_e04_study import paired_analysis, read_registration
from tools.qms_e05_source_guard import ROOT, verify
from tools.qms_real_review import private_path, trial_trace


def reference(path):
    return dict(path=Path(path).resolve().relative_to(ROOT).as_posix(),
                sha256=sha256(Path(path).read_bytes()).hexdigest())


def build(output, package):
    output = private_path(output)
    record, registered_hash = read_registration(output)
    off, active = [json.loads((output/f"{arm}.json").read_text()) for arm in record["paired_arms"]]
    if off["registration_sha256"] != active["registration_sha256"] or off["registration_sha256"] != registered_hash:
        raise ValueError("arm registration mismatch")
    if off["harness_sha256"] != active["harness_sha256"] or trial_trace(off) != trial_trace(active):
        raise ValueError("different execution harness, search pool or objectives")
    if verify() != record["source"]:
        raise ValueError("reviewed production source changed")
    package = Path(package).resolve()
    proof = json.loads((package/"e05-proof.json").read_text())
    if proof["source_guard"] != record["source"] or (proof["core"], proof["native"]) != ("1.1.2", "0.4.3"):
        raise ValueError("study does not bind the installed artifact")
    for ref in proof["artifact_refs"]:
        path = ROOT/ref["path"]
        if sha256(path.read_bytes()).hexdigest() != ref["sha256"] or path.stat().st_size != ref["bytes"]:
            raise ValueError("exact installed artifact changed")
    witness_path = output/"active-witness.json"
    if sha256(witness_path.read_bytes()).hexdigest() != active["witness_sha256"]:
        raise ValueError("raw original-account witness changed")
    witness = json.loads(witness_path.read_text())
    if len(witness["tasks"]) != record["expected_folds"]:
        raise ValueError("incomplete task corpus")
    for row, task in zip(active["paired"], witness["tasks"], strict=True):
        candidates = {c["evaluation_id"]: c for c in task["candidates"]}
        anchor = candidates[task["anchor_candidate_evaluation_id"]]
        if off["params"][str(row["fold_id"])] != anchor["effective_params"]:
            raise ValueError("meta native anchor differs from off-arm actual params")
        if active["params"][str(row["fold_id"])] != candidates[row["selected"]]["effective_params"]:
            raise ValueError("meta params were not executed")
    from numpy import load
    financial = {}
    for arm, value in zip(record["paired_arms"], (off, active), strict=True):
        if (value["attempts"] != record["expected_folds"]*record["attempts_per_fold"] or
                set(value["checks"]) != {"original_account_exact", "snapshot_causal", "actual_params", "alpha_prefix_exact"} or
                not all(v is True for v in value["checks"].values()) or value["observer_failures"] or
                value["versions"]["quantbt-engine"] != "1.1.2" or value["versions"]["quantbt-native"] != "0.4.3"):
            raise ValueError("actual runtime/account gate incomplete")
        with load(output/f"{arm}.npz") as buffers:
            costs = {key:float(buffers[key].sum()) for key in ("fees", "funding")}
        financial[arm] = dict(report=value["full_report"], costs=costs,
            wall_seconds=value["wall_seconds"], cpu_seconds=value["cpu_seconds"],
            peak_rss_mib=value["after_memory"]["peak_rss_mib"], pss_mib=value["after_memory"]["pss_mib"],
            attempts=value["attempts"], completed=value["completed"], pruned=value["pruned"],
            account_conformance_seconds=value["account_check_seconds"])
    return dict(schema="qms-e04-sanitized-real-diagnostic-v1", source=record["source"],
        registration=reference(output/"registration.json"), installed_proof=reference(package/"e05-proof.json"),
        evidence=[reference(output/name) for name in ("off.json", "active.json", "off.npz", "active.npz", "active-witness.json")],
        alpha_sha256=record["alpha_sha256"], market=record["market"], universe=record["symbols"],
        account=record["account"], methodology=dict(mode="mode_4_is_only_robust", schedule="per_fold_causal",
            trials_per_fold=128, seed=731, full_is_search_exact=True, off_equals_active_native_anchor=True,
            raw_aggregate_account_metrics=True, actual_selected_params=True, calendar=record["frequency"],
            train_window=record["train_window"], locked_holdout=False, research_exposed=True,
            owner_new_universe_protocol_approved=False, no_outcome_retuning=True),
        analysis=paired_analysis(active["paired"], record), financial=financial,
        meta_elapsed=active["meta_elapsed"], observer_attempts=active["observer_attempts"],
        gates=dict(software="PASS", installed="PASS_LOCAL_CP312", real_diagnostic="EXECUTED",
            empirical_promotion="NOT_PROMOTED_OWNER_PROTOCOL_AND_LOCKED_EVALUATION_PENDING",
            e03_g01="SCIENTIFIC_COMPATIBILITY_APPROVAL_REQUIRED", remote="NOT_RUN_CURRENT_BYTES",
            publication="NOT_AUTHORIZED"), publication=False)


def render(receipt):
    analysis = receipt["analysis"]
    off, active = [receipt["financial"][arm] for arm in ("off", "active")]
    means = analysis["supported_means"]
    rows = "\n".join(f"| {label} | {off['report'][key]:.4f} | {active['report'][key]:.4f} |"
        for label, key in (("Final equity", "final_equity"), ("Return (%)", "total_return_pct"),
                          ("OOS account Sharpe", "sharpe"), ("Max drawdown (%)", "max_drawdown_pct")))
    return f'''# E04 Real Portfolio Meta On/Off Diagnostic

## Frozen Scope

Unchanged private Gradient/Delta RSI, ETHUSDT/BTCUSDT 1h, 37,968 aligned bars
per symbol (2020-01 through 2024-04); no missing-hour repair. Each strategy
uses its own causal price history and shared params. Original native portfolio
longshort `%_equity` account, 20,000 capital, 0.25 allocation per symbol,
leverage one, one-way fee 0.00025, one-bps slippage and original funding policy.
Mode 4 / per_fold_causal, rolling 365D, 28 monthly forward folds from 2022-01,
128 attempts per fold, seed 731, unchanged TPE recipe and no early stopping.

The owner requested real evaluation; the additional universe/protocol does not
have separate formal economic approval. This is research-exposed diagnostic
data, not locked holdout or the guide's complete development/evaluation split.
No results were used to retune alpha, learner, costs, RNG or thresholds.

## Correctness

Same full IS search pool/objectives and native anchor params between arms.
Active uses only past matured outcomes; selected params are actually executed.
IS/forward labels come from original aggregate shared-account results, never
symbol-average Sharpe. Final positions are stitched into one continuous account,
not compounded fold equities. Accepted positions, costs, funding, margin,
turnover, diagnostics and equity match an independent original-account call
exactly; its conformance cost is charged separately, not used for learning.

## Observed Effect

| Original OOS continuous account | Meta off | Meta active |
|---|---:|---:|
{rows}

{analysis["valid_folds"]}/{analysis["calendar_folds"]} paired-valid folds;
{analysis["supported_valid_origins"]} valid origins with twelve matured tasks;
{analysis["changed_decisions"]} changed selected evaluations.
Supported mean native decay: {means["native_decay"] if means else "UNDEFINED"}.
Supported mean meta decay: {means["meta_decay"] if means else "UNDEFINED"}.
R (native decay minus meta decay): {means["r"] if means else "UNDEFINED"}.
Forward Q (meta minus native Sharpe): {means["q"] if means else "UNDEFINED"}.
IS contribution: {means["is_difference"] if means else "UNDEFINED"}.
Intervals are paired moving-block bootstrap, three months, 4,096 resamples,
95%, seed 731. Read exact bounds in the [sanitized receipt](../../benchmarks/optimization/meta_selection/qms_e04_real_diagnostic.json).
Diagnostic R > 0 / lower-Q >= 0 threshold: **{analysis["diagnostic_threshold_pass"]}**.
Lower IS alone is not better forward performance. Undefined windows are not zero.

## Cost And Decision

Off: {off["wall_seconds"]:.3f} s, peak RSS {off["peak_rss_mib"]:.1f} MiB.
Active: {active["wall_seconds"]:.3f} s, peak RSS {active["peak_rss_mib"]:.1f} MiB.
One cold public call per arm on a shared VPS, single worker/numeric thread;
not repeated medians or a kernel benchmark. Observer attempts:
{receipt["observer_attempts"]}. Evaluation and learner timings stay separate
in the receipt. Costs include the original post-seal labels, not free inference.

**NOT PROMOTED.** Diagnostic success or failure does not replace owner approval
and locked evaluation. E03-G01 remains open without scientific repair approval.
Real quarterly basis has separate expiry/roll/data coverage requirements.
Current-source remote matrix and public index are not certified here.
Read [software/artifact scope](QMSE04_REPORT.md), [the plan](../../upgrade/implement.md#qms-e04)
and [cleanup](../BUILD_TEST_CLEANUP.md). Private alpha, params, data and raw
witnesses remain ignored. No push, merge, tag or upload was performed.
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("do not overwrite sealed diagnostic receipt")
    receipt = build(args.study, args.package)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    args.report.write_text(render(receipt))
    print(json.dumps(receipt["gates"], sort_keys=True))
