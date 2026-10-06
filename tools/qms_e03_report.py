"""Rebuild a public E03 receipt from private raw results; never copies alpha/params."""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from tools.qms_e02_audit import compare as compare_e02
from tools.qms_e03_queue import prepared_trace_parity
from tools.qms_e03_source_guard import ROOT, verify
from tools.qms_e03_study import CELLS, read_registration, summarize


def baseline_parity(before, after):
    # E02's broad JSON inventory includes E03's mutable reviewed-source input,
    # not just sealed historical receipts. Validate its current bytes separately;
    # every actual historical receipt and all financial/scientific lanes remain
    # subject to the original exact E02 comparator.
    a, b = deepcopy(before), deepcopy(after)
    name = "benchmarks/optimization/meta_selection/qms_e03_reviewed_source.json"
    if name in b["native"]["historical_receipts"]:
        assert b["native"]["historical_receipts"][name] == sha256((ROOT/name).read_bytes()).hexdigest()
    a["native"]["historical_receipts"].pop(name, None)
    b["native"]["historical_receipts"].pop(name, None)
    verify()
    return compare_e02(a, b)


def file_ref(path):
    path = Path(path).resolve()
    return dict(path=str(path.relative_to(ROOT)), sha256=sha256(path.read_bytes()).hexdigest())


def test_receipt(path):
    paths = [path] if isinstance(path, (str, Path)) else list(path)
    cases = [case for member in paths for case in ET.parse(member).getroot().iter("testcase")]
    identities = {(c.get("classname"), c.get("name")) for c in cases}
    if not cases or len(identities) != len(cases):
        raise ValueError("missing/duplicate executed test identities")
    if any(c.find(s) is not None for c in cases for s in ("failure", "error", "skipped")):
        raise ValueError("E03 regression requires no failures, errors or skips")
    groups = {f"E03-T{i:02d}": sum(c.get("name", "").startswith(f"test_e03_t{i:02d}_")
                                   for c in cases) for i in range(1, 7)}
    if not all(groups.values()):
        raise ValueError("E03 required test group missing")
    return dict(distinct_tests=len(cases), e03_members=groups, failures=0, errors=0, skipped=0,
                evidence=[file_ref(p) for p in paths])


def execution_summary(run):
    trials = run["trials"]
    assert len(trials) == run["attempts"] == run["completed"] + run["pruned"]
    unique = {(row["schedule_fold_id"], json.dumps(row["params"], sort_keys=True, allow_nan=False))
              for row in trials}
    return dict(attempts=run["attempts"], completed=run["completed"], pruned=run["pruned"],
        failed=0, unique_requested_params_by_fold=len(unique),
        wall_seconds=run["wall_seconds"], cpu_seconds=run["cpu_seconds"],
        execution_memory=run["after_memory"], export_memory=run["after_export_memory"],
        cold_export_seconds_before_receipt=run["cold_export_seconds_before_receipt"],
        independent_account_check_seconds=run["account_check_seconds"])


