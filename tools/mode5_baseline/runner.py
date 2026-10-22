"""Source-bound M5-01 receipt. No private alpha import or market optimization."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
from time import perf_counter
import xml.etree.ElementTree as ET

from .evidence import interval_record, load_json, reconcile, sampler_observation
from .cleanup import cleanup_workspace, verify_snapshot
from .inventory import alpha_inventory, binding_map, provenance, sampler_factory_manifest
from .isolation import canonical_digest, copy_python_tree, copy_reviewed_files, file_identity, private_output, write_json, zip_manifest
from .registration import study_registration


ROOT = Path(__file__).resolve().parents[2]
GUIDE = "upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md"
MASTERS = ("00_BASELINE_mode5_invariant_master_artifact.json",
           "01_TEST1_mode5_sampler_tuning_master_artifact.json",
           "02_TEST2_mode5_direct_formulations_master_artifact.json")
ALPHAS = {"A-SC": "a_sc.py", "A-HMA": "a_hma.py", "A-VWAP": "a_vwap.py", "A-HASH": "a_hash.py"}
TESTS = ("tests/mode5/test_baseline.py", "tests/test_phase48b_release_hygiene.py",
         "tests/test_phase48f_release_gate.py", "tests/test_optimization_samplers.py")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def expected_inputs(text: str) -> dict:
    rows = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\| ([A-Z0-9-]+) \| `([^`]+)` \| ([\d,]+) \| `([a-f0-9]{64})` \|", line)
        if match:
            ref, name, size, digest = match.groups()
            rows[ref] = {"name": name, "bytes": int(size.replace(",", "")), "sha256": digest}
    return rows


def checked_input(path: Path, expected: dict, ref: str) -> dict:
    observed = file_identity(path)
    if any(observed[k] != expected[k] for k in ("bytes", "sha256")):
        raise ValueError(f"input identity mismatch: {ref}")
    return observed | {"ref": ref, "status": "VERIFIED_EXTRACTED_MEMBER"}


def archive_inventory(paths: list[Path], expected: dict, ref: str) -> dict:
    observed = []
    for path in paths:
        if path.is_symlink() or path.exists():
            identity = checked_input(path, expected, ref)
            observed.append(identity | {"status": "VERIFIED_ORIGINAL_ARCHIVE", "manifest": zip_manifest(path)})
    return {"ref": ref, "expected": expected, "observed": observed or None,
            "searched_paths": list(map(str, paths)),
            "status": "VERIFIED_ORIGINAL_ARCHIVE" if observed else "NOT_SUPPLIED_AT_REGISTERED_PATHS",
            "disposition": "verified archive identity" if observed else
                           "verified extracted source members; no archive certificate or reconstruction",
            "recovery_owner": "maintainer",
            "recovery_action": None if observed else "supply exact archive or approve scoped extracted-member baseline"}


def protected_snapshot(paths) -> dict:
    return {str(path.resolve()): file_identity(path)["sha256"] for path in sorted(set(paths))}


def privacy_inventory(roots: list[Path]) -> dict:
    relative = [str(root.relative_to(ROOT)) for root in roots]
    tracked = git("ls-files", "--", *relative).splitlines()
    if tracked:
        raise ValueError("private research path is tracked; do not remove owner files implicitly")
    ignored = {}
    for path in relative:
        result = subprocess.run(["git", "check-ignore", "--no-index", "--quiet", path + "/"], cwd=ROOT)
        ignored[path] = result.returncode == 0
    if not all(ignored.values()):
        raise ValueError("private research path lacks Git ignore protection")
    return {"tracked_private_paths": tracked, "git_ignored_roots": ignored,
            "sdist_alpha_exclusion": "MANIFEST.in: prune upgrade/alphas",
            "artifact_guard": "tools/check_release_artifacts.py --private-source-root upgrade/alphas",
            "certification": "GIT_AND_SYNTHETIC_CANARIES_ONLY_NO_NEW_DISTRIBUTION_BUILD"}


def run_checks(output: Path, scratch: Path) -> list[dict]:
    scratch.parent.mkdir(parents=True, exist_ok=True)
    checks = [
        [sys.executable, "-m", "pytest", "-q", *TESTS, "-p", "no:cacheprovider",
         f"--basetemp={scratch}", f"--junitxml={output / 'tests.xml'}"],
        [sys.executable, "tools/check_docs_links.py", "--check-anchors", "--file", "upgrade/implement.md", "--file", GUIDE],
        [sys.executable, "tools/scan_public_secrets.py"],
        ["git", "diff", "--check"],
    ]
    runs = []
    for command in checks:
        start = perf_counter()
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                       timeout=600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        except subprocess.TimeoutExpired as exc:
            def decode(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            write_json(output / f"check-{len(runs)+1:02}.json", {
                "command": command, "exit_code": None, "status": "TIMED_OUT", "timeout_seconds": 600,
                "wall_seconds": perf_counter()-start, "stdout": decode(exc.stdout), "stderr": decode(exc.stderr)})
            raise
        row = {"command": command, "exit_code": completed.returncode,
               "wall_seconds": perf_counter() - start, "stdout": completed.stdout,
               "stderr": completed.stderr}
        runs.append(row)
        write_json(output / f"check-{len(runs):02}.json", row)
        if completed.returncode:
            raise ValueError(f"M5-01 check failed; retained {output}/check-{len(runs):02}.json")
    return runs


def run(args) -> dict:
    started = perf_counter()
    private_root = ROOT / "upgrade/private/mode5_upgrade_v1/m5-01"
    local_root = ROOT / "upgrade/local/mode5_upgrade_v1/m5-01"
    protected_roots = (ROOT / "src", ROOT / "rust", ROOT / "upgrade/alphas", args.bundle)
    output = private_output(args.output, [private_root], protected_roots)
    copies = private_output(local_root / output.name, [local_root], protected_roots)
    scratch_root = ROOT / ".maturin/mode5/m5-01"
    scratch = private_output(scratch_root / output.name, [scratch_root], protected_roots)
    before = shutil.disk_usage(ROOT)
    if before.free < 5 * 1024**3 + 64 * 1024**2:
        raise ValueError("insufficient registered disk reserve")
    if git("branch", "--show-current") == "main":
        raise ValueError("main is protected")
    text = (ROOT / GUIDE).read_text()
    expected = expected_inputs(text)
    archives = [archive_inventory([ROOT / "upgrade" / expected[ref]["name"],
                                  args.bundle.parent / expected[ref]["name"]], expected[ref], ref)
                for ref in ("BUNDLE", "D4")]
    spec = args.bundle / "MODE5_INVARIANT_AND_ALPHA_PROFILING_SPEC_V1_1.md"
    input_paths = [spec, *(args.bundle / name for name in MASTERS)]
    inputs = [checked_input(path, expected[ref], ref)
              for ref, path in zip(("D0", "D1", "D2", "D3"), input_paths, strict=True)]
    for alpha, name in ALPHAS.items():
        inputs.append(checked_input(ROOT / "upgrade/alphas" / name, expected[f"D4-{alpha[2:]}"] , alpha))
    inputs.append(checked_input(ROOT / "upgrade/alphas/golden.py", expected["D4-GOLDEN"], "D4-GOLDEN"))
    historical_scripts = sorted(args.bundle.parent.joinpath("experiments").glob("mode5_*benchmark.py"))
    private_alphas = sorted((ROOT / "upgrade/alphas").rglob("*.py"))
    production = [ROOT / name for name in git("ls-files", "--", "src", "rust", "contracts").splitlines()
                  if Path(name).suffix in {".py", ".rs", ".toml", ".json"}]
    locks = [ROOT / "uv.lock", ROOT / "rust/Cargo.lock", ROOT / "pyproject.toml"]
    extras = list(args.bundle.glob("*.md")) + historical_scripts + locks + [ROOT / GUIDE,
              ROOT / "upgrade/MODE5_INVARIANT_AND_ALPHA_PROFILING_SPEC_V1.md", args.rsi]
    historical_alpha_root = args.bundle.parent / "src/crypto_regime_lab/alphas"
    historical_alphas = sorted(historical_alpha_root.rglob("*.py"))
    data_documents = [p for name in ("data_readlock_policy.json", "data_provenance.json", "instrument_registry.json")
                      if (p := args.bundle.parent / "configs" / name).is_file()]
    extras.extend(historical_alphas + data_documents)
    phase_files = [ROOT / "MANIFEST.in", ROOT / "tools/check_release_artifacts.py",
                   ROOT / "tools/run_mode5_baseline.py", ROOT / TESTS[0],
                   *sorted((ROOT / "tools/mode5_baseline").glob("*.py"))]
    extras.extend(phase_files)
    extras.extend(Path(row["path"]) for archive in archives for row in (archive["observed"] or []))
    snapshot = protected_snapshot([*input_paths, *private_alphas, *production, *extras])
    output.mkdir(parents=True)
    write_json(output / "protected_before.json", snapshot)
    resource_plan = {"filesystem_free_bytes": before.free, "free_inodes": os.statvfs(ROOT).f_favail,
                     "incremental_budget_bytes": 64 * 1024**2, "minimum_free_bytes": 5 * 1024**3,
                     "processes": 1, "threads": 1, "market_evaluations": 0,
                     "scratch": str(scratch), "retained": [str(output), str(copies)]}
    write_json(output / "resource_registration.json", resource_plan)
    source = {"git_sha": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
              "dirty_state": git("status", "--porcelain"), "runtime": provenance(),
              "locks": [file_identity(path) for path in locks],
              "phase_source_files": [file_identity(path) for path in phase_files],
              "production_source_id": canonical_digest({name: value for name, value in snapshot.items()
                                                        if "/src/quantbt/" in name or "/rust/" in name})}
    if Path(source["runtime"]["imports"]["quantbt"]["path"]) != (ROOT / "src/quantbt/__init__.py").resolve():
        raise ValueError("harness must import the reviewed source checkout")
    if source["runtime"]["loaded_core_version"] != "1.1.2" or source["runtime"]["packages"]["quantbt-native"] != "0.4.3":
        raise ValueError("wrong registered core/native pair; do not repair the environment implicitly")
    for path in private_alphas + historical_scripts:
        ast.parse(path.read_text(), filename=str(path))
    baseline, t1, t2 = [load_json(path) for path in input_paths[1:]]
    analysis = reconcile(baseline, t1, t2, spec.read_text())
    roster = {alpha: alpha_inventory(ROOT / "upgrade/alphas" / name)
              for alpha, name in ALPHAS.items()}
    roster["A-RSI"] = alpha_inventory(args.rsi)
    for alpha, row in roster.items():
        historical = historical_alpha_root / ALPHAS[alpha] if alpha in ALPHAS else None
        row.update(symbol="ETHUSDT" if alpha == "A-RSI" else "BTCUSDT",
                   timeframe="1h" if alpha == "A-RSI" else "1m_historical_scope_to_be_admitted",
                   route="pct_equity_candidate" if alpha in {"A-SC", "A-RSI"} else "event_lifecycle_candidate",
                   clock_sizing_warmup_status="UNVERIFIED_M5_02",
                   fullset_presets_role="REFERENCE_ONLY_SELECTION_ADJUSTED",
                   historical_source=(file_identity(historical) if historical and historical.is_file() else None),
                   historical_primary_file_matches=(file_identity(historical)["sha256"] == row["sha256"]
                                                    if historical and historical.is_file() else None),
                   helper_and_financial_equivalence="NOT_CERTIFIED_BY_PRIMARY_FILE_EQUALITY")
    copies.mkdir(parents=True)
    copy_reviewed_files(input_paths, copies / "bundle", allowed_roots=[local_root], protected_roots=protected_roots)
    copy_python_tree(ROOT / "upgrade/alphas", copies / "alphas", allowed_roots=[local_root], protected_roots=protected_roots)
    copy_reviewed_files([args.rsi], copies / "rsi", allowed_roots=[local_root], protected_roots=protected_roots)
    cache_roots = [args.bundle.parent / "evidence" / name for name in
                   ("mode5_invariant_benchmark", "mode5_sampler_tuning_benchmark", "mode5_direct_formulations_benchmark")]
    cache_inventory = [{"root": str(path), "files": [file_identity(p) for p in sorted(path.glob("*")) if p.is_file()],
                        "scope": "only these three historical lanes; not a server-wide absence claim"} for path in cache_roots]
    recovery = {"summary_reanalysis": "REANALYZE_ONLY", "execution_reuse": "SOURCE_COMPATIBILITY_UNVERIFIED",
                "full_paths": "MISSING_REQUIRED_INPUT_IN_SEARCHED_LANES", "cache_search": cache_inventory,
                "plan": ["request original retained source/equity/fill/data witnesses before reuse",
                         "M5-02 qualify actual new alpha source/clock/sizing with eventful synthetic/pilot admission",
                         "M5-04 register minimal missing candidate replay only after data/support authorization"],
                "no_automatic_market_rerun": True}
    conceptual = [{"kind": "SEMANTIC_SCOPE_CORRECTION", "old_value": "Random/TPE/QMC",
                   "new_value": analysis["actual_sampler_labels"], "source_pointer": "D2#/metadata/samplers",
                   "historical_location": "D0 chapter 3.1 and export README table; preserved unchanged"},
                  {"kind": "SEMANTIC_SCOPE_CORRECTION", "old_value": "untouched independent OOS 2024",
                   "new_value": "EXPLORATORY_REVIEWED_2024; about 43 scored elapsed days for T1",
                   "source_pointer": "D2#/metadata/stress_regimes/R_HOLDOUT"},
                  {"kind": "SOURCE_OBSERVATION", "old_value": "NSGA-II search / LORO validation",
                   "new_value": "paired QMC panel; Pareto/Chebyshev postselection and range-penalty selection",
                   "source_pointer": "historical direct-formulations source: tuning/selection functions; no new method certification"},
                  {"kind": "HYPOTHESIS_NOT_UNIVERSAL_CONCLUSION", "old_value": "trend cannot use fixed configuration",
                   "new_value": "T2 scope negative; T1 HMA/QMC positive; alpha/recipe/horizon diagnostics required",
                   "source_pointer": "D2#/matrix_summary; D3#/"}]
    manifest = {"schema": "quantbt.mode5_baseline.manifest.v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "phase": "M5-01", "guide": file_identity(ROOT / GUIDE), "source": source,
                "inputs": inputs, "archives": archives, "alpha_files_ast_parsed": len(private_alphas),
                "historical_source": [file_identity(p) for p in historical_scripts],
                "source_compatibility": "NOT_FINANCIALLY_REPLAYED", "bytecode_imported": False}
    data_registry = {"schema": "quantbt.mode5_baseline.data_roles.v1",
                     "historical_windows": analysis["windows"],
                     "development_anchors": {k: interval_record(v) for k, v in baseline["metadata"]["regimes"].items()},
                     "data_policy_documents": [file_identity(p) for p in data_documents],
                     "raw_snapshot_verified": False, "snapshot_status": "NO_DATA_LOAD_OR_NEW_SNAPSHOT_M5_01",
                     "next_action": "M5-02 pin actual permitted market snapshot before any pilot",
                     "selection_permission": "reviewed development only; no untouched window invented",
                     "data_after_unregistered_origin": "NO_SELECTION_PERMISSION",
                     "preset_role": "REFERENCE_ONLY_SELECTION_ADJUSTED"}
    files = {"baseline_manifest.json": manifest, "evidence_errata.json": {"entries": analysis["numeric_errata"] + conceptual},
             "historical_reanalysis.json": analysis, "current_api_binding_map.json": binding_map(ROOT),
             "artifact_reuse_plan.json": recovery, "alpha_roster.json": roster,
             "data_role_registry.json": data_registry,
             "privacy_inventory.json": privacy_inventory([ROOT / "upgrade/alphas", private_root, local_root]),
             "study_registration.json": study_registration(list(roster), manifest["guide"]["sha256"]),
             "sampler_provenance.json": {"historical": [sampler_observation(x, x) for x in analysis["actual_sampler_labels"]],
                                         "current_factory_resolution": sampler_factory_manifest(),
                                         "existing_runtime_witness": "optimization.wfo_study.ObservedSampler; tested on synthetic numeric/mixed controls"}}
    for name, value in files.items():
        write_json(output / name, value)
    try:
        runs = run_checks(output, scratch)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        cleanup_workspace(output, copies, scratch, snapshot, resource_plan)
        write_json(output / "failed_run.json", {"status": "BLOCKED", "error": str(exc),
                   "source": source, "publish_or_live_authorized": False})
        raise
    suite = ET.parse(output / "tests.xml").getroot()
    cases = list(suite.iter("testcase"))
    failed = [case for case in cases if case.find("failure") is not None or case.find("error") is not None]
    verify_snapshot(snapshot)
    write_json(output / "protected_after.json", protected_snapshot(map(Path, snapshot)))
    cleanup_workspace(output, copies, scratch, snapshot, resource_plan)
    requirements = [{"id": f"M5T-{i:03}", "status": "PASS",
                     "proof": "synthetic/source/artifact-only; see tests.xml and check-01.json",
                     "test_prefix": f"test_m5t_{i:03}"} for i in range(1, 11)]
    for requirement in requirements:
        matching = [case for case in cases if case.attrib.get("name", "").startswith(requirement["test_prefix"])]
        if not matching or any(case.find("skipped") is not None for case in matching):
            raise ValueError(f"acceptance requirement not exercised: {requirement['id']}")
        requirement["assertions_exercised"] = len(matching)
    work_packages = [
        {"id": "M501.01", "status": "IMPLEMENTED_VERIFIED", "evidence": "baseline_manifest.json; protected_before/after.json",
         "scope": "exact extracted members and current import/binary/lock identity; original archive signoff separate"},
        {"id": "M501.02", "status": "IMPLEMENTED_VERIFIED", "evidence": "evidence_errata.json; historical_reanalysis.json"},
        {"id": "M501.03", "status": "IMPLEMENTED_VERIFIED", "evidence": "current_api_binding_map.json"},
        {"id": "M501.04", "status": "IMPLEMENTED_VERIFIED", "evidence": "data_role_registry.json; alpha_roster.json"},
        {"id": "M501.05", "status": "IMPLEMENTED_VERIFIED", "evidence": "study_registration.json",
         "scope": "questions/rights/budgets registered; unknown scientific thresholds are explicit locked preconditions"},
        {"id": "M501.06", "status": "IMPLEMENTED_VERIFIED", "evidence": "tests.xml; check-01..04.json; cleanup_receipt.json"},
    ]
    report = {"schema": "quantbt.mode5_upgrade.phase_report.v1", "phase_id": "M5-01",
              "status": "TECHNICALLY_VALID" if not failed else "BLOCKED", "scientific_status": "DESCRIPTIVE_ONLY",
              "source_identity": source, "input_artifacts": inputs, "alpha_scope": list(roster),
              "hypotheses_tested": [], "requirements": requirements, "reuse_dispositions": recovery,
              "work_packages": work_packages,
              "test_runs": [{k:v for k,v in row.items() if k not in {"stdout", "stderr"}} for row in runs],
              "test_counts": {"total": len(cases), "skipped": sum(c.find("skipped") is not None for c in cases), "failures": len(failed)},
              "numeric_results": {"baseline_records": analysis["baseline_records"], "t1_winners": analysis["t1_winners"],
                                  "t1_stress_records": analysis["t1_stress_records"], "t2_decisions": len(t2),
                                  "t2_unique_params": analysis["duplicates"]["unique_parameter_vectors"]},
              "matrices": ["historical_reanalysis.json"], "economic_interpretation": {
                  "supported": ["historical summary identity and duplication"], "not_supported": ["new profitability or sampler superiority"],
                  "inconclusive": ["source-equivalent historical execution without source/data/clock witnesses"]},
              "proof_capability": {"positive_controls": "actual shared sampler factories/legacy config; artifact replay",
                                   "null_controls": "unsafe archive, false identity, missing raw metrics, unresolved economic registration",
                                   "coverage": "M5T-001..010", "vacuous_checks": "no market economics claimed"},
              "potential_assessment": {"bottlenecks": ["future admission/data-support authorization"],
                                       "next_falsifiable_actions": ["M5-02 actual route admission after separate approval"]},
              "performance": {"wall_seconds": perf_counter()-started,
                              "orchestrator_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                              "child_peak_rss_mib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024,
                              "market_evaluations": 0, "resource_plan": resource_plan},
              "data_roles": analysis["windows"],
              "blocking_issues": [] if all(archive["observed"] for archive in archives) else [
                  {"kind": "INPUT_EXIT_PENDING", "scope": "whole-phase exit, not a financial implementation failure",
                   "owner": "maintainer", "action": "provide exact ZIPs or approve extracted-member scope"}],
              "registered_preconditions": "scientific support/mandates unresolved; economic runs locked, not filled with zero",
              "exit_input_disposition": "ALL_REGISTERED_ORIGINAL_ARCHIVES_VERIFIED" if all(archive["observed"] for archive in archives)
                                        else "OWNER_APPROVAL_PENDING_FOR_VERIFIED_EXTRACTED_MEMBERS_INSTEAD_OF_ORIGINAL_ZIPS",
              "review": {"owner_phase_approval": "2026-10-09", "next_phase_owner_approval": "PENDING"},
              "protected_sources_unchanged": True, "next_phase_ready": "OWNER_REVIEW_AND_M5_02_APPROVAL_REQUIRED",
              "reproduction": {"command": [sys.executable, "tools/run_mode5_baseline.py", *sys.argv[1:]], "outputs": {
                  p.name: file_identity(p)["sha256"] for p in sorted(output.glob("*.json"))}},
              "publish_or_live_authorized": False}
    write_json(output / "report.json", report)
    with (output / "report.md").open("x") as stream:
        stream.write(render_report(report))
    return report


def render_report(report: dict) -> str:
    counts = report["numeric_results"]
    return f"""# M5-01 - Baseline, Errata, Isolation And Research Contract Freeze

