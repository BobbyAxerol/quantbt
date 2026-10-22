"""Bounded cold reproduction of explicitly public synthetic report evidence.

Run this file with an isolated installed interpreter in a fresh process. It
neither builds artifacts nor changes sys.path. Historical private research is
not an input to this deliberately small, non-financial reproduction sample.
"""

from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from hashlib import sha256
import argparse
import importlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


SCHEMA = "quantbt.m5_12.synthetic_reproduction.v1"
KINDS = ("diagnostics", "mode4", "mode5", "winner")
MAX_FILE_BYTES = 2 * 1024**2
MAX_TOTAL_BYTES = 8 * 1024**2
OWNERS = (
    "quantbt.diagnostics.assessment", "quantbt.diagnostics.report",
    "quantbt.diagnostics.geometry.finite_panel", "quantbt.mode5.geometry.schema",
    "quantbt.diagnostics.decisions.report", "quantbt.diagnostics.decisions.reduction",
    "quantbt.diagnostics.decisions.validation", "quantbt.diagnostics.decisions.render",
    "quantbt.mode5.decision_report", "quantbt.diagnostics.winner.report",
    "quantbt.diagnostics.winner.explanation", "quantbt.diagnostics.winner.render",
)
REQUIRED_VALUES = {
    "diagnostics": ("/coverage/evaluations", "/coverage/unique_effective_candidates",
        "/activity/zero_activity_evaluations", "/analyses/environments/status", "/context/metric_units"),
    "mode4": ("/summary/cohorts/all_calendar/policies/applied/effects/R/mean",
        "/summary/cohorts/all_calendar/policies/applied/effects/Q/mean",
        "/summary/cohorts/all_calendar/policies/applied/helped",
        "/summary/cohorts/all_calendar/policies/applied/harmed", "/payload/family/metric_contract_id"),
    "mode5": ("/selected_params", "/summary/chosen_candidate", "/summary/attempts",
        "/summary/unique_evaluated_candidates", "/summary/objective_unit"),
    "winner": ("/subject/candidate_id", "/annual_summary/environments",
        "/annual_summary/utility/minimum", "/explanation/comparisons/0/objective_delta",
        "/account/status", "/annual_summary/measures/net_return/unit"),
}

# Inventory only. The main qualification runner owns execution and its receipts.
OPERATIONS_TARGETS = {
    "audit_cancel_crash_backpressure": (
        "tests/mode5/test_diagnostic_audit.py::test_m5t_040_slow_sink_backpressure_and_success_after_durable_flush",
        "tests/mode5/test_diagnostic_audit.py::test_m5t_040_cancelled_and_crashed_artifacts_are_partial_not_success",
        "tests/mode5/test_diagnostic_audit.py::test_m5t_040_fsync_failure_has_no_success_marker",
        "tests/mode5/test_public_boundaries.py::test_public_failed_batch_retains_unevaluated_asks_and_releases_context",
    ),
    "stale_handles_and_worker_recovery": (
        "tests/test_phase71_runtime_productization.py::test_native_wfo_budget_handle_generation_cancel_and_replay",
        "tests/native_event/test_phase54a5_prepared_cache_boundary.py::test_prepared_object_cache_clear_refuses_active_pin_and_advances_generation",
        "tests/test_phase76_reactive_wfo.py::test_phase76_worker_death_recovers_with_new_generation_and_no_market_ipc",
        "tests/meta_selection/test_c02_transport.py::test_c02_t01_t04_stale_missing_corrupt_replies_and_child_deadline",
    ),
    "narrowed_rights_and_recipe_failure": (
        "tests/mode5/test_diagnostic_planner.py::test_m5t_036_earlier_cutoff_denies_an_already_cached_mature_record",
        "tests/mode5/test_archive_review.py::test_reload_and_verify_recheck_narrower_or_changed_access",
        "tests/mode5/test_cross_mode_handoff.py::test_donor_plan_reload_rejects_prefix_relabel_and_narrowed_cutoff",
        "tests/mode5/test_dossier_governance.py::test_recipe_fields_cannot_be_implicit",
        "tests/mode5/test_public_boundaries.py::test_missing_seal_prevents_execution",
    ),
    "exact_sampler_not_full_wfo_continuation": (
        "tests/meta_selection/test_c04_checkpoint_safety.py::test_c04_t01_fresh_process_continuation_without_evaluator_during_restore",
        "tests/meta_selection/test_c04_continuation.py::test_c04_t02_batch_order_not_replaced_with_sequential_order",
        "tests/meta_selection/test_c04_continuation.py::test_c04_t05_seed_only_reconstruction_is_not_accepted_as_resume",
        "tests/meta_selection/test_pre04_latent.py::test_fresh_process_continuation",
    ),
}


