"""Read-only Mode 5 requirement evidence inventory; never a package certificate."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
import xml.etree.ElementTree as ET


GUIDE = "upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md"
GUIDE_SHA256 = "661a2a3d83eed2b2592bfb98e3b4f8e3aa34bcd9740ec6b50c812f73753b99fe"
PRIVATE = "upgrade/private/mode5_upgrade_v1/"
PUBLIC = "docs/mode5/evidence/"
MAX_BYTES = 8 * 1024 * 1024
REPORT_FIELDS = (
    "schema", "phase_id", "status", "scientific_status", "source_identity",
    "input_artifacts", "alpha_scope", "hypotheses_tested", "requirements",
    "reuse_dispositions", "test_runs", "numeric_results", "matrices",
    "economic_interpretation", "proof_capability", "potential_assessment",
    "performance", "data_roles", "blocking_issues", "review",
    "protected_sources_unchanged", "reproduction", "next_phase_ready",
)


@dataclass(frozen=True)
class HistoricalPhase:
    report: str
    seal: str
    seal_sha256: str
    receipt: str
    xml_sha256: str
    command_sha256: str
    source_scope: str


# Hashes are of retained receipts, not newly executed assertions or current code.
PHASES = (
    HistoricalPhase("M5_01_BASELINE_REPORT.md", "m5-01.json",
        "1e9a5f9b3d05eb498f2fe125ebc64297a2e7e55c069a16f90afb9b53ec4a4148",
        "m5-01/attempt-04/tests", "3ab2a302fda1126d8785a769e7ecba00848b4f5816827c1d10c784b81365632c",
        "09a5c3461ce75b2cdb0b5383158b3268fe41999298d6ee070031845bf68cd4ea",
        "source/helper/artifact controls; extracted-member exit approved separately"),
    HistoricalPhase("M5_02_ADMISSION_REPORT.md", "m5-02.json",
        "92ed2a0dd505f274ea70053cd959782f4275aa05f4d50cbb1cbac3dc8bd8be76",
        "m5-02/attempt-04/contracts-final-04", "0de04b40d6ee4693d0e70c261990b89fe6257b64689b9d9de9b54747aa9542b7",
        "ff6624299ffd7027aecb5adf33c221efea373cfaeb67b7cc15a3882dbf08d144",
        "actual five-alpha binding admission; short reviewed window, not economic transfer"),
    HistoricalPhase("M5_03_STATISTICS_REPORT.md", "m5-03.json",
        "bb822500528ec2a9a09922f9d33757a16bbb34e9bb8a0537f5d42aa372220e98",
        "m5-03/attempt-01/contracts-05", "f4d967f446d24a85bf6a1a093d05c68fa963078e334799e4ab96d3db16fde06f",
        "37d8a39101b4552d1b849a2defb28e2fc3291cb95a36584802484746776b8612",
        "metric/oracle and synthetic financial streams; not a trading performance certificate"),
    HistoricalPhase("M5_04_REUSE_REPORT.md", "m5-04-final.json",
        "e06c6a488466c6f71d986f61516cec9acdbd47cc65a7602be0ee3a00fa164e1d",
        "m5-04/attempt-02/regression-01", "ab09db291dd923ed380b92c221aea5452ed7c0123112809b1ae20f2b0908733c",
        "ed164550fd402f0667e2bcc68bce8146ea432ecb39713b373fa6db0a275013fe",
        "planner/cache/rights/audit controls; stored history is not an adaptive rerun"),
    HistoricalPhase("M5_05_ENVIRONMENT_REPORT.md", "m5-05.json",
        "50c28bd3dbf4cc29b0ab3da6d5f6dd43beacd48473a5339e20aaee9d9343eeb6",
        "m5-05/attempt-01/contracts-final", "f11a8b4d71f978654ffb32d49b5f7d8282ff056647deb928ea6c34c427d060c5",
        "94204d30b08e3dad3e8a488ddc8e4cbaaf60ac9a99876f15e48a027f87891d0a",
        "environment rights, continuous attribution and explicit reset controls"),
    HistoricalPhase("M5_06_GEOMETRY_REPORT.md", "m5-06.json",
        "0d14cd06721dde1a731ed266c3e4ebcd321ceaf35ccdfb4110b7537e82687427",
        "m5-06/attempt-01/contracts-source-final", "657739716b56bae736a792e3ff94897cdb35ce8e2785873979ac09341a3a8778",
        "d4f0ab9f452212efc24fb71d7ddc3b21b66358955780f2f7413cc07031286598",
        "feasible geometry and finite probes; no all-alpha global sensitivity or basin guarantee"),
    HistoricalPhase("M5_07_SELECTION_REPORT.md", "m5-07.json",
        "845827491cba3cad16dbd276001ebde9183ac7083705d1edaa1ef424d319f846",
        "m5-07/attempt-01/contracts-audit-final", "c3f27434ee237f154ebf71126057e1df90ada961c24b0cad332eec133a987a12",
        "0f0a2b25f1c53dfca91a7a26bdb894269373d1e5546aa39bfa5404707dd9547c",
        "versioned formulas and selector arithmetic; guide math assertions are not market observations"),
    HistoricalPhase("M5_08_BATTERY_REPORT.md", "m5-08.json",
        "bc8663a3ac44ef5e90236aceeb0eba3b1b21e5890cad649715776efcbc0ba937",
        "m5-08/attempt-01/contracts-05", "a9da4ac7022f6265e6364716ca945c113e8223c1c2b26819337961c6a422a81c",
        "3897a2a765d01ed05abd056a44eef0b401012dfb7bf996b3c857c0f57ec68c08",
        "registered targeted diagnostics; later studies have distinct scope and access history"),
    HistoricalPhase("M5_09_DOSSIER_REPORT.md", "m5-09.json",
        "66b3e6c4fec5f893927f3f46f77c1cfd07d88a2d90fb9aa8551d99d1ac2640b3",
        "m5-09/attempt-01/regression-02", "f51d43576368e3f146d9961b0c48dbd5d7db3dbfea9549ac07a9e5f11b0cc425",
        "e4caf7a14f6c4d3f03a6866b4a63e9f3612b143a817c45c8f1c0aa81c74a8695",
        "dossier/plan/advisory governance; no automatic router qualification"),
    HistoricalPhase("M5_10_PUBLIC_RUNTIME_REPORT.md", "m5-10.json",
        "440716e1dc09736e8e63daf68f5387dd7e8a823814727529dd7d2abab05a1084",
        "m5-10/attempt-01/mode5-final-14", "cc70d7db200252457b9a21d0a545280e2c114add03dee6554c5a30191d31efe9",
        "8645b076461107e49dcdc7572614a2b791791bb9c1a5f8efec880ee71e7bbd6c",
        "historical opt-in runtime and installed pair; not the ACC-repaired final artifact"),
    HistoricalPhase("M5_11_ECONOMIC_REPORT.md", "m5-11.json",
        "4103e4b8b9bd7df7b37c57a6be4e1ff3243f5939da0ecb214d27fc40f17c4ed6",
        "m5-11/attempt-01/economics-final-06", "216c41892def9262a3fad53eefc0c624452fdf370d5b5274d5e767fc8edfc296",
        "26725da30d4792313d8666f09cd6da401d0a04b54ea57762c18c461f550f5bcc",
        "historical finite exploratory pilot; accepted parent ledger supplies the subsequent scope disposition"),
)

# These requirements do not embed their guide ID in the actual test name.
# Every name is exact before pytest's parameter suffix, never a module-wide count.
ALIASES = {
    91: ("test_sampler_only_legacy_mode5_does_not_activate_opt_in",
         "test_walkforward_phase2_mode_1_decay_optimizes_with_optuna_and_records_ledger",
         "test_walkforward_phase3_mode_2_sbb_optimizes_and_records_bootstrap_metrics",
         "test_walkforward_phase3_flat_minima_selector_prefers_dense_cluster_over_sharp_peak",
         "test_walkforward_mode4_is_only_robust_runs_without_oos_selection",
         "test_walkforward_mode5_full_robust_uses_whole_history_without_oos_claim",
         "test_phase74_native_prepared_public_modes_preserve_selection_and_final_account"),
    92: ("test_actual_inherited_sampler_and_no_meta",),
    93: ("test_tpe_conditional_categorical_actual_effective_rows",),
    94: ("test_cma_categorical_reject_and_explicit_fallback",),
    95: ("test_sobol_actual_sequence_projection_and_collision_ledger",),
    96: ("test_ask_tell_schedule_deterministic_and_distinct",
         "test_prepared_and_fresh_public_work_preserve_candidate_scores"),
    97: ("test_old_objective_score_is_never_imported",),
    98: ("test_actual_public_selection_and_replay", "test_adaptive_requires_explicit_researcher_choice"),
    99: ("test_public_lifecycle_uses_original_fills_not_proxy",),
    100: ("test_actual_execution_window_public_selection_and_audit",),
    101: ("test_full_sample_parent_cannot_gain_independent_claim_from_child",),
    102: ("test_reviewed_2024_never_becomes_clean_holdout_by_new_label",),
    103: ("test_future_or_immature_input_blocks_entire_prefix",
          "test_complete_prefix_proof_is_not_whole_recipe_validation"),
    104: ("test_cached_reviewed_execution_is_not_a_new_post_freeze_run",),
    105: ("test_turnover_allocation_cost_mde_is_account_bps_not_position_bps",),
    106: ("test_lower_is_alone_cannot_pass_joint_forward_gate",),
    107: ("test_pf_zero_denominator_or_profit_never_gets_epsilon",
          "test_same_vector_decay_matches_direct_difference_and_log_pf"),
    108: ("test_capable_positive_control_and_harmful_control",
          "test_interval_crossing_hurdle_is_inconclusive_without_retuning"),
    109: ("test_fee_stress_changes_future_decisions_via_actual_equity",),
    110: ("test_missing_ledger_or_required_origins_cannot_be_pooled_away",),
}

SUPPLEMENTS = {
    48: ("m5-05/attempt-01/review-final.json",),
    58: ("m5-06/attempt-01/finalize-source-final/parameter_activity_matrix.json",),
    72: ("m5-08/attempt-01/sampler_comparison.json",),
    75: ("m5-08/attempt-01/risk_controls.json",),
    77: ("m5-08/attempt-01/analysis-v1/hma_targeted_transfer.json",),
    100: ("m5-10/attempt-01/certification.json",),
    101: ("m5-11/attempt-01/claim_report.json",),
    104: ("m5-11/attempt-01/actual_access_rights.json",),
    109: ("m5-11/attempt-01/stress.json",),
}
SUPPLEMENT_PINS = {
    "m5-08/attempt-01/analysis-v1/hma_targeted_transfer.json":
        "0ce081bc6d40ef4c250124bf37a8185d693905cf19c52e54038c750c0e33ec93",
}

M512_RELATED = {
    111: (39, 96), 112: (37, 72), 113: (), 114: (30, 87, 98),
    115: (7, 100), 116: (36, 49, 89), 117: (40, 96),
    118: (2, 7), 119: (), 120: (),
}

CURRENT_GATES = {
    111: "Current matched public/prepared cold/warm/output cost, or an explicitly bounded performance claim",
    112: "Final work ledger: proposals, executions, effective candidates and dependent observations kept separate",
    113: "Fresh-process reconstruction of final reports from sealed, hash-bound inputs",
    114: "Final report semantic/override/decision-digest reconciliation, not only JSON parsing",
    115: "Exact final wheel and sdist consumers outside checkout, with actual module/resources/native provenance",
    116: "Narrowed-rights reload tests on the final supported report/cache/pack paths",
    117: "Final affected cancellation/partial-output/audit-flush/stale-handle regression with retained failures",
    118: "Final source/protected input/privacy/branch and artifact identity checks; no release authority inferred",
    119: "Final phase-report schema and proof/potential/reproduction review; counts alone rejected",
    120: "Main source-bound handoff reconciles these 120 rows, twelve reports, product gates and approved limits",
}
SCOPED_DISPOSITIONS = {
    2: ("VERIFIED_EXISTING", "m5-01-exit-review.json",
        "Owner accepts guide plus hash-verified extracted members; original ZIP hashes were not locally remeasured"),
    58: ("INSUFFICIENT_EVIDENCE_WITH_PLAN", "m5-11-parent-disposition.json",
         "Finite-panel/local observations retained; all-alpha global structured sensitivity is not certified"),
    60: ("INSUFFICIENT_EVIDENCE_WITH_PLAN", "m5-11-parent-disposition.json",
         "Unmet held-probe radii remain insufficient, not basin PASS; adverse neighbors retained"),
    88: ("DEFERRED_APPROVED", "m5-11-parent-disposition.json",
         "Explicit advisory is supported; no learned automatic router or universal recipe promotion"),
    103: ("DEFERRED_APPROVED", "m5-11-parent-disposition.json",
          "Bounded registered prefix checks exist; broader whole learned-procedure qualification stays NOT_EVALUATED"),
    104: ("INSUFFICIENT_EVIDENCE_WITH_PLAN", "m5-11-parent-disposition.json",
          "Reviewed/exploratory data cannot become untouched independent confirmation"),
    110: ("DEFERRED_APPROVED", "m5-11-parent-disposition.json",
          "Accepted completed scopes with limits; no eligible HMA formal cohort in tested panel/mandate; no blanket superiority"),
}

PRODUCTS = {
    "diagnostics_first_admission": (31, 36, 39, 81, 82, 89, 90),
    "five_axes_six_matrices": (24, 27, 44, 46, 47, 55, 58, 71, 77, 85, 110),
    "sensitivity_advice": (11, 14, 51, 54, 56, 57, 58, 60),
    "dual_environments": (41, 42, 43, 44, 45, 46, 48, 49, 50),
    "psr_tail_regret": (21, 22, 23, 25, 28, 29, 30, 61, 63, 64, 67),
    "local_robustness": (53, 55, 59, 60, 65, 66, 70),
    "pareto_compromise": (68, 69, 73),
    "advisory_not_automatic_routing": (76, 80, 83, 84, 86, 87, 88, 103, 104),
    "public_mode5_and_legacy": tuple(range(91, 101)),
    "research_reproducibility": (2, 7, 8, 37, 40, 78, 79, 102, 112, 113, 118, 119, 120),
}


def _bytes(root: Path, name: str) -> bytes:
    rel = PurePosixPath(name)
    if rel.is_absolute() or not rel.parts or any(p in (".", "..") for p in rel.parts) or "\\" in name:
        raise ValueError("repository-relative evidence path required")
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("evidence symlink refused")
    if not path.is_file():
        raise FileNotFoundError(name)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("evidence exceeds bounded reader")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("evidence grew beyond bounded reader")
    return raw


def _ref(root: Path, name: str, expected: str | None = None) -> dict[str, Any]:
    try:
        raw = _bytes(root, name)
    except FileNotFoundError:
        return {"path": name, "status": "MISSING", "sha256": None, "bytes": None}
    digest = sha256(raw).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"immutable receipt changed: {name}")
    return {"path": name, "status": "RETAINED", "sha256": digest, "bytes": len(raw)}


def _json(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("evidence JSON must be an object")
    return value


def _checked_bytes(root: Path, reference: dict[str, Any]) -> bytes:
    raw = _bytes(root, reference["path"])
    if sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("evidence changed during readback")
    return raw


def guide_requirements(text: str) -> tuple[dict[str, Any], ...]:
    if '# Phụ lục B — 120 mandatory acceptance requirements' not in text:
        raise ValueError("authoritative Appendix B register missing")
    section = text.split('# Phụ lục B — 120 mandatory acceptance requirements', 1)[1]
    section = section.split('# Phụ lục C', 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [s.strip() for s in line.split("|")]
        if len(cells) < 6 or not re.fullmatch(r"`M5T-\d{3}`", cells[1]):
            continue
        number = int(cells[1][5:-1])
        rows.append(dict(id=f"M5T-{number:03d}", number=number,
                         phase=f"M5-{(number - 1) // 10 + 1:02d}",
                         kind=cells[2], scenario=cells[3], required_assertion="|".join(cells[4:-1])))
    if [r["number"] for r in rows] != list(range(1, 121)):
        raise ValueError("guide must contain each of the 120 ordered requirements exactly once")
    return tuple(rows)


def _read_run(root: Path, phase: HistoricalPhase) -> dict[str, Any]:
    xml_name = PRIVATE + phase.receipt + ".xml"
    command_name = PRIVATE + ("m5-01/attempt-04/check-01" if phase.receipt.endswith("/tests")
                              else phase.receipt) + ".json"
    xml_ref = _ref(root, xml_name, phase.xml_sha256)
    command_ref = _ref(root, command_name, phase.command_sha256)
    result = dict(xml=xml_ref, command_receipt=command_ref, cases=[], exit_code=None,
                  command_recorded=False, suite_clean=False)
    if xml_ref["status"] != "RETAINED" or command_ref["status"] != "RETAINED":
        return result
    record = _json(_checked_bytes(root, command_ref))
    result["exit_code"] = record.get("exit_code")
    command = record.get("command")
    result["command_recorded"] = bool(isinstance(command, list) and command
        and all(isinstance(s, str) for s in command) and Path(xml_name).name in " ".join(command))
    raw = _checked_bytes(root, xml_ref)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entity declarations refused")
    tree = ET.fromstring(raw)
    if tree.tag not in ("testsuite", "testsuites"):
        raise ValueError("JUnit root required")
    cases = list(tree.iter("testcase"))
    bad_counts = any(int(node.get(key, "0")) != 0 for node in tree.iter()
                     if node.tag in ("testsuite", "testsuites")
                     for key in ("failures", "errors", "skipped"))
    result["suite_clean"] = bool(cases) and not bad_counts and not any(
        e.tag in ("failure", "error", "skipped") for e in tree.iter())
    # Parameter suffixes can contain private values: never export them or logs.
    result["cases"] = [dict(classname=c.get("classname", ""),
        name=c.get("name", "").split("[", 1)[0],
        passed=not any(x.tag in ("failure", "error", "skipped") for x in c)) for c in cases]
    return result


def assertion_matches(number: int, case: dict[str, Any]) -> bool:
    tagged = re.match(r"test_m5t_?0*(\d+)(?:_|$)", case["name"], flags=re.I)
    return bool((tagged and int(tagged.group(1)) == number)
                or case["name"] in ALIASES.get(number, ()))


def requirement_evidence(row: dict[str, Any], run: dict[str, Any],
                         artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    matching = [case for case in run["cases"] if assertion_matches(row["number"], case)]
    complete = bool(matching) and all(c["passed"] for c in matching)
    sound_run = (run["exit_code"] == 0 and type(run["exit_code"]) is int
                 and run["command_recorded"] and run["suite_clean"])
    # M5T-077 is the named retained HMA/T1/T2 transfer reanalysis, not a unit ID.
    observed = row["number"] == 77 and artifacts and all(a["status"] == "RETAINED" for a in artifacts)
    state = ("HISTORICAL_ASSERTIONS_RECORDED" if complete and sound_run else
             "RETAINED_REANALYSIS_NOT_NEW_EXECUTION" if observed and sound_run else
             "INSUFFICIENT_RECORDED_ASSERTIONS")
    return dict(row, evidence_state=state,
        assertions=sorted({c["classname"] + "::" + c["name"] for c in matching}),
        executed_parameter_cases=len(matching),
        historical_run={k: v for k, v in run.items() if k != "cases"},
        supplemental_artifacts=artifacts,
        current_installed_qualification="NOT_INFERRED_FROM_HISTORICAL_RECEIPTS",
        independent_market_validation="NOT_ESTABLISHED_BY_THIS_REQUIREMENT_MAPPING")


def validate_phase_report(report: dict[str, Any]) -> None:
    """Validate Appendix D.2 fields for new canonical reports, not old receipts."""
    missing = set(REPORT_FIELDS).difference(report)
    if missing:
        raise ValueError("missing phase report fields: " + ", ".join(sorted(missing)))
    if report["schema"] != "quantbt.mode5_upgrade.phase_report.v1":
        raise ValueError("canonical phase report schema required")
    if not re.fullmatch(r"M5-(0[1-9]|1[0-2])", str(report["phase_id"])):
        raise ValueError("canonical phase ID required")
    for key in ("hypotheses_tested", "requirements", "test_runs", "blocking_issues"):
        if not isinstance(report[key], list):
            raise ValueError("list required: " + key)
    for key in ("proof_capability", "potential_assessment", "reproduction"):
        if not isinstance(report[key], dict) or not report[key]:
            raise ValueError("substantive report section required: " + key)
    proof = report["proof_capability"]
    if not all(key in proof for key in ("positive_controls", "null_controls", "coverage", "vacuous_checks")):
        raise ValueError("proof capability must expose controls, coverage and vacuous checks")
    if not any(key in report["reproduction"] for key in ("command", "commands", "harness", "receipts")):
        raise ValueError("reproduction locator required; a test count is insufficient")
    if not any(report["reproduction"].get(key) for key in ("command", "commands", "harness", "receipts")):
        raise ValueError("empty reproduction locator")
    if not all(key in report["potential_assessment"] for key in (
            "evidence", "bottlenecks", "next_falsifiable_actions")):
        raise ValueError("potential assessment must disclose evidence, limits and next actions")


def build_inventory(root: Path, *, current_reports: tuple[str, str] | None = None) -> dict[str, Any]:
    """Reconcile known receipts without imports, subprocesses, simulation or writes."""
    root = root.resolve(strict=True)
    guide_ref = _ref(root, GUIDE, GUIDE_SHA256)
    if guide_ref["status"] != "RETAINED":
        raise ValueError("authoritative guide required")
    requirements = guide_requirements(_checked_bytes(root, guide_ref).decode("utf-8"))
    rows, phases = [], []
    for number, phase in enumerate(PHASES, 1):
        seal_ref = _ref(root, PUBLIC + phase.seal, phase.seal_sha256)
        seal = _json(_checked_bytes(root, seal_ref)) if seal_ref["status"] == "RETAINED" else {}
        run = _read_run(root, phase)
        for row in requirements[(number - 1) * 10:number * 10]:
            artifacts = [_ref(root, PRIVATE + p, SUPPLEMENT_PINS.get(p))
                         for p in SUPPLEMENTS.get(row["number"], ())]
            item = requirement_evidence(row, run, artifacts)
            if row["number"] == 91:
                regression = replace(phase, receipt="m5-10/attempt-01/regression-final-08",
                    xml_sha256="cc9e1cfd01ac507254cc4e687b5a607443f0b87922c7b60586f1a5c117dd3121",
                    command_sha256="d21c24853e5544a3c8f792275150c99b77a646c6454d39ac2fb4027a14ae5f67")
                extra = requirement_evidence(row, _read_run(root, regression), [])
                item["legacy_mode_regression"] = extra
            item["historical_scope"] = phase.source_scope
            if row["number"] in SCOPED_DISPOSITIONS:
                disposition, authority, limit = SCOPED_DISPOSITIONS[row["number"]]
                item["approved_research_limit"] = dict(disposition=disposition,
                    authority_receipt=PUBLIC + authority, scope=limit,
                    numerical_correctness_waived=False, independent_validation_granted=False)
            if artifacts and any(a["status"] != "RETAINED" for a in artifacts):
                item["supplement_gap"] = "required supplemental real-data observation missing; control is not market proof"
            rows.append(item)
        phases.append(dict(id=f"M5-{number:02d}",
            markdown=_ref(root, "docs/mode5/" + phase.report), json=seal_ref,
            recorded_status=seal.get("status", seal.get("whole_phase_exit", "SEE_RETAINED_REPORT")),
            recorded_source={k: seal[k] for k in (
                "committed_tested_phase_source", "qualified_phase_commits", "implementation_source_sha",
                "tested_source_head", "qualified_code_commit") if k in seal},
            scope=phase.source_scope, current_installed_certificate=False))
    for row in requirements[110:]:
        rows.append(dict(row, evidence_state="MAIN_CURRENT_QUALIFICATION_REQUIRED",
            assertions=[], historical_run=None, supplemental_artifacts=[],
            related_historical_requirements=[f"M5T-{n:03d}" for n in M512_RELATED[row["number"]]],
            next_required_evidence=CURRENT_GATES[row["number"]],
            current_installed_qualification="OWNED_BY_MAIN_NOT_INFERRED",
            independent_market_validation="NOT_ESTABLISHED_BY_PACKAGE_QUALIFICATION"))
    final = dict(id="M5-12", recorded_status="MAIN_REPORT_NOT_SUPPLIED", scope="current-source local qualification",
                 markdown=None, json=None, current_installed_certificate=False)
    if current_reports is not None:
        md, js = current_reports
        final.update(markdown=_ref(root, md), json=_ref(root, js), recorded_status="MAIN_REPORT_REFERENCED_NOT_CERTIFIED")
        if final["json"]["status"] == "RETAINED":
            validate_phase_report(_json(_checked_bytes(root, final["json"])))
    phases.append(final)
    owners = [
        ("baseline_extracted_members", "m5-01-exit-review.json",
         "d1ce6713f580350f34b93796b331ac592609d2f89f5abf444cf9b78511264eb8"),
        ("parent_research_scope", "m5-11-parent-disposition.json",
         "6b5c822c29af2b968b2a770b927f9a6e25981f61c20b239bcb08bd06d262896c"),
    ]
    return dict(schema="quantbt.mode5.requirement_traceability.v1", guide=guide_ref,
        authority="READ_ONLY_INVENTORY_NOT_EXECUTION_OR_CERTIFICATION",
        requirements=rows, phases=phases,
        state_counts=dict(Counter(row["evidence_state"] for row in rows)),
        owner_dispositions=[dict(id=key, receipt=_ref(root, PUBLIC + name, digest)) for key, name, digest in owners],
        product_gates={key: [f"M5T-{i:03d}" for i in ids] for key, ids in PRODUCTS.items()},
        coverage_inventory=_coverage_inventory(root),
        package_qualified=False, all_120_pass=False, publication_authorized=False,
        main_action="Bind final source, regression, exact artifacts, installed consumers, reconstructed reports and cleanup; do not relabel history")


def _coverage_inventory(root: Path) -> list[dict[str, Any]]:
    facts = (
        ("five_original_alpha_admission", "M5_02_ADMISSION_REPORT.md",
         "actual routes admitted within the recorded contract; not every financial backend or clock"),
        ("five_axis_and_seven_alpha_research", "M5_11_RESEARCH_COVERAGE_DISPOSITION.md",
         "completed registered scopes accepted; HMA has no eligible formal cohort; finite probes and sensitivity retain limits"),
        ("formal_remaining_studies", "M5_11_9_RESEARCH_STATUS.md",
         "nine terminal formal studies; typed feasibility prunes are attempts, not successful financial observations"),
        ("cross_mode_research", "M5_11_13_CHRONOLOGICAL_DISPOSITION_REPORT.md",
         "KEEP_BASELINE; unexecuted broad whole-procedure experiments DEFERRED_APPROVED/NOT_EVALUATED"),
        ("cross_mode_opt_in_and_winner", "../diagnostics/M5_11_15_IMPLEMENTATION_REPORT.md",
         "source-qualified executable donor/winner mechanics; destination rescores coordinates; no universal economic superiority"),
        ("current_account_scope", "../portfolio_review/ACC01_REPORT.md",
         "intentional accounting/config fixes supersede old unchanged-finance claims; gross-cross/netting is not venue-exact isolated/hedge inventory"),
        ("historical_installed_vs_current", "M5_12_PREPARATION.md",
         "earlier installed CPython3.12 receipts are historical; new source/pair/consumers and later remote/public proof remain distinct"),
    )
    result = []
    for key, path, limit in facts:
        # All catalog entries are explicit and normalized before the safe reader.
        normalized = "docs/" + path[3:] if path.startswith("../") else "docs/mode5/" + path
        result.append(dict(id=key, source=_ref(root, normalized), claim_limit=limit,
                           independent_validation="NOT_INFERRED", economic_default_promotion=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--current-report-md")
    parser.add_argument("--current-report-json")
    args = parser.parse_args()
    if bool(args.current_report_md) != bool(args.current_report_json):
        parser.error("both current report paths are required together")
    reports = (args.current_report_md, args.current_report_json) if args.current_report_md else None
    print(json.dumps(build_inventory(args.root, current_reports=reports), sort_keys=True, indent=2,
                     ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
