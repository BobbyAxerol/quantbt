"""Synthetic-only ML-04 P0 retention and mocked cold-custody checks."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import digest, wire
from tests.meta_selection.test_qms03_history import make_task, revision_for
from tools.meta_model_research import fallback_audit as module
from tools.meta_model_research.fallback_audit import FOLDS, GROUPS, audit_fallback_rows


@pytest.fixture
def data():
    rows, corpora = [], {}
    _, schema = make_task(n=3)
    for group in GROUPS:
        revisions, selections, snapshots = [None] * 57, [None] * 57, {}
        for fold in FOLDS:
            task, _ = make_task(n=3, year=2000 + fold, corpus=group, schema=schema)
            revision = revision_for(task, schema)
            selected = task.candidates[
                1
            ]  # Frozen Ridge P0 is deliberately NOT the native anchor.
            snapshot = SimpleNamespace(
                snapshot_id=f"PRIVATE-{group}-{fold}",
                origin_count=fold - 13,
                information_as_of=task.data_cutoff,
            )
            record = dict(
                selected_evaluation_id=selected.evaluation_id,
                selected_params=dict(selected.effective_params),
                final_selection_reason="META_MODEL_PROPOSAL",
                native_selected_evaluation_id=task.anchor_candidate_evaluation_id,
                native_selected_params=dict(task.anchor.effective_params),
                current_outer_oos_used_for_selection=False,
                information_as_of=task.data_cutoff.isoformat(),
                decision_sealed_at=task.decision_sealed_at.isoformat(),
                proposal=dict(
                    proposed_evaluation_id=selected.evaluation_id,
                    proposed_params=dict(selected.effective_params),
                ),
            )
            revisions[fold], selections[fold], snapshots[fold] = (
                revision,
                dict(task=wire(task), record=record),
                snapshot,
            )
            rows.append(
                dict(
                    panel="union",
                    policy="P0",
                    resolved_policy="P0",
                    group=group,
                    fold=fold,
                    winner=selected.evaluation_id,
                    status=record["final_selection_reason"],
                    anchor=task.anchor_candidate_evaluation_id,
                    cutoff=task.data_cutoff.isoformat(),
                    label_available_at=max(
                        o.label_available_at for o in revision.outcomes
                    ).isoformat(),
                    revision_available_at=revision.revision_available_at.isoformat(),
                    snapshot_id=snapshot.snapshot_id,
                    K=snapshot.origin_count,
                )
            )
        corpora[group] = SimpleNamespace(
            group=group,
            revisions=revisions,
            selections=selections,
            snapshot=lambda fold, s=snapshots: s[fold],
        )
    nominees = {
        p: {
            g: dict(
                policy="P0",
                nominees=[],
                reason="FAMILY_CALIBRATION_COMPLETE_BLOCKS_INSUFFICIENT",
            )
            for g in GROUPS
        }
        for p in ("base", "union")
    }
    result = dict(
        schema="m4.ml02.fixed-pool-replay.v1",
        status="REPLAY_COMPLETE_ANALYSIS_PENDING",
        rows=rows,
        new_financial_calls=0,
        new_optimizer_proposals=0,
    )
    return result, corpora, nominees


def audit(data):
    return audit_fallback_rows(*data)


def test_all_128_frozen_p0_choices_may_differ_from_native_and_no_row_hash_is_invented(
    data,
):
    rows_before = deepcopy(data[0])
    assert all("proposed_params_digest" not in r for r in data[0]["rows"])
    result = audit(data)
    assert data[0] == rows_before
    assert result["checked_rows"] == result["selected_params_hashes_checked"] == 128
    assert result["policy"] == "FROZEN_RIDGE_P0"
    assert result["nominee_cells_checked"] == 8
    assert all(
        c["P0_differs_from_native_anchor"] == 32 for c in result["per_group"].values()
    )
    assert (
        result["model_fits"]
        == result["financial_calls"]
        == result["optimizer_proposals"]
        == 0
    )
    assert result["public_activation"] is result["economic_improvement_claim"] is False
    encoded = json.dumps(result, allow_nan=False)
    assert (
        "PRIVATE" not in encoded
        and "hma_length" not in encoded
        and "evaluation-" not in encoded
    )
    assert len(result["audit_digest"]) == 64


@pytest.mark.parametrize(
    "field", ["cutoff", "label_available_at", "revision_available_at"]
)
def test_row_timestamps_cannot_drift(data, field):
    data[0]["rows"][0][field] = (
        pd.Timestamp(data[0]["rows"][0][field]) + pd.Timedelta(nanoseconds=1)
    ).isoformat()
    with pytest.raises(ValueError, match="CLOCK_MISMATCH"):
        audit(data)


@pytest.mark.parametrize(
    "change",
    ["winner", "reason", "anchor", "snapshot", "K", "resolved_policy", "lookahead"],
)
def test_decision_and_prefix_corruption_fail_closed(data, change):
    row = data[0]["rows"][0]
    if change == "winner":
        row["winner"] = row["anchor"]
    elif change == "reason":
        row["status"] = "META_SUPPORT_INSUFFICIENT"
    elif change == "anchor":
        row["anchor"] = row["winner"]
    elif change == "snapshot":
        row["snapshot_id"] = "wrong"
    elif change == "K":
        row["K"] += 1
    elif change == "resolved_policy":
        row["resolved_policy"] = "P1"
    else:
        data[1][GROUPS[0]].selections[25]["record"][
            "current_outer_oos_used_for_selection"
        ] = True
    with pytest.raises(ValueError, match="MLR04_FALLBACK"):
        audit(data)


@pytest.mark.parametrize("where", ["selected", "proposal", "native", "row"])
def test_params_payload_and_optional_digest_corruption_fail_closed(data, where):
    record = data[1][GROUPS[0]].selections[25]["record"]
    if where == "row":
        data[0]["rows"][0]["proposed_params_digest"] = "0" * 64
    elif where == "proposal":
        record["proposal"]["proposed_params"]["hma_length"] += 1
    else:
        record["selected_params" if where == "selected" else "native_selected_params"][
            "hma_length"
        ] += 1
    with pytest.raises(ValueError, match="PARAMS_DIGEST_MISMATCH"):
        audit(data)


@pytest.mark.parametrize(
    "change", ["duplicate", "missing", "substitute-panel", "substitute-policy"]
)
def test_full_unique_outer_union_p0_roster_required(data, change):
    rows = data[0]["rows"]
    if change == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif change == "missing":
        rows.pop()
    elif change == "substitute-panel":
        rows[0]["panel"] = "base"
    else:
        rows[0]["policy"] = "P1"
    with pytest.raises(ValueError, match="DUPLICATE_ROW|INCOMPLETE_OUTER_ROSTER"):
        audit(data)


@pytest.mark.parametrize("panel", ["base", "union"])
def test_every_heldout_group_on_both_panels_must_have_no_nominees(data, panel):
    data[2][panel][GROUPS[-1]]["nominees"] = ["X2"]
    with pytest.raises(ValueError, match="NO_NOMINEE_SCOPE_REQUIRED"):
        audit(data)


def test_no_nominees_does_not_mean_replace_p0_with_anchor(data):
    first = audit(data)
    row = data[0]["rows"][0]
    corpus = data[1][GROUPS[0]]
    record = corpus.selections[25]["record"]
    record["selected_evaluation_id"] = row["winner"] = row["anchor"]
    record["selected_params"] = dict(corpus.revisions[25].task.anchor.effective_params)
    record["proposal"] = None
    record["final_selection_reason"] = row["status"] = "META_SUPPORT_INSUFFICIENT"
    second = audit(data)
    assert second["per_group"][GROUPS[0]]["P0_differs_from_native_anchor"] == 31
    assert first["audit_digest"] != second["audit_digest"]


def test_scope_does_not_replay_other_panels_policies_or_training_folds(data):
    first = audit(data)
    data[0]["rows"] += [
        dict(data[0]["rows"][0], panel="base", winner="ignored"),
        dict(data[0]["rows"][0], policy="P1", winner="ignored"),
        dict(data[0]["rows"][0], fold=24, winner="ignored"),
    ]
    data[0]["rows"].reverse()
    assert audit(data) == first


def test_unavailable_snapshot_and_saved_task_misbinding_are_rejected(data):
    corpus = data[1][GROUPS[0]]
    snapshot = corpus.snapshot(25)
    snapshot.information_as_of += pd.Timedelta(nanoseconds=1)
    with pytest.raises(ValueError, match="PREFIX_MISMATCH"):
        audit(data)
    snapshot.information_as_of -= pd.Timedelta(nanoseconds=1)
    corpus.selections[25]["task"]["run_id"] = "wrong-task"
    with pytest.raises(ValueError, match="SAVED_TASK_MISMATCH"):
        audit(data)


def mocked_wrapper(data, monkeypatch):
    docs, refs, calls = {}, {}, []
    base = Path("/synthetic/authority")
    roots = {g: base / g for g in GROUPS}
    monkeypatch.setattr(module, "BASE", base)
    monkeypatch.setattr(module, "ROOTS", roots)

    def add(path, document=None, sha=None):
        path = str(path)
        refs[path] = dict(path=path, bytes=123, sha256=sha or digest(path))
        if document is not None:
            docs[path] = document
        return refs[path]

    baseline_ref = add(module.BASELINE_PATH, data[0])
    screen_ref = add(
        module.SCREEN_PATH, dict(schema="m4.ml03.finite-screen.v1", nominees=data[2])
    )
    add(
        module.PUBLIC / "ml02_closure.json",
        dict(
            schema="m4.ml02.closure.v1",
            technical_gate="PASS",
            input_pins=[baseline_ref],
        ),
    )
    add(
        module.PUBLIC / "ml03_closure.json",
        dict(
            schema="m4.ml03.closure.v1",
            technical_gate="PASS",
            no_nominees=True,
            inputs=[screen_ref],
        ),
    )
    account_refs = [
        add(root / account / name)
        for root in roots.values()
        for account in ("native", "ridge")
        for name in module.ACCOUNT_NAMES
    ]
    readback_path = base / "four-alpha-closeout-v1/readback.json"
    readback = dict(input_pins=account_refs)
    add(readback_path, readback, module.READBACK_SHA256)

    def fake_pin(path):
        path = str(path)
        calls.append(("pin", path))
        if path not in refs:
            add(path)
        return dict(refs[path])

    def fake_read(path, **kwargs):
        path = str(path)
        calls.append(("read", path))
        assert kwargs["expected_sha256"] == refs[path]["sha256"]
        assert kwargs["expected_bytes"] == refs[path]["bytes"]
        return docs[path]

    monkeypatch.setattr(module, "pin", fake_pin)
    monkeypatch.setattr(module, "read_verified", fake_read)
    monkeypatch.setattr(
        module,
        "verify_freeze",
        lambda: dict(verified=True, freeze_id="synthetic-freeze"),
    )
    monkeypatch.setattr(module, "load_corpus", lambda g: data[1][g])
    return docs, refs, calls, readback


def test_wrapper_entirely_mocked_checks_all_24_original_financial_pins_without_decoding(
    data, monkeypatch
):
    _, _, calls, _ = mocked_wrapper(data, monkeypatch)
    result = module.run_fallback_audit()
    assert result["protected_account_files"] == 24 and result["checked_rows"] == 128
    assert result["baseline_freeze"]["verified"]
    assert set(result["source_pins"]) == {
        "fallback_audit.py",
        "admission.py",
        "protocol.py",
    }
    assert not any(
        Path(path).name in module.ACCOUNT_NAMES
        for kind, path in calls
        if kind == "read"
    )
    assert "/synthetic/" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "corrupt",
        "root-prefix",
        "readback-hash",
        "source-mutated",
    ],
)
def test_mocked_wrapper_fails_closed_on_account_and_custody_corruption(
    data, monkeypatch, change
):
    _, refs, _, readback = mocked_wrapper(data, monkeypatch)
    if change == "missing":
        readback["input_pins"].pop()
    elif change == "duplicate":
        readback["input_pins"].append(dict(readback["input_pins"][0]))
    elif change == "corrupt":
        ref = readback["input_pins"][0]
        refs[ref["path"]] = dict(ref, sha256="bad")
    elif change == "root-prefix":
        ref = readback["input_pins"][0]
        ref["path"] = ref["path"].replace("/A-SC/", "/A-SC-other/")
    elif change == "readback-hash":
        refs[str(module.BASE / "four-alpha-closeout-v1/readback.json")]["sha256"] = (
            "bad"
        )
    else:
        original = module.pin
        visits = Counter()

        def changing(path):
            ref = original(path)
            visits[str(path)] += 1
            if Path(path).name == "fallback_audit.py" and visits[str(path)] > 1:
                ref["sha256"] = "changed"
            return ref

        monkeypatch.setattr(module, "pin", changing)
    with pytest.raises(ValueError, match="MLR04_FALLBACK"):
        module.run_fallback_audit()