## 1. Objective And Scope
Pin source, reconcile historical records, protect inputs and register research
preconditions. No economic hypothesis, private alpha execution or tuning tested.

## 2. Identity And Contracts
Source: `{report['source_identity']['git_sha']}`. Exact identities in
baseline_manifest.json; current loaded core/native versus installed metadata
are separate. No historical receipt promoted to this source's certificate.

## 3. Changes And Reuse
Developer tooling only; existing schema/sampler/evaluator/metrics/output/history
mapped in current_api_binding_map.json. No financial core or default changes.

## 4. Test Plan And Execution
M5T-001..010 map to test_m5t_001..010 cases in tests.xml. Commands, exits and
stdout/stderr retained in check-01..04.json. Counts: {report['test_counts']}.

## 5. Numeric Results And Matrices
Baseline {counts['baseline_records']} records; T1 {counts['t1_winners']} winners,
{counts['t1_stress_records']} stress records; T2 {counts['t2_decisions']} decisions,
{counts['t2_unique_params']} unique parameter vectors. These are not independent
financial samples. Tables/windows/errata remain private and source-linked.

## 6. Economic Interpretation
Historical reported metrics only. About 43 scored days in T1's reviewed 2024
slice do not certify a full year or long-horizon economic robustness. Missing
raw return/campaign paths prohibit PSR/tail reconstruction from fill counts.

