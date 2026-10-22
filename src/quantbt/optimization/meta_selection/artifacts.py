"""Portable complete bundles; digests detect corruption, not research authorization."""

from __future__ import annotations

import json

from .common import MetaRecordError, canonical, digest, strict_fields, utc, wire
from .model import MetaModelArtifact, RidgeSettings
from .numerics import NumericLimits
from .persistence import _unique_object
from .selection import MetaSelectionDecision


def _dump(value, schema):
    payload = wire(value)
    return canonical(
        {"schema": schema, "payload": payload, "content_digest": digest(payload)}
    )


def _load(
    text, schema, *, expected_id, id_schema, available_as_of, max_bytes=16_000_000
):
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
            set(doc) != {"schema", "payload", "content_digest"}
            or doc["schema"] != schema
            or doc["content_digest"] != digest(doc["payload"])
        ):
            raise MetaRecordError("META_ARTIFACT_DIGEST_INVALID")
        if (
            not expected_id
            or digest({"schema": id_schema[0], id_schema[1]: doc["payload"]})
            != expected_id
        ):
            raise MetaRecordError("META_ARTIFACT_REVIEW_ID_REQUIRED_OR_MISMATCH")
        if available_as_of is None:
            raise MetaRecordError("META_ARTIFACT_AVAILABILITY_REQUIRED")
        return doc["payload"], utc(available_as_of)
    except MetaRecordError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise MetaRecordError("META_ARTIFACT_CORRUPT") from exc


def dumps_model(model):
    return _dump(model, "qms-model-bundle-v1")


def loads_model(text, *, expected_model_id, available_as_of):
    fields, cutoff = _load(
        text,
        "qms-model-bundle-v1",
        expected_id=expected_model_id,
        id_schema=("qms-ridge-model-v1", "model"),
        available_as_of=available_as_of,
    )
    try:
        fields = strict_fields(MetaModelArtifact, fields)
        fields["settings"] = RidgeSettings(
            **strict_fields(RidgeSettings, fields["settings"])
        )
        fields["numeric_limits"] = NumericLimits(
            **strict_fields(NumericLimits, fields["numeric_limits"])
        )
        model = MetaModelArtifact(**fields)
        if model.fit_completed_at > cutoff or model.information_as_of > cutoff:
            raise MetaRecordError("META_MODEL_NOT_YET_AVAILABLE")
        return model
    except MetaRecordError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise MetaRecordError("META_MODEL_BUNDLE_CORRUPT") from exc


def dumps_decision(decision):
    return _dump(decision, "qms-decision-bundle-v1")


def loads_decision(text, *, expected_decision_id, available_as_of):
    fields, cutoff = _load(
        text,
        "qms-decision-bundle-v1",
        expected_id=expected_decision_id,
        id_schema=("qms-selection-decision-v1", "decision"),
        available_as_of=available_as_of,
    )
    try:
        decision = MetaSelectionDecision(**strict_fields(MetaSelectionDecision, fields))
        if decision.ready_at > cutoff:
            raise MetaRecordError("META_DECISION_NOT_YET_AVAILABLE")
        return decision
    except MetaRecordError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise MetaRecordError("META_DECISION_BUNDLE_CORRUPT") from exc
