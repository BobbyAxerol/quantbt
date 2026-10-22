"""Cold recovery of a completed challenger whose outer JSON export failed.

No provider, sampler, pickle loader or financial engine is imported here.
Historical files stay immutable; the recovered receipt references their bytes.
"""

from datetime import date, datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile

from quantbt.mode5.diagnostics.identity import canonical, digest


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def pin(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(),
            "canonical regular evidence required")
    checksum, size = sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            checksum.update(block)
            size += len(block)
    return dict(path=str(path), bytes=size, sha256=checksum.hexdigest())


def checked(seal):
    require(pin(seal["path"]) == seal, "evidence hash differs: " + seal["path"])
    raw = Path(seal["path"]).read_bytes()
    require(len(raw) == seal["bytes"] and sha256(raw).hexdigest() == seal["sha256"],
            "evidence changed during parse")
    return json.loads(raw)


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if type(value) is dict:
        require(all(type(key) is str for key in value), "string JSON keys required")
        return {key: _plain(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_plain(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise TypeError("unsupported receipt value: " + type(value).__name__)


def write_atomic(path, value):
    """Serialize before writing, publish without replacing any prior receipt."""
    raw = json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("ascii") + b"\n"
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return pin(path)


def recover_completed_floor(spec):
    """Verify an externally sealed cold-recovery spec; return no new finance."""
    parent, tidy = checked(spec["failed_parent"]), checked(spec["failed_cleanup"])
    failure = checked(spec["export_failure"])
    require(parent["status"] == "FAIL_RETAINED" and parent["reason"] is None
            and parent["source_pins_unchanged"] is True
            and parent["all_owned_children_reaped"] is True
            and parent["original_scorer_changed"] is False
            and tidy["status"] == "PASS_CLEANUP_ONLY"
            and tidy["result"] == spec["failed_parent"]
            and tidy["all_owned_children_reaped"] is True,
            "closed failed owner with intact source/cleanup required")
    require(failure["type"] == "TypeError"
            and failure["error"] == "Object of type Timestamp is not JSON serializable"
            and failure["retained_prior_evidence"] is True,
            "only the witnessed receipt serialization failure may be recovered")
    log = parent["log"]
    require(pin(log["path"]) == log
            and failure["error"] in Path(log["path"]).read_text(),
            "original worker log must witness the export failure")
    retained = {item["path"]: item for item in tidy["retained_pins"]}
    require(len(retained) == len(tidy["retained_pins"]), "distinct retained paths required")
    for seal in retained.values():
        require(pin(seal["path"]) == seal, "retained evidence changed")
    require(parent["child_result"] == retained.get(spec["partial_outer"]["path"])
            == spec["partial_outer"]
            and spec["inner_result"] == retained.get(spec["inner_result"]["path"])
            and spec["export_failure"] == retained.get(spec["export_failure"]["path"]),
            "original cleanup must bind complete inner and failed outer bytes")
    try:
        checked(spec["partial_outer"])
    except json.JSONDecodeError:
        pass
    else:
        raise ValueError("historical outer must be the witnessed partial JSON")

    registration = checked(spec["original_run_registration"])
    cold = checked(registration["cold_result"])
    require(cold["status"] == "PASS_COLD_FLOOR_BINDING_REPAIR"
            and cold["artifacts"]["binding"] == spec["binding"],
            "original qualified cold binding required")
    binding = checked(spec["binding"])
    geometry_identity = digest(binding["continuous"]["geometry"])
    for seal in registration["code_pins"]:
        require(pin(seal["path"]) == seal, "original wrapper/provider code changed")
    original = checked(registration["original_registration"])
    require(Path(spec["inner_result"]["path"]).parent
            == Path(registration["output"]) / "challenger"
            and Path(spec["partial_outer"]["path"]).parent == Path(registration["output"]),
            "inner and failed outer must belong to the original registered run")
    require(original["provider_sources"] == spec["source_manifest"],
            "exact original financial source manifest required")
    sources = checked(spec["source_manifest"])
    source_pins = sources["source_pins"]
    require(len({item["path"] for item in source_pins}) == len(source_pins),
            "distinct original source paths required")
    for seal in source_pins:
        require(pin(seal["path"]) == seal, "original financial source changed")

    inner = checked(spec["inner_result"])
    checkpoint, outcome, counts, audit = (inner[key] for key in
        ("checkpoints", "outcome", "actual_counts", "audit"))
    require(inner["arm"] == "environment_floor_mean_v1" and inner["annual_resets"] == 0
            and inner["old_panel_imported_as_trials"] is False
            and inner["final_endpoint_accounts_completed"] == inner["direct_owner_completed"] == 1
            and outcome["status"] == "SELECTED_REPLAY_VERIFIED"
            and outcome["annual_account_resets"] == 0
            and outcome["deployment_authorized"] is False,
            "completed original floor/selected replay, not a partial study, required")
    require(checkpoint["attempts"] == 256 and checkpoint["states"] == {"COMPLETE": 256}
            and checkpoint["budget_complete"] is True and checkpoint["coverage_issue"] is False
            and checkpoint["unique_effective_proposals"] == checkpoint["unique_executed_points"] == 256,
            "256 complete distinct original trials required")
    directory = Path(spec["inner_result"]["path"]).parent
    study_pin = retained.get(str(directory / "study.json"))
    require(study_pin is not None and checked(study_pin) == outcome,
            "durable study outcome differs from completed inner receipt")
    trials, accounts, rows = (checkpoint[key] for key in
        ("trial_checkpoints", "accounts", "runtime_trial_ledger"))
    require(len(trials) == len(rows) == 256 and len(accounts) == 257
            and rows == outcome["trial_ledger"], "ordered durable trial/account ledger required")
    observed = {}
    for account in accounts:
        require(account["account"] == retained.get(account["account"]["path"])
                and account["metadata"] == retained.get(account["metadata"]["path"])
                and account["financial_execution_count"] == 1, "one retained original account per query")
        record = checked(account["metadata"])
        observation = record["observation"]
        execution = observation["execution"]
        require(record["account"] == account["account"]
                and record["evaluation_identity"] == observation["identity"] == account["evaluation_identity"]
                and record["query_id"] == account["query_id"]
                and observation["request_identity"] == execution["request_identity"]
                and outcome["continuous_observations"].get(account["query_id"]) == observation
                and execution["effective_params_identity"] == account["point_identity"]
                and observation["annual_account_resets"] == 0
                and observation["financial_execution_count"] == execution["financial_execution_count"] == 1,
                "immutable account lineage/count/continuous policy differs")
        require(account["query_id"] not in observed, "duplicate query cannot increase coverage")
        observed[account["query_id"]] = account["point_identity"]
    require(set(outcome["continuous_observations"]) == set(observed)
            and outcome["continuous_account_retention"]["count"] == 257
            and outcome["continuous_account_retention"]["entries"]
            == [{key: account[key] for key in ("query_id", "evaluation_identity")} for account in accounts],
            "terminal retained account roster differs")
    proposals, parameter_vectors = set(), set()
    for index, (seal, row) in enumerate(zip(trials, rows)):
        require(seal == retained.get(seal["path"]), "trial missing from original cleanup")
        trial = checked(seal)
        identity = trial["user_attrs"]["mode5_effective_point_identity"]
        require(trial["trial_id"] == row["trial_id"] == index,
                "trial order differs from terminal ledger")
        require(trial["user_attrs"]["mode5_effective_geometry_identity"] == geometry_identity
                and identity == digest(dict(schema=geometry_identity, effective=row["effective_params"]))
                and row["candidate_id"] == digest(row["effective_params"]),
                "canonical effective params/geometry identity differs")
        early = trial["runtime_row"]
        # The existing runtime reconciles only display Sharpe fields at close.
        # Verify that exact enrichment from retained observations, not arbitrary
        # differences between early trial checkpoints and the terminal ledger.
        values = [view["raw_sharpe"] for view in row["observations"]]
        mean = sum(values)/len(values) if values and all(v is not None for v in values) else None
        require(len(values) == 3, "three original annual observations required")
        # np.mean on this three-item trial path sums left-to-right; Python 3.12
        # sum at terminal reconciliation may differ by one float64 ULP.
        trial_mean = 0.
        for value in values:
            trial_mean += value or 0.
        trial_mean /= len(values)
        whole = row["whole_observation"]["raw_sharpe"]
        reconciled = dict(early, annual_mean_raw_sharpe=mean,
                          raw_whole_sharpe=whole, raw_sharpe=whole)
        require(row == reconciled
                and (early == row or early["raw_sharpe"] == trial_mean),
                "terminal Sharpe enrichment differs from retained observations")
        require(trial["optuna_state"] == "COMPLETE"
                and trial["values"] == [row["objective"]]
                and trial["user_attrs"]["qms_effective"] == row["effective_params"]
                and observed.get(row["continuous_observation_ref"]) == identity,
                "trial order/params/objective/account linkage differs")
        proposals.add(identity)
        parameter_vectors.add(canonical(row["effective_params"]))
    require(len(proposals) == len(set(observed.values())) == len(parameter_vectors) == 256,
            "unique coverage cannot be inferred from trial count")
    require(counts == dict(original_scorer_invocations=257, retained_scorer_accounts=257,
            final_endpoint_accounts_completed=1, direct_owner_accounts_completed=1,
            observed_completed_account_total=259,
            count_unit="ORIGINAL_ACCOUNT_INVOCATIONS_NOT_INTERNAL_NATIVE_PASSES",
            internal_native_passes=None, internal_native_passes_status="NOT_INFERRED")
            and checkpoint["recorded_scorer_accounts"] == 257
            and outcome["compute_bill"]["original_account_observations"] == 257,
            "original invocation counts differ")
    require(audit["status"] == "EXACT_ORIGINAL_DIRECT_PARITY" and audit["direct_owner_completed"] == 1,
            "original independent direct accounting audit required")
    final, direct = audit["selected_final_paths"], audit["direct_paths"]
    require(final == retained.get(final["path"]) and direct == retained.get(direct["path"])
            and (final["sha256"], final["bytes"]) == (direct["sha256"], direct["bytes"]),
            "selected/direct full NPZ bytes must be identical")
    vector_pin = retained.get(str(directory / "selected-vector.json"))
    require(vector_pin is not None, "original selected vector missing")
    vector = checked(vector_pin)
    chosen = outcome["decision"]["chosen_candidate"]
    selected_row = next((row for row in rows if row["candidate_id"] == chosen), None)
    require(outcome["selected_params_digest"] == chosen and selected_row is not None
            and selected_row["effective_params"] == vector["effective_params"]
            and vector["point_identity"] == audit["selected_point_identity"] == accounts[-1]["point_identity"]
            == observed[selected_row["continuous_observation_ref"]],
            "selected actual vector and replay account differ")
    for seal in [*retained.values(), *source_pins, spec["source_manifest"],
                 *registration["code_pins"], *spec.values(), log,
                 registration["original_registration"], registration["cold_result"]]:
        require(pin(seal["path"]) == seal, "exit custody differs")
    return dict(schema="mode5.completed_floor_receipt_recovery.v1",
        status="PASS_COLD_RECOVERED_FLOOR_256", original_parent_status="FAIL_RETAINED",
        evidence=dict(spec, original_log=log, original_study=study_pin, selected_vector=vector_pin),
        actual_counts=counts, trial_count=256, unique_executed_points=256,
        eligible_trials=sum(row["components"]["eligible"] for row in rows),
        original_selected_audit=audit, source_pins_verified=len(source_pins),
        retained_pins_verified=len(retained), cold_entry_and_exit_verified=True,
        original_worker_exit_receipt="NOT_DURABLE; source reverified by cold recovery",
        all_original_children_reaped=True, new_financial_executions=0,
        new_search_attempts=0, rng_draws=0, original_receipts_unchanged=True,
        independent_validation=False, deployment_authorized=False)
