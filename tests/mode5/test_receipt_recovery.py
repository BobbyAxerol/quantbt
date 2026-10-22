"""Synthetic cold receipts only; no account execution or pickle deserialization."""

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from tools.mode5_research import receipt_recovery as recovery


class Fixture:
    def __init__(self, root):
        self.root = root
        self.directory = root / "run" / "challenger"
        self.directory.mkdir(parents=True)
        source = root / "original.py"
        source.write_text("# synthetic source, not a financial provider\n")
        sources = self.save(root / "sources.json", dict(source_pins=[recovery.pin(source)]))
        original = self.save(root / "original.json", dict(provider_sources=sources))
        geometry = dict(version="synthetic_fixture", axis="window")
        self.geometry_identity = recovery.digest(geometry)
        binding = self.save(root / "binding.json", dict(continuous=dict(geometry=geometry)))
        cold = self.save(root / "cold.json", dict(status="PASS_COLD_FLOOR_BINDING_REPAIR", artifacts=dict(binding=binding)))
        registration = self.save(root / "registration.json", dict(
            original_registration=original, cold_result=cold, code_pins=[recovery.pin(source)], output=str(root / "run")))
        self.retained = []
        rows, accounts, trials, observations = [], [], [], {}
        for index in range(257):
            params = dict(window=index if index < 256 else 0)
            point = recovery.digest(dict(schema=self.geometry_identity, effective=params))
            account_file = self.directory / f"account-{index:04d}.pkl"
            account_file.write_bytes(b"synthetic opaque bytes, never unpickled")
            account_pin = recovery.pin(account_file)
            metadata = self.save(self.directory / f"account-{index:04d}.json", dict(
                account=account_pin, query_id=f"query-{index}", evaluation_identity=f"account-{index}",
                observation=dict(identity=f"account-{index}", request_identity=f"request-{index}",
                    annual_account_resets=0, financial_execution_count=1,
                    execution=dict(request_identity=f"request-{index}", effective_params_identity=point,
                        financial_execution_count=1))))
            observations[f"query-{index}"] = recovery.checked(metadata)["observation"]
            self.retained.extend([account_pin, metadata])
            accounts.append(dict(account=account_pin, metadata=metadata,
                query_id=f"query-{index}", evaluation_identity=f"account-{index}",
                point_identity=point, financial_execution_count=1))
            if index == 256:
                continue
            row = dict(trial_id=index, candidate_id=recovery.digest(params), objective=float(index),
                effective_params=dict(window=index), continuous_observation_ref=f"query-{index}",
                components=dict(eligible=True), observations=[dict(raw_sharpe=v) for v in (0., 1., 2.)],
                whole_observation=dict(raw_sharpe=3.), raw_sharpe=3.,
                raw_whole_sharpe=3., annual_mean_raw_sharpe=1.)
            rows.append(row)
            trial = self.save(self.directory / f"trial-{index:04d}.json", dict(
                trial_id=index, optuna_state="COMPLETE", values=[float(index)],
                runtime_row={k: (1. if k == "raw_sharpe" else v) for k, v in row.items()
                             if k not in ("raw_whole_sharpe", "annual_mean_raw_sharpe")},
                user_attrs=dict(mode5_effective_geometry_identity=self.geometry_identity,
                    mode5_effective_point_identity=point, qms_effective=row["effective_params"])))
            trials.append(trial)
            self.retained.append(trial)
        outcome = dict(status="SELECTED_REPLAY_VERIFIED", annual_account_resets=0,
            deployment_authorized=False, trial_ledger=rows, selected_params_digest=recovery.digest(dict(window=0)),
            decision=dict(chosen_candidate=recovery.digest(dict(window=0))), continuous_observations=observations,
            continuous_account_retention=dict(count=257, entries=[{key: a[key] for key in
                ("query_id", "evaluation_identity")} for a in accounts]),
            compute_bill=dict(original_account_observations=257))
        self.retained.append(self.save(self.directory / "study.json", outcome))
        final = self.directory / "selected-final.npz"
        direct = self.directory / "selected-direct.npz"
        final.write_bytes(b"synthetic identical complete financial stream container")
        direct.write_bytes(final.read_bytes())
        self.retained.extend([recovery.pin(final), recovery.pin(direct)])
        self.retained.append(self.save(self.directory / "selected-vector.json", dict(
            effective_params=dict(window=0), point_identity=accounts[0]["point_identity"])))
        self.inner = dict(arm="environment_floor_mean_v1", annual_resets=0,
            old_panel_imported_as_trials=False, final_endpoint_accounts_completed=1, direct_owner_completed=1,
            outcome=outcome, checkpoints=dict(attempts=256, states={"COMPLETE": 256},
                budget_complete=True, coverage_issue=False, unique_effective_proposals=256,
                unique_executed_points=256, trial_checkpoints=trials, accounts=accounts,
                runtime_trial_ledger=rows, recorded_scorer_accounts=257),
            actual_counts=dict(original_scorer_invocations=257, retained_scorer_accounts=257,
                final_endpoint_accounts_completed=1, direct_owner_accounts_completed=1,
                observed_completed_account_total=259,
                count_unit="ORIGINAL_ACCOUNT_INVOCATIONS_NOT_INTERNAL_NATIVE_PASSES",
                internal_native_passes=None, internal_native_passes_status="NOT_INFERRED"),
            audit=dict(status="EXACT_ORIGINAL_DIRECT_PARITY", direct_owner_completed=1,
                selected_final_paths=recovery.pin(final), direct_paths=recovery.pin(direct),
                selected_point_identity=accounts[0]["point_identity"]))
        partial = root / "run" / "result.json"
        partial.write_text('{"timestamp":')
        failure = self.save(root / "run" / "failure.json", dict(type="TypeError",
            error="Object of type Timestamp is not JSON serializable", retained_prior_evidence=True))
        log = root / "worker.log"
        log.write_text("TypeError: Object of type Timestamp is not JSON serializable\n")
        parent = self.save(root / "parent.json", dict(status="FAIL_RETAINED", reason=None,
            source_pins_unchanged=True, all_owned_children_reaped=True, original_scorer_changed=False,
            child_result=recovery.pin(partial), log=recovery.pin(log)))
        self.retained.extend([recovery.pin(partial), failure])
        self.spec = dict(failed_parent=parent, failed_cleanup=None, export_failure=failure,
            inner_result=None, partial_outer=recovery.pin(partial),
            original_run_registration=registration, source_manifest=sources, binding=binding)
        self.refresh()

    def save(self, path, value):
        path.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
        return recovery.pin(path)

    def refresh(self):
        self.retained = [item for item in self.retained if item["path"] != str(self.directory / "result.json")]
        self.spec["inner_result"] = self.save(self.directory / "result.json", self.inner)
        self.retained.append(self.spec["inner_result"])
        self.spec["failed_cleanup"] = self.save(self.root / "cleanup.json", dict(
            status="PASS_CLEANUP_ONLY", result=self.spec["failed_parent"],
            all_owned_children_reaped=True, retained_pins=self.retained))