def _canonical(value):
    from quantbt.mode5.diagnostics.identity import canonical
    return canonical(value)


def _hash(value):
    return sha256(value).hexdigest()


def _strict_json(raw):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("duplicate JSON key: " + name)
            result[name] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def _regular(path, cap=MAX_FILE_BYTES):
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
        raise ValueError("regular non-symlink evidence required")
    if path.stat().st_size > cap:
        raise ValueError("evidence byte budget exceeded")
    with path.open("rb") as stream:
        raw = stream.read(cap + 1)
    if len(raw) > cap:
        raise ValueError("evidence byte budget exceeded")
    return raw


def _access(value):
    from quantbt.diagnostics import AccessPolicy
    policy = AccessPolicy(**dict(value, roles=tuple(value["roles"]), manifests=tuple(value["manifests"])))
    if policy.roles != ("synthetic",) or policy.purpose != "diagnostic":
        raise PermissionError("only explicit public synthetic diagnostic rights are supported")
    return policy


def _owners():
    rows = {}
    for name in OWNERS:
        module = importlib.import_module(name)
        rows[name] = _hash(_regular(module.__file__))
    return rows


def _diagnostics(value, access):
    from quantbt.diagnostics import (AccessWitness, AlphaDiagnostics, DiagnosticAdvice,
        DiagnosticBudget, DiagnosticContext, DiagnosticObservation)
    if set(value) != {"schema", "ranges", "context", "observations", "advice"} or value["schema"] != "m512-diagnostic-inputs-v1":
        raise ValueError("bounded retained diagnostic input schema required")
    context = DiagnosticContext(**dict(value["context"],
        metric_units=tuple(tuple(row) for row in value["context"]["metric_units"])))
    # No new association bootstrap or financial research is authorized here.
    # Its original precomputed matrix can be certified separately by the main.
    if context.outcome_blind_roster:
        raise ValueError("sample rebuild supports reviewed roster only; no new bootstrap")
    pairs = value["ranges"]
    if len(pairs) > 16 or len(dict(pairs)) != len(pairs) or not 1 <= len(value["observations"]) <= 128:
        raise ValueError("bounded distinct ranges and 1..128 retained observations required")
    owner = AlphaDiagnostics(dict(pairs), context=context, access=access,
        budget=DiagnosticBudget(max_observations=128, max_report_bytes=MAX_FILE_BYTES))
    rows = []
    for row in value["observations"]:
        witness = AccessWitness(**row["witness"])
        if witness.role != "synthetic":
            raise PermissionError("real research observations are outside this sample")
        rows.append(DiagnosticObservation.from_params(geometry=owner.geometry,
            **dict(row, witness=witness)))
    advice = tuple(DiagnosticAdvice(**dict(row, evidence_ids=tuple(row["evidence_ids"]),
        missing_evidence=tuple(row["missing_evidence"]))) for row in value["advice"])
    return owner.analyze(rows, advice=advice)


def _private(report, kind):
    if kind == "diagnostics":
        return report.to_dict()
    if kind == "mode4":
        return report.to_dict(private=True, detail=True)
    return report.to_dict(private=True)


def _identity(report):
    return report.record.identity