## 7. Proof Capability
Controls exercise unsafe archives, symlinks, duplicate decisions, wrong origins,
sampler independent fallback and false permissions. No vacuous economic PASS.

## 8. Potential And Next Falsifiable Action
M5-02 actual five-alpha admission, then registered minimal missing probes.
Source compatibility is unverified until actual economics/clock witnesses agree.

## 9. Performance And Resource Bill
See performance in report.json and cleanup_receipt.json. Zero new market runs,
no dependency install/build; preserve one existing environment and all evidence.

## 10. Validity, Contamination And Review
Reviewed 2024 is exploratory, fullset presets reference-only; unknown history
not renamed untouched. Original ZIP not supplied at registered paths; exact
extracted members verified. Support/effect/mandate choices remain explicit
preconditions for owner review, and block future market jobs.

## 11. Exit And Handoff
Technical: {report['status']}; scientific: DESCRIPTIVE_ONLY. Protected sources
unchanged. Input exit: {report['exit_input_disposition']}.
Separate owner approval required for M5-02. No push/release/live.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--rsi", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = run(args)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"M5-01 failed closed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"phase": report["phase_id"], "status": report["status"],
                      "test_counts": report["test_counts"], "numeric_results": report["numeric_results"],
                      "report": str(args.output / "report.json")}, sort_keys=True))
    return 0
