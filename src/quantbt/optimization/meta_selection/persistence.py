"""Strict JSON checkpoints, with a thin existing columnar-retention adapter."""

from __future__ import annotations

from dataclasses import replace
import json
from typing import Mapping

from .common import MetaRecordError, canonical, digest, strict_fields, wire
from .history import SealedTaskRevision
from .panel import FrozenLabelPanel
from .records import (
    CandidateForwardRecord,
    CandidateISRecord,
    CandidateRoleRef,
    CompatibilityFamily,
    MetaTask,
    MetricObservation,
)


def observation_from_payload(payload):
    return MetricObservation(**strict_fields(MetricObservation, payload))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MetaRecordError("duplicate checkpoint JSON field")
        result[key] = value
    return result


def dumps_revision(revision):
    payload = wire(revision)
    return canonical(
        {
            "schema": "qms-history-checkpoint-v1",
            "payload": payload,
            "content_digest": digest(payload),
        }
    )


def loads_revision(
    text,
    *,
    verified_output_witnesses=None,
    reviewed_revision_ids=(),
    max_bytes=16_000_000,
):
    if not isinstance(text, str) or len(text.encode()) > max_bytes:
        raise MetaRecordError("checkpoint type/size invalid")
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                MetaRecordError("nonfinite JSON")
            ),
        )
        if (
            set(document) != {"schema", "payload", "content_digest"}
            or document["schema"] != "qms-history-checkpoint-v1"
            or digest(document["payload"]) != document["content_digest"]
        ):
            raise MetaRecordError("checkpoint schema/content digest mismatch")
        fields = strict_fields(SealedTaskRevision, document["payload"])
        task_fields = strict_fields(MetaTask, fields["task"])
        task_fields["family"] = CompatibilityFamily(
            **strict_fields(CompatibilityFamily, task_fields["family"])
        )
        candidates = []
        for payload in task_fields["candidates"]:
            candidate = strict_fields(CandidateISRecord, payload)
            candidate["observation"] = observation_from_payload(
                candidate["observation"]
            )
            candidates.append(CandidateISRecord(**candidate))
        task_fields["candidates"] = tuple(candidates)
        task_fields["roles"] = tuple(
            CandidateRoleRef(**strict_fields(CandidateRoleRef, r))
            for r in task_fields["roles"]
        )
        fields["task"] = MetaTask(**task_fields)
        fields["panel"] = FrozenLabelPanel(
            **strict_fields(FrozenLabelPanel, fields["panel"])
        )
        outcomes = []
        for payload in fields["outcomes"]:
            outcome = strict_fields(CandidateForwardRecord, payload)
            outcome["observation"] = observation_from_payload(outcome["observation"])
            outcomes.append(CandidateForwardRecord(**outcome))
        fields["outcomes"] = tuple(outcomes)
        revision = SealedTaskRevision(**fields)
        witnesses = (
            {} if verified_output_witnesses is None else verified_output_witnesses
        )
        if not isinstance(witnesses, Mapping):
            raise MetaRecordError(
                "import witnesses must bind original output refs to complete observation digests"
            )
        observations = [c.observation for c in revision.task.candidates] + [
            o.observation for o in revision.outcomes
        ]
        for observation in observations:
            if observation.output_ref in witnesses and witnesses[
                observation.output_ref
            ] != digest(observation):
                raise MetaRecordError("original metric witness mismatch")
        # A serialized 'verified' checkbox is never an authorization witness.
        verified = (
            all(o.output_ref in witnesses for o in observations)
            and revision.revision_id in set(reviewed_revision_ids)
            and revision.verification != "unverified"
        )
        return revision if verified else replace(revision, verification="unverified")
    except MetaRecordError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MetaRecordError("corrupt history checkpoint") from exc


def retention_chunk(revision, *, chunk_id):
    from ...core.research_audit import ColumnarResearchTableV1

    return ColumnarResearchTableV1.from_records(
        table_name="meta_task_revisions",
        chunk_id=chunk_id,
        records=[
            {
                "task_id": revision.task.task_id,
                "revision_id": revision.revision_id,
                "family_id": revision.task.family.family_id,
                "available_at": revision.revision_available_at.isoformat(),
                "checkpoint_json": dumps_revision(revision),
            }
        ],
    )


def restore_chunk(
    chunk,
    *,
    expected_logical_digest,
    verified_output_witnesses=None,
    reviewed_revision_ids=(),
):
    if (
        chunk.table_name != "meta_task_revisions"
        or chunk.logical_digest != expected_logical_digest
    ):
        raise MetaRecordError("retained chunk schema/digest mismatch")
    from ...core.research_audit import ColumnarResearchTableV1

    rows = chunk.to_records()
    rebuilt = ColumnarResearchTableV1.from_records(
        table_name=chunk.table_name, chunk_id=chunk.chunk_id, records=rows
    )
    if rebuilt.logical_digest != expected_logical_digest:
        raise MetaRecordError("retained chunk content digest mismatch")
    revisions = []
    for row in rows:
        if set(row) != {
            "task_id",
            "revision_id",
            "family_id",
            "available_at",
            "checkpoint_json",
        }:
            raise MetaRecordError("retained revision row schema mismatch")
        revision = loads_revision(
            row["checkpoint_json"],
            verified_output_witnesses=verified_output_witnesses,
            reviewed_revision_ids=reviewed_revision_ids,
        )
        # Check original checkpoint identity, before unverified import disposition.
        source = json.loads(row["checkpoint_json"])["payload"]
        if (
            row["task_id"] != revision.task.task_id
            or row["family_id"] != revision.task.family.family_id
            or row["revision_id"]
            != digest({"schema": "qms-revision-v1", "record": source})
            or row["available_at"] != revision.revision_available_at.isoformat()
        ):
            raise MetaRecordError("retained revision references mismatch")
        revisions.append(revision)
    return tuple(revisions)


def dumps_pending(record):
    if record.observation.status.value != "PENDING":
        raise MetaRecordError("pending checkpoint requires pending disposition")
    payload = wire(record)
    return canonical(
        {
            "schema": "qms-pending-checkpoint-v1",
            "payload": payload,
            "content_digest": digest(payload),
        }
    )


def loads_pending(text, *, max_bytes=1_000_000):
    if not isinstance(text, str) or len(text.encode()) > max_bytes:
        raise MetaRecordError("pending checkpoint type/size invalid")
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                MetaRecordError("nonfinite JSON")
            ),
        )
        if (
            set(document) != {"schema", "payload", "content_digest"}
            or document["schema"] != "qms-pending-checkpoint-v1"
            or digest(document["payload"]) != document["content_digest"]
        ):
            raise MetaRecordError("pending schema/content digest mismatch")
        payload = strict_fields(CandidateForwardRecord, document["payload"])
        payload["observation"] = observation_from_payload(payload["observation"])
        record = CandidateForwardRecord(**payload)
        if record.observation.status.value != "PENDING":
            raise MetaRecordError("restored pending checkpoint is not pending")
        return record
    except MetaRecordError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MetaRecordError("corrupt pending checkpoint") from exc