def _render(report, kind):
    kwargs = {} if kind == "diagnostics" else dict(private=True)
    if kind == "mode4":
        kwargs["detail"] = True
    return {"json": report.to_json(**kwargs).encode("utf-8"),
        "md": report.to_markdown(**kwargs).encode("utf-8")}


def _values(data, expected, kind):
    from quantbt.mode5.dossier.records import pointer
    if not isinstance(expected, dict) or not set(REQUIRED_VALUES[kind]) <= expected.keys() or len(expected) > 64:
        raise ValueError("explicit critical value/unit/support assertions required: " + kind)
    for path, value in expected.items():
        if not path.startswith("/") or _canonical(pointer(data, path)) != _canonical(value):
            raise ValueError("exact retained value mismatch: " + kind + path)


def _build(inputs, accesses, identities):
    from quantbt.diagnostics import ResearchDecisionReport, WinnerQualificationReport, WinnerQualificationRequest
    from quantbt.mode5 import DecisionReport
    from quantbt.diagnostics import AccessWitness

    if set(accesses) != {"diagnostics", "mode4", "winner"}:
        raise ValueError("three explicitly retained access policies required")
    policies = {kind: _access(value) for kind, value in accesses.items()}
    diagnostic = _diagnostics(inputs["diagnostics"], policies["diagnostics"])
    fold = ResearchDecisionReport.from_json(_canonical(inputs["mode4"]))
    fold.authorize(policies["mode4"])
    data = fold.to_dict(private=True, detail=True)
    if data["mode"] != "mode4" or not 1 <= len(data["payload"]["rows"]) <= 16:
        raise ValueError("representative Mode4 sample requires 1..16 fold records")
    if any(row["role"] != "synthetic" for row in data["source_witnesses"]):
        raise PermissionError("only synthetic fold records may be reproduced here")
    decision = DecisionReport.from_json(_canonical(inputs["mode5"]))
    winner = WinnerQualificationReport.from_json(_canonical(inputs["winner"]),
        expected_identity=identities["winner"])
    retained = winner.to_dict(private=True)
    if (retained["checks"] or retained["baseline"]["status"] != "NOT_SUPPLIED"
            or retained["account"]["status"] != "NOT_SUPPLIED"):
        raise ValueError("sample supports retained decision-only winner, not external account/catalog attachments")
    witness = AccessWitness(**retained["witness"])
    if witness.role != "synthetic":
        raise PermissionError("only synthetic winner evidence may be reproduced here")
    winner.verify(decision, access=policies["winner"], witness=witness,
        source_ref=retained["source_ref"], request=WinnerQualificationRequest(include_account=False))
    return dict(diagnostics=diagnostic, mode4=fold, mode5=decision, winner=winner)


@contextmanager
def no_execution():
    """Tripwires for accidental public finance, optimizer or Ridge invocation."""
    from quantbt import QuantBTEndpoint
    from quantbt.walkforward import WalkForwardEngine
    from quantbt.optimization.meta_selection.model import RidgeLearner
    import optuna

    def forbidden(*args, **kwargs):
        raise RuntimeError("reproduction must not execute finance, optimization or model fitting")

    with ExitStack() as stack:
        for owner, name in ((QuantBTEndpoint, "backtest"), (QuantBTEndpoint, "simulate"),
                (WalkForwardEngine, "run"), (RidgeLearner, "fit"),
                (optuna, "create_study"), (optuna.study.Study, "ask")):
            stack.enter_context(patch.object(owner, name, forbidden))
        yield


