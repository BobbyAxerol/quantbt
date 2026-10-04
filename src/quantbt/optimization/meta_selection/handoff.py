"""Complete immutable handoff; host owns activation, position and order policy."""

from __future__ import annotations

from dataclasses import dataclass
import json

from .artifacts import dumps_decision, dumps_model, loads_decision, loads_model
from .common import MetaRecordError, canonical, digest, freeze, strict_fields, utc, wire
from .history import HistorySnapshot
from .model import MetaModelArtifact
from .persistence import (
    _unique_object,
    dumps_revision,
    loads_revision,
    task_from_payload,
)
from .records import MetaTask
from .selection import MetaSelectionDecision


@dataclass(frozen=True, slots=True)
class DecisionHandoff:
    task: MetaTask
    decision: MetaSelectionDecision
    model: MetaModelArtifact | None
    snapshot: HistorySnapshot
    native_selection_reason: dict
    effective_at: object = None
    schema_version: str = "qms-host-handoff-v1"

    def __post_init__(self):
        object.__setattr__(
            self, "native_selection_reason", freeze(self.native_selection_reason)
        )
        if self.effective_at is not None:
            object.__setattr__(self, "effective_at", utc(self.effective_at))
        task, decision, model, snapshot = (
            self.task,
            self.decision,
            self.model,
            self.snapshot,
        )
        candidates = {c.evaluation_id: c for c in task.candidates}
        if (
            self.schema_version != "qms-host-handoff-v1"
            or decision.task_id != task.task_id
            or decision.anchor_evaluation_id != task.anchor_candidate_evaluation_id
            or decision.information_as_of != task.data_cutoff
            or decision.clock_mode != task.clock_mode
            or decision.decision_sealed_at != task.decision_sealed_at
            or decision.proposed_evaluation_id not in candidates
            or decision.raw_best_evaluation_id not in candidates
            or decision.actual_evaluation_id is not None
            and decision.actual_evaluation_id not in candidates
            or digest(decision.proposed_params)
            != digest(candidates[decision.proposed_evaluation_id].effective_params)
            or any(p["evaluation_id"] not in candidates for p in decision.predictions)
            or snapshot.family_id != task.family.family_id
            or snapshot.information_as_of > task.data_cutoff
            or self.effective_at is not None
            and self.effective_at < decision.ready_at
        ):
            raise MetaRecordError("META_HANDOFF_LINEAGE_OR_CLOCK_INVALID")
        if decision.model_id is None:
            if model is not None or decision.training_snapshot_id is not None:
                raise MetaRecordError("META_HANDOFF_UNEXPECTED_MODEL")
        elif (
            model is None
            or model.model_id != decision.model_id
            or model.family_id != task.family.family_id
            or model.information_as_of > task.data_cutoff
            or model.information_as_of != snapshot.information_as_of
            or model.fit_completed_at != decision.fit_completed_at
            or model.fit_completed_at > decision.decision_sealed_at
            or model.training_snapshot_id != snapshot.snapshot_id
            or decision.training_snapshot_id != snapshot.snapshot_id
            or set(model.revision_references)
            != set(
                (r.task.task_id, r.revision_id, r.content_digest)
                for r in snapshot.revisions
            )
            or model.schema["schema_id"] != task.family.descriptor_schema_id
            or dict(model.history_permissions)
            != {
                "corpora": snapshot.authorized_corpora,
                "cohorts": snapshot.outcome_origins,
                "exposures": snapshot.research_exposures,
                "snapshot_order": snapshot.snapshot_order,
            }
        ):
            raise MetaRecordError("META_HANDOFF_MODEL_FRONTIER_OR_BASIS_INVALID")

    @property
    def selected_params(self):
        eid = self.decision.actual_evaluation_id or self.decision.proposed_evaluation_id
        return next(
            c.effective_params for c in self.task.candidates if c.evaluation_id == eid
        )

    @property
    def handoff_id(self):
        return digest({"schema": self.schema_version, "handoff": self})

    def read_params(self, *, available_as_of):
        if utc(available_as_of) < self.decision.ready_at:
            raise MetaRecordError("META_DECISION_NOT_YET_AVAILABLE")
        return wire(self.selected_params)