@pytest.fixture
def f(tmp_path):
    return Fixture(tmp_path)


def test_completed_receipt_recovers_without_mutation_or_finance(f):
    old = [deepcopy(item) for item in f.retained]
    result = recovery.recover_completed_floor(f.spec)
    assert result["status"] == "PASS_COLD_RECOVERED_FLOOR_256"
    assert result["original_parent_status"] == "FAIL_RETAINED"
    assert result["new_financial_executions"] == result["new_search_attempts"] == result["rng_draws"] == 0
    assert result["trial_count"] == result["eligible_trials"] == 256
    assert result["actual_counts"]["observed_completed_account_total"] == 259
    assert all(recovery.pin(item["path"]) == item for item in old)
    assert "NOT_DURABLE" in result["original_worker_exit_receipt"]


@pytest.mark.parametrize("field,value", [
    ("attempts", 255), ("states", {"COMPLETE": 255, "FAIL": 1}),
    ("budget_complete", False), ("coverage_issue", True),
    ("unique_effective_proposals", 255), ("unique_executed_points", 255),
])
def test_incomplete_or_wrong_coverage_cannot_recover(f, field, value):
    f.inner["checkpoints"][field] = value
    f.refresh()
    with pytest.raises(ValueError, match="256 complete"):
        recovery.recover_completed_floor(f.spec)


@pytest.mark.parametrize("field", ["original_scorer_invocations", "observed_completed_account_total"])
def test_account_counts_are_not_invented(f, field):
    f.inner["actual_counts"][field] -= 1
    f.refresh()
    with pytest.raises(ValueError, match="invocation counts"):
        recovery.recover_completed_floor(f.spec)