def seal_synthetic(directory, *, diagnostic_inputs, reports, access, expected_values):
    """Freeze caller-reviewed synthetic evidence before a separate-process run.

    Expected values must be supplied independently by the caller. This function
    does not turn self-generated hashes into independent economic evidence.
    Returned manifest SHA must be retained outside the bundle before reproduction.
    """
    if set(reports) != set(KINDS) or set(expected_values) != set(KINDS):
        raise ValueError("all four representative reports required; no silent partial coverage")
    inputs = {kind: _private(reports[kind], kind) for kind in KINDS}
    inputs["diagnostics"] = diagnostic_inputs
    policies = {kind: asdict(policy) for kind, policy in access.items()}
    identities = {kind: _identity(reports[kind]) for kind in KINDS}
    with no_execution():
        rebuilt = _build(inputs, policies, identities)
    entries = {}
    for kind in KINDS:
        report = rebuilt[kind]
        if _identity(report) != identities[kind]:
            raise ValueError("rebuilt input does not match original report: " + kind)
        _values(_private(report, kind), expected_values[kind], kind)
        raw = _canonical(inputs[kind]).encode("utf-8")
        outputs = _render(reports[kind], kind)
        if len(raw) > MAX_FILE_BYTES or any(len(v) > MAX_FILE_BYTES for v in outputs.values()):
            raise ValueError("per-report byte budget exceeded")
        entries[kind] = dict(file=kind + "-input.json", sha256=_hash(raw), bytes=len(raw),
            identity=identities[kind], values=expected_values[kind],
            outputs={name: dict(sha256=_hash(value), bytes=len(value)) for name, value in outputs.items()})
    manifest = dict(schema=SCHEMA, evidence_classification="SYNTHETIC_CONTROL", public_safe=True,
        access=policies, entries=entries, owners=_owners(),
        producer_pid=os.getpid(),
        scope="representative_reports_only", twelve_phase_reports_rebuilt=False,
        historical_research_recomputed=False, independent_validation=False)
    raw_manifest = _canonical(manifest).encode("utf-8")
    if len(raw_manifest) + sum(r["bytes"] for r in entries.values()) > MAX_TOTAL_BYTES:
        raise ValueError("reproduction bundle byte budget exceeded")
    root = Path(directory).absolute()
    _new_directory(root)
    for kind, row in entries.items():
        with (root / row["file"]).open("xb") as stream:
            stream.write(_canonical(inputs[kind]).encode("utf-8"))
    with (root / "manifest.json").open("xb") as stream:
        stream.write(raw_manifest)
    return dict(path=str(root / "manifest.json"), sha256=_hash(raw_manifest), bytes=len(raw_manifest))


def _new_directory(root):
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("output path may not traverse symlinks")
    root.mkdir(exist_ok=False)