def export_fold_handoff(result, *, fold_id, effective_at=None):
    """Read existing result sidecars. No fit, broker, account reset or replay."""
    metadata = result.metadata.get("walk_forward", result.metadata)["meta_selection"]
    row = next((r for r in metadata["records"] if r["fold_id"] == fold_id), None)
    if row is None:
        raise MetaRecordError("META_HANDOFF_FOLD_UNKNOWN")
    task = next(t for t in metadata["tasks"] if t.task_id == row["task_id"])
    snapshot = next(
        s for s in metadata["snapshots"] if s.snapshot_id == row["training_snapshot_id"]
    )
    decision = row["proposal"]
    model = metadata["models"].get(decision.model_id)
    return DecisionHandoff(
        task,
        decision,
        model,
        snapshot,
        {
            "policy_id": row["native_selection_policy"],
            "objective": row["native_objective"],
            "raw_is_sharpe": row["native_raw_is_sharpe"],
            "selection": row["native_selection_reason"],
            "final_selection_policy": row["final_selection_policy"],
            "current_outer_oos_used_for_selection": row[
                "current_outer_oos_used_for_selection"
            ],
            "past_matured_forward_used_for_selection": row[
                "past_matured_forward_used_for_selection"
            ],
        },
        effective_at,
    )


def dumps_handoff(bundle):
    if not isinstance(bundle, DecisionHandoff):
        raise MetaRecordError("META_HANDOFF_TYPE_INVALID")
    snapshot = wire(bundle.snapshot)
    snapshot["revisions"] = [dumps_revision(r) for r in bundle.snapshot.revisions]
    payload = {
        "task": wire(bundle.task),
        "decision": dumps_decision(bundle.decision),
        "model": dumps_model(bundle.model) if bundle.model else None,
        "snapshot": snapshot,
        "native_selection_reason": wire(bundle.native_selection_reason),
        "effective_at": wire(bundle.effective_at),
        "schema_version": bundle.schema_version,
    }
    return canonical(
        {
            "schema": "qms-portable-handoff-bundle-v1",
            "payload": payload,
            "content_digest": digest(payload),
            "handoff_id": bundle.handoff_id,
        }
    )


def loads_handoff(
    text,
    *,
    expected_handoff_id,
    available_as_of,
    authorized_corpora,
    expected_family_id,
    verified_output_witnesses=None,
    reviewed_revision_ids=(),
    outcome_origins=("historical_counterfactual",),
    research_exposures=("research_only",),
    max_bytes=32_000_000,
):
    """Caller supplies trusted ID, economics family, permissions and witnesses."""
    if not isinstance(text, str) or len(text.encode()) > max_bytes:
        raise MetaRecordError("META_ARTIFACT_SIZE_INVALID")
    try:
        doc = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                MetaRecordError("META_ARTIFACT_NONFINITE")
            ),
        )
        if (
            set(doc) != {"schema", "payload", "content_digest", "handoff_id"}
            or doc["schema"] != "qms-portable-handoff-bundle-v1"
            or digest(doc["payload"]) != doc["content_digest"]
            or not expected_handoff_id
            or doc["handoff_id"] != expected_handoff_id
        ):
            raise MetaRecordError("META_ARTIFACT_REVIEW_ID_REQUIRED_OR_MISMATCH")
        fields = strict_fields(DecisionHandoff, doc["payload"])
        task = task_from_payload(fields["task"])
        snapshot_fields = strict_fields(HistorySnapshot, fields["snapshot"])
        if (
            task.family.family_id != expected_family_id
            or task.corpus_id not in authorized_corpora
            or task.outcome_origin not in outcome_origins
            or task.research_exposure not in research_exposures
            or not set(snapshot_fields["authorized_corpora"]).issubset(
                authorized_corpora
            )
            or not set(snapshot_fields["outcome_origins"]).issubset(outcome_origins)
            or not set(snapshot_fields["research_exposures"]).issubset(
                research_exposures
            )
        ):
            raise MetaRecordError("META_HANDOFF_PERMISSION_OR_FAMILY_INVALID")
        snapshot_fields["revisions"] = tuple(
            loads_revision(
                r,
                verified_output_witnesses=verified_output_witnesses,
                reviewed_revision_ids=reviewed_revision_ids,
            )
            for r in snapshot_fields["revisions"]
        )
        fields["task"] = task
        fields["snapshot"] = HistorySnapshot(**snapshot_fields)
        decision_doc = json.loads(fields["decision"])
        decision_id = digest(
            {"schema": "qms-selection-decision-v1", "decision": decision_doc["payload"]}
        )
        fields["decision"] = loads_decision(
            fields["decision"],
            expected_decision_id=decision_id,
            available_as_of=available_as_of,
        )
        if fields["model"] is not None:
            fields["model"] = loads_model(
                fields["model"],
                expected_model_id=fields["decision"].model_id,
                available_as_of=available_as_of,
            )
        bundle = DecisionHandoff(**fields)
        if bundle.handoff_id != expected_handoff_id:
            raise MetaRecordError("META_ARTIFACT_DIGEST_INVALID")
        bundle.read_params(available_as_of=available_as_of)
        return bundle
    except MetaRecordError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
        raise MetaRecordError("META_HANDOFF_BUNDLE_CORRUPT") from exc