@pytest.mark.parametrize("target", ["source", "trial", "account", "direct", "inner"])
def test_changed_evidence_rejected(f, target):
    path = {"source": f.root / "original.py", "trial": f.directory / "trial-0000.json",
        "account": f.directory / "account-0000.pkl", "direct": f.directory / "selected-direct.npz",
        "inner": f.directory / "result.json"}[target]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="changed|differs"):
        recovery.recover_completed_floor(f.spec)


def test_truncated_inner_is_not_partial_json_recovery(f):
    f.inner = None
    (f.directory / "result.json").write_bytes(b'{"outcome":')
    f.spec["inner_result"] = recovery.pin(f.directory / "result.json")
    f.retained[-1] = f.spec["inner_result"]
    f.spec["failed_cleanup"] = f.save(f.root / "cleanup.json", dict(status="PASS_CLEANUP_ONLY",
        result=f.spec["failed_parent"], all_owned_children_reaped=True, retained_pins=f.retained))
    with pytest.raises(json.JSONDecodeError):
        recovery.recover_completed_floor(f.spec)


def test_original_parent_must_be_reaped(f):
    parent = recovery.checked(f.spec["failed_parent"])
    parent["all_owned_children_reaped"] = False
    f.spec["failed_parent"] = f.save(f.root / "parent.json", parent)
    f.refresh()
    with pytest.raises(ValueError, match="closed failed owner"):
        recovery.recover_completed_floor(f.spec)


def test_selected_vector_must_match_actual_trial_and_replay(f):
    f.inner["audit"]["selected_point_identity"] = "other-point"
    f.refresh()
    with pytest.raises(ValueError, match="selected actual vector"):
        recovery.recover_completed_floor(f.spec)


def test_trial_order_cannot_be_rearranged(f):
    f.inner["checkpoints"]["trial_checkpoints"].reverse()
    f.refresh()
    with pytest.raises(ValueError, match="trial order"):
        recovery.recover_completed_floor(f.spec)


@pytest.mark.parametrize("field", ["raw_sharpe", "raw_whole_sharpe", "annual_mean_raw_sharpe"])
def test_only_original_display_enrichment_can_differ(f, field):
    f.inner["checkpoints"]["runtime_trial_ledger"][0][field] = 999.
    f.inner["outcome"]["trial_ledger"][0][field] = 999.
    f.save(f.directory / "study.json", f.inner["outcome"])
    f.retained = [recovery.pin(item["path"]) for item in f.retained]
    f.refresh()
    with pytest.raises(ValueError, match="Sharpe enrichment"):
        recovery.recover_completed_floor(f.spec)


def test_actual_pandas_timestamp_export(tmp_path):
    from pandas import Timestamp
    stamp = Timestamp("2024-01-01T01:02:03.123456789Z")
    result = recovery.write_atomic(tmp_path / "result.json", dict(date=stamp))
    assert recovery.checked(result)["date"] == stamp.isoformat()


def test_trial_mean_preserves_original_three_value_addition_not_new_sum(f):
    values = [-2.32603933078491, .33786918692024354, .25768275286321357]
    from numpy import mean
    early = recovery.checked(f.inner["checkpoints"]["trial_checkpoints"][0])
    early["runtime_row"]["observations"] = [dict(raw_sharpe=v) for v in values]
    early["runtime_row"]["raw_sharpe"] = float(mean(values))
    row = f.inner["checkpoints"]["runtime_trial_ledger"][0]
    row["observations"] = deepcopy(early["runtime_row"]["observations"])
    row["annual_mean_raw_sharpe"] = sum(values)/3
    seal = f.save(Path(f.inner["checkpoints"]["trial_checkpoints"][0]["path"]), early)
    f.inner["checkpoints"]["trial_checkpoints"][0] = seal
    f.save(f.directory / "study.json", f.inner["outcome"])
    f.retained = [recovery.pin(item["path"]) for item in f.retained]
    f.refresh()
    assert recovery.recover_completed_floor(f.spec)["status"] == "PASS_COLD_RECOVERED_FLOOR_256"


def sync_outcome(f):
    study = f.save(f.directory / "study.json", f.inner["outcome"])
    f.retained = [study if item["path"] == study["path"] else item for item in f.retained]
    f.refresh()