def reproduce(manifest_path, *, expected_sha256, output):
    """Verify externally pinned inputs, rebuild/reduce, then write fresh MD/JSON."""
    raw = _regular(manifest_path)
    if type(expected_sha256) is not str or len(expected_sha256) != 64 or _hash(raw) != expected_sha256:
        raise ValueError("externally pinned manifest SHA256 mismatch")
    manifest = _strict_json(raw)
    required = {"schema", "evidence_classification", "public_safe", "access", "entries", "owners",
        "scope", "producer_pid", "twelve_phase_reports_rebuilt", "historical_research_recomputed", "independent_validation"}
    if (set(manifest) != required or manifest["schema"] != SCHEMA
            or manifest["evidence_classification"] != "SYNTHETIC_CONTROL" or manifest["public_safe"] is not True
            or manifest["scope"] != "representative_reports_only"
            or type(manifest["producer_pid"]) is not int or manifest["producer_pid"] <= 0
            or any(manifest[k] is not False for k in ("twelve_phase_reports_rebuilt",
                "historical_research_recomputed", "independent_validation"))
            or set(manifest["entries"]) != set(KINDS)):
        raise ValueError("complete bounded public synthetic reproduction manifest required")
    if manifest["owners"] != _owners():
        raise ValueError("current report owner bytes differ from sealed reproduction owners")
    inputs, identities, pins = {}, {}, {}
    total = len(raw)
    parent = Path(manifest_path).absolute().parent
    for kind in KINDS:
        row = manifest["entries"][kind]
        if set(row) != {"file", "sha256", "bytes", "identity", "values", "outputs"} or row["file"] != kind + "-input.json":
            raise ValueError("fixed relative evidence filename and complete entry required")
        value = _regular(parent / row["file"])
        total += len(value)
        if total > MAX_TOTAL_BYTES or _hash(value) != row["sha256"] or len(value) != row["bytes"]:
            raise ValueError("input hash/size/bundle budget mismatch: " + kind)
        inputs[kind], identities[kind] = _strict_json(value), row["identity"]
        pins[kind] = dict(sha256=row["sha256"], bytes=row["bytes"])
    with no_execution():
        reports = _build(inputs, manifest["access"], identities)
        rendered = {}
        for kind, report in reports.items():
            row = manifest["entries"][kind]
            if _identity(report) != row["identity"]:
                raise ValueError("rebuilt report identity mismatch: " + kind)
            _values(_private(report, kind), row["values"], kind)
            rendered[kind] = _render(report, kind)
            expected = {name: dict(sha256=_hash(value), bytes=len(value))
                for name, value in rendered[kind].items()}
            if row["outputs"] != expected:
                raise ValueError("rendered numeric/Markdown/JSON bytes differ: " + kind)
    if sum(len(v) for outputs in rendered.values() for v in outputs.values()) > MAX_TOTAL_BYTES:
        raise ValueError("retained output byte budget exceeded")
    # Validate every report before creating output. A partial filesystem write
    # never receives the terminal receipt, which is written exclusively last.
    root = Path(output).absolute()
    _new_directory(root)
    files = {}
    for kind, outputs in rendered.items():
        for suffix, value in outputs.items():
            name = kind + "." + suffix
            with (root / name).open("xb") as stream:
                stream.write(value)
            files[name] = dict(bytes=len(value), sha256=_hash(value))
    # Recheck custody after rendering/writing. Never silently certify a changed input.
    if _hash(_regular(manifest_path)) != expected_sha256 or _owners() != manifest["owners"]:
        raise ValueError("manifest or report owner changed during reproduction")
    for kind, pin in pins.items():
        now = _regular(parent / manifest["entries"][kind]["file"])
        if len(now) != pin["bytes"] or _hash(now) != pin["sha256"]:
            raise ValueError("input changed during reproduction: " + kind)
    receipt = dict(schema=SCHEMA, status="REPRESENTATIVE_REPRODUCTION_VERIFIED",
        evidence_classification="SYNTHETIC_CONTROL", manifest_sha256=expected_sha256,
        report_ids=identities, files=files, process_id=os.getpid(), interpreter=sys.executable,
        fresh_process=os.getpid() != manifest["producer_pid"],
        isolated_interpreter=bool(sys.flags.isolated),
        owner_origins={name: str(Path(importlib.import_module(name).__file__).resolve()) for name in OWNERS},
        owners=manifest["owners"], checked_values={k: manifest["entries"][k]["values"] for k in KINDS},
        new_financial_runs=0, new_optimizer_trials=0, new_model_fits=0,
        twelve_phase_reports_rebuilt=False, historical_research_recomputed=False,
        independent_validation=False, installed_artifact_qualified=False,
        operational_regressions="INVENTORIED_NOT_EXECUTED", publish_or_live_authorized=False)
    with (root / "reproduction.json").open("xb") as stream:
        stream.write(_canonical(receipt).encode("utf-8"))
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True, help="digest retained outside the input bundle")
    parser.add_argument("--output", type=Path, required=True, help="new directory; no overwrites or cleanup")
    args = parser.parse_args(argv)
    raw = _regular(args.manifest)
    if _hash(raw) != args.expected_sha256:
        raise ValueError("externally pinned manifest SHA256 mismatch")
    if _strict_json(raw).get("producer_pid") == os.getpid():
        raise ValueError("CLI qualification requires a process distinct from the producer")
    receipt = reproduce(args.manifest, expected_sha256=args.expected_sha256, output=args.output)
    print(json.dumps(dict(status=receipt["status"], process_id=receipt["process_id"],
        output=str(args.output)), sort_keys=True))


if __name__ == "__main__":
    main()