def build(*, study, package, junit, before, after):
    import numpy as np
    from tools.qms_real_review import trial_trace
    source = verify()
    tests = test_receipt(junit)
    baseline = json.loads(Path(before).read_text())
    current = json.loads(Path(after).read_text())
    assert baseline_parity(baseline, current)
    artifact = json.loads((package / "e03-proof.json").read_text())
    assert artifact["source_guard"] == source
    assert artifact["source_exact_wheel"] and artifact["source_exact_sdist"]
    base_proof = file_ref(package / "e01-proof.json")
    assert base_proof["sha256"] == artifact["base_proof_sha256"]
    expected = set(CELLS)
    for consumer in artifact["consumers"].values():
        assert {(c["target"], c["backend"]) for c in consumer["cells"]} == expected
        assert len(consumer["cells"]) == 8
        assert all(c["off_shadow_account_exact"] and c["active_original_witness"] for c in consumer["cells"])
        assert consumer["empirical_promotion"] is False
    for ref in artifact["artifact_refs"]:
        file = ROOT / ref["path"]
        assert file.stat().st_size == ref["bytes"] and sha256(file.read_bytes()).hexdigest() == ref["sha256"]
    registration, registration_hash = read_registration(study)
    assert registration["source"] == source
    summary = summarize(study)
    rows, raw_refs, totals = [], [], dict(attempts=0, completed=0, pruned=0, observer_attempts=0)
    for row in summary["rows"]:
        if row["status"] == "NOT_EXECUTED":
            raise ValueError("all eight registered pairs must finish before final E03 receipt")
        target, backend = row["target"], row["backend"]
        arms = [study / f"{target}-{backend}-{a}-off.json" for a in ("off", "active")]
        off, active = [json.loads(p.read_text()) for p in arms]
        assert trial_trace(off) == trial_trace(active)
        raw_refs.extend(file_ref(p) for p in arms)
        assert [r["schedule_fold_id"] for r in off["trials"]] == [r["schedule_fold_id"] for r in active["trials"]]
        for path, run in zip(arms, (off, active), strict=True):
            assert run["source_sha256"] == source["source_sha256"] and all(run["checks"].values())
            raw_refs.append(file_ref(path.with_suffix(".npz")))
            if run["witness_sha256"]:
                witness = path.with_name(path.stem + "-witness.json")
                assert sha256(witness.read_bytes()).hexdigest() == run["witness_sha256"]
                raw_refs.append(file_ref(witness))
            for key in totals:
                totals[key] += run.get(key, 0)
        intervals = row["supported_interval_r_q_is"]
        # Fixed whitelist: private parameters, candidate rows, alpha and prices
        # never enter the public receipt.
        rows.append(dict(target=target, backend=backend, empirical_status=row["status"],
            registered_threshold_pass=row["registered_threshold_pass"],
            calendar_folds=row["calendar_folds"], valid_folds=row["valid_folds"],
            supported_valid_origins=row["supported_valid_origins"],
            all_valid_mean_r=row["all_valid_mean_r"], all_valid_mean_q=row["all_valid_mean_q"],
            supported_means=row["supported_means"],
            supported_interval_r_q_is=intervals,
            off_seconds=row["off_seconds"], active_seconds=row["active_seconds"],
            added_seconds=row["active_seconds"]-row["off_seconds"],
            overhead_pct=(row["active_seconds"]/row["off_seconds"]-1.)*100.,
            off_peak_rss_mib=row["off_peak_rss_mib"], active_peak_rss_mib=row["active_peak_rss_mib"],
            meta_elapsed=row["meta_elapsed"], observer_attempts=row["observer_attempts"],
            execution={a:execution_summary(r) for a,r in (("off",off),("active",active))},
            metrics={a:{k:r["full_report"][k] for k in
                ("final_equity", "sharpe", "max_drawdown_pct", "num_trades")}
                for a,r in (("off",off),("active",active))},
            matched_is_pool=True, original_account_parity=True, empirical_promotion=False))
    prepared_rows = []
    for target in ("notional", "unit"):
        paths = [study / f"{target}-native_vectorized-active-{p}.json" for p in ("off", "require")]
        normal, prepared = [json.loads(p.read_text()) for p in paths]
        prepared_trace_parity(normal, prepared)
        assert normal["params"] == prepared["params"]
        with np.load(paths[0].with_suffix(".npz")) as a, np.load(paths[1].with_suffix(".npz")) as b:
            assert a.files == b.files
            delta = {}
            for key in a.files:
                np.testing.assert_allclose(a[key], b[key], rtol=1e-9, atol=1e-8)
                delta[key] = float(np.max(np.abs(a[key]-b[key])))
        raw_refs.append(file_ref(paths[1]))
        raw_refs.append(file_ref(paths[1].with_suffix(".npz")))
        witness = paths[1].with_name(paths[1].stem + "-witness.json")
        assert sha256(witness.read_bytes()).hexdigest() == prepared["witness_sha256"]
        raw_refs.append(file_ref(witness))
        prepared_rows.append(dict(target=target, original_seconds=normal["wall_seconds"],
            prepared_seconds=prepared["wall_seconds"], selected_params_exact=True,
            full_trial_pool_parity=True, account_max_absolute_difference=delta,
            execution=execution_summary(prepared), observer_attempts=prepared["observer_attempts"],
            prepared_peak_rss_mib=prepared["after_memory"]["peak_rss_mib"]))
    return dict(schema="qms-e03-final-evidence-v1", local_software_gate="PASS",
        empirical_promotion=False, owner_review="PENDING", remote_current_source="NOT_RUN",
        public_index_qualification="NOT_RUN", publication=False, source=source,
        tests=tests, legacy_scalar_reactive_account_exact=True,
        baseline_refs=[file_ref(before), file_ref(after)],
        installed_pair=dict(core=artifact["core"], native=artifact["native"],
            evidence=file_ref(package / "e03-proof.json"), artifact_refs=artifact["artifact_refs"],
            mandatory_consumer_evidence=base_proof,
            exact_core_source=True, native_rebuilt=False, software_cells=8),
        registration_sha256=registration_hash,
        protocol=dict(trials=128, seed=731, matured_origins=12, paired_folds=28,
            interval="95% moving-block percentile / 3 months / 4096 draws", research_exposed=True,
            locked_holdout=False, financial_authority="original per-cell Numba execution",
            meta_numeric_authority="compiled Rust require", timing="cold public call/shared VPS/one study worker"),
        counts=totals, prepared_additional_attempts=sum(r["execution"]["attempts"] for r in prepared_rows),
        cells=rows, prepared_full_studies=prepared_rows, private_raw_refs=raw_refs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("study", "package", "before", "after", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--junit", type=Path, nargs="+", required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    if output.exists():
        raise ValueError("receipt sealed; choose a fresh path")
    result = build(**args)
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(gate=result["local_software_gate"], cells=len(result["cells"]),
                          promotion=False, publication=False)))