@pytest.mark.parametrize("field", ["identity", "request_identity"])
def test_sidecar_observation_cannot_conflict_with_evaluation_headers(f, field):
    account = f.inner["checkpoints"]["accounts"][0]
    record = recovery.checked(account["metadata"])
    record["observation"][field] = "conflicting-observation"
    new = f.save(Path(account["metadata"]["path"]), record)
    account["metadata"] = new
    f.retained = [new if item["path"] == new["path"] else item for item in f.retained]
    sync_outcome(f)
    with pytest.raises(ValueError, match="account lineage"):
        recovery.recover_completed_floor(f.spec)


def test_terminal_retention_roster_cannot_omit_a_query(f):
    f.inner["outcome"]["continuous_account_retention"]["entries"].pop()
    sync_outcome(f)
    with pytest.raises(ValueError, match="retained account roster"):
        recovery.recover_completed_floor(f.spec)


def test_identity_label_must_derive_from_effective_parameters(f):
    row = f.inner["checkpoints"]["runtime_trial_ledger"][1]
    row["effective_params"] = dict(window=0)
    sync_outcome(f)
    with pytest.raises(ValueError, match="canonical effective params"):
        recovery.recover_completed_floor(f.spec)


def test_replay_for_different_point_cannot_match_selected_parameter_header(f):
    accounts = f.inner["checkpoints"]["accounts"]
    selected, different = accounts[-1], accounts[1]["point_identity"]
    selected["point_identity"] = different
    record = recovery.checked(selected["metadata"])
    record["observation"]["execution"]["effective_params_identity"] = different
    f.inner["outcome"]["continuous_observations"][selected["query_id"]] = record["observation"]
    new = f.save(Path(selected["metadata"]["path"]), record)
    selected["metadata"] = new
    f.retained = [new if item["path"] == new["path"] else item for item in f.retained]
    f.inner["audit"]["selected_point_identity"] = different
    new_vector = f.save(f.directory / "selected-vector.json", dict(effective_params=dict(window=0), point_identity=different))
    f.retained = [new_vector if item["path"] == new_vector["path"] else item for item in f.retained]
    sync_outcome(f)
    with pytest.raises(ValueError, match="selected actual vector"):
        recovery.recover_completed_floor(f.spec)


@pytest.mark.parametrize("target", ["log", "original"])
def test_all_entry_inputs_are_checked_again_at_exit(f, monkeypatch, target):
    real = recovery.checked
    def mutate_at_selected_vector(seal):
        value = real(seal)
        if Path(seal["path"]).name == "selected-vector.json":
            path = f.root / ("worker.log" if target == "log" else "original.json")
            path.write_bytes(path.read_bytes() + b"changed after entry")
        return value
    monkeypatch.setattr(recovery, "checked", mutate_at_selected_vector)
    with pytest.raises(ValueError, match="exit custody"):
        recovery.recover_completed_floor(f.spec)


def test_atomic_publication_fsyncs_directory(tmp_path, monkeypatch):
    import os
    import stat
    original = os.fsync
    synced_directory = []
    def sync(fd):
        synced_directory.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        original(fd)
    monkeypatch.setattr(os, "fsync", sync)
    recovery.write_atomic(tmp_path / "receipt.json", dict(status="PASS"))
    assert synced_directory == [False, True]


def test_nested_datetime_export_is_normalized_before_publication(tmp_path):
    value = dict(nested=[date(2023, 12, 31), dict(cutoff=datetime(2024, 1, 1, tzinfo=timezone.utc))])
    receipt = recovery.write_atomic(tmp_path / "result.json", value)
    assert recovery.checked(receipt) == dict(nested=["2023-12-31", dict(cutoff="2024-01-01T00:00:00+00:00")])
    assert list(tmp_path.iterdir()) == [tmp_path / "result.json"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object(), {1: "wrong key"}])
def test_unsupported_export_leaves_no_partial_receipt(tmp_path, value):
    with pytest.raises((TypeError, ValueError)):
        recovery.write_atomic(tmp_path / "result.json", dict(value=value))
    assert not list(tmp_path.iterdir())


def test_export_never_replaces_a_historical_receipt(tmp_path):
    path = tmp_path / "result.json"
    old = recovery.write_atomic(path, dict(status="FAIL_RETAINED"))
    with pytest.raises(FileExistsError):
        recovery.write_atomic(path, dict(status="PASS"))
    assert recovery.pin(path) == old
    assert list(tmp_path.iterdir()) == [path]
