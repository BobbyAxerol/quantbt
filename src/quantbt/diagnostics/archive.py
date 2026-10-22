"""Source-bound cold archive reviews; no observations or execution authority."""

from dataclasses import asdict, dataclass, fields, is_dataclass
import json
from types import UnionType
from typing import Literal, get_args, get_origin

from quantbt.mode5.dossier.evidence import EvidenceCatalog
from quantbt.mode5.dossier.records import Record, require_text

from .access import AccessPolicy, AccessWitness
from .archive_contracts import ArchiveEvidence, IntendedReuse, assess_reuse


SCHEMA = "quantbt.archive_review.v1"
LIMITATIONS = (
    "Metadata eligibility is not accounting verification or permission.",
    "No candidate scores, sampler inputs, execution or reducer results are produced.",
    "Archive compatibility does not establish economic benefit or deployment authority.",
)
DISPOSITIONS = (
    "EXACT_REUSE", "DERIVED_READBACK_ALLOWED", "TARGETED_EXECUTION_REQUIRED",
    "RIGHTS_FORBIDDEN", "INCOMPATIBLE",
)


def _restore(kind, value):
    """Decode only declared dataclass fields, with JSON lists restored to tuples."""
    if is_dataclass(kind):
        declared = fields(kind)
        if type(value) is not dict or set(value) != {field.name for field in declared}:
            raise ValueError("exact known " + kind.__name__ + " fields required")
        return kind(**{field.name: _restore(field.type, value[field.name]) for field in declared})
    origin = get_origin(kind)
    if origin is tuple:
        if type(value) is not list:
            raise ValueError("canonical tuple list required")
        item, repeated = get_args(kind)
        if repeated is not Ellipsis:
            raise ValueError("unsupported tuple contract")
        return tuple(_restore(item, item_value) for item_value in value)
    if origin is Literal:
        if type(value) is not str or value not in get_args(kind):
            raise ValueError("known literal contract required")
        return value
    if origin is UnionType:
        for alternative in get_args(kind):
            try:
                return _restore(alternative, value)
            except ValueError:
                pass
        raise ValueError("typed optional contract required")
    if kind not in (str, int, type(None)) or type(value) is not kind:
        raise ValueError("exact typed contract field required")
    return value


def _access(access):
    if not isinstance(access, AccessPolicy):
        raise TypeError("fresh canonical AccessPolicy required")
    access.__post_init__()


def _limit(value, name):
    if type(value) is not int or value < 1:
        raise ValueError("positive exact " + name + " required")


def _ref(ref):
    if type(ref) is not dict or set(ref) != {"source", "pointer", "sha256"}:
        raise ValueError("exact catalog source reference required")
    require_text(ref["source"])
    if (type(ref["pointer"]) is not str or type(ref["sha256"]) is not str
            or len(ref["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in ref["sha256"])):
        raise ValueError("exact catalog pointer and digest required")
    return dict(ref)


def _row(evidence, intended, ref, witness, access):
    access.require(witness)
    # Check even disconnected nodes: a cached graph never supplies read authority.
    for node in evidence.nodes:
        access.require(node.witness)
    result = assess_reuse(evidence, intended, access)
    return dict(evidence_id=evidence.evidence_id, source_identity=evidence.identity.identity,
        target_identity=intended.identity.identity, disposition=result.disposition,
        reasons=result.reasons, missing_inputs=result.missing_inputs, ref=_ref(ref),
        source_witness=asdict(witness),
        declared_inputs=dict(evidence=asdict(evidence), intended=asdict(intended)))


def _entries(rows):
    result = []
    for row in rows:
        if type(row) is not dict or type(row.get("declared_inputs")) is not dict:
            raise ValueError("declared original archive assessment inputs required")
        inputs = row["declared_inputs"]
        if set(inputs) != {"evidence", "intended"}:
            raise ValueError("exact original archive assessment inputs required")
        result.append((_restore(ArchiveEvidence, inputs["evidence"]),
                       _restore(IntendedReuse, inputs["intended"]), _ref(row["ref"])))
    return tuple(result)


def _object(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("duplicate JSON contract field")
        value[name] = item
    return value


@dataclass(frozen=True)
class ArchiveReview:
    """Immutable eligibility record; verification rebuilds against current sources."""

    record: Record

    def __post_init__(self):
        if not isinstance(self.record, Record):
            raise ValueError("immutable archive review Record required")
        data = self.record.data
        required = {"schema", "context_id", "access_id", "access_policy", "status", "rows", "limitations"}
        if (set(data) != required or data["schema"] != SCHEMA
                or data["limitations"] != list(LIMITATIONS) or type(data["rows"]) is not list):
            raise ValueError("complete versioned private archive review required")
        require_text(data["context_id"])
        access = _restore(AccessPolicy, data["access_policy"])
        if data["access_id"] != access.identity:
            raise ValueError("archive access identity mismatch")
        if data["status"] != ("REVIEWED" if data["rows"] else "NO_ARCHIVE"):
            raise ValueError("explicit archive presence status required")
        try:
            for row, (evidence, intended, ref) in zip(data["rows"], _entries(data["rows"])):
                witness = _restore(AccessWitness, row["source_witness"])
                if Record.of(row) != Record.of(_row(evidence, intended, ref, witness, access)):
                    raise ValueError("archive row differs from its declared assessment inputs")
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("complete typed archive assessment row required") from error

    @classmethod
    def empty(cls, context_id, access):
        return cls.assess((), context_id=context_id, access=access, catalog=None)

    @classmethod
    def assess(cls, entries, *, context_id, access, catalog, max_rows=10000):
        require_text(context_id)
        _access(access)
        _limit(max_rows, "archive row budget")
        if type(entries) is not tuple or len(entries) > max_rows:
            raise ValueError("bounded immutable archive entries required; no rows truncated")
        rows = []
        if entries:
            if not isinstance(catalog, EvidenceCatalog):
                raise TypeError("verified EvidenceCatalog required for archive sources")
            catalog.verify_current()
            sources = {source["source_id"]: source for source in catalog.manifest.data["sources"]}
            for entry in entries:
                if (type(entry) is not tuple or len(entry) != 3
                        or not isinstance(entry[0], ArchiveEvidence) or not isinstance(entry[1], IntendedReuse)):
                    raise TypeError("typed (ArchiveEvidence, IntendedReuse, exact catalog.ref) tuple required")
                evidence, intended, ref = entry
                ref = _ref(ref)
                if ref["source"] not in sources:
                    raise ValueError("archive source absent from verified catalog")
                witness = _restore(AccessWitness, sources[ref["source"]]["witness"])
                access.require(witness)
                raw = catalog.require_ref(ref)
                if Record.of({"value": raw}) != Record.of({"value": asdict(evidence)}):
                    raise ValueError("archive source must exactly match declared ArchiveEvidence")
                rows.append(_row(evidence, intended, ref, witness, access))
            catalog.verify_current()
        return cls(Record.of(dict(schema=SCHEMA, context_id=context_id, access_id=access.identity,
            access_policy=asdict(access), status="REVIEWED" if rows else "NO_ARCHIVE",
            rows=rows, limitations=LIMITATIONS)))

    @property
    def identity(self):
        return self.record.identity

    def verify(self, catalog, access):
        data = self.record.data
        entries = _entries(data["rows"])
        rebuilt = self.assess(entries, context_id=data["context_id"], access=access,
                              catalog=catalog, max_rows=max(10000, len(entries)))
        if access.identity != data["access_id"]:
            raise PermissionError("changed access policy requires fresh archive review")
        if self != rebuilt:
            raise ValueError("archive review differs from current source-bound assessment")
        return self

    @classmethod
    def from_json(cls, payload, *, catalog, access, max_bytes=16*1024**2, max_rows=10000):
        _limit(max_bytes, "archive byte budget")
        _limit(max_rows, "archive row budget")
        if not isinstance(payload, str) or len(payload.encode()) > max_bytes:
            raise ValueError("bounded complete private archive JSON required")
        try:
            data = json.loads(payload, object_pairs_hook=_object)
            if type(data) is not dict or type(data.get("rows")) is not list or len(data["rows"]) > max_rows:
                raise ValueError("bounded complete private archive rows required")
            return cls(Record.of(data)).verify(catalog, access)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("complete private archive review required; public views are not reloadable") from error

    def to_dict(self, *, public=False):
        if type(public) is not bool:
            raise ValueError("explicit archive disclosure boolean required")
        data = self.record.data
        if not public:
            return data
        return dict(status=data["status"], status_counts={
            status: sum(row["disposition"] == status for row in data["rows"])
            for status in DISPOSITIONS if any(row["disposition"] == status for row in data["rows"])},
            limitations=list(LIMITATIONS))

    def to_json(self, *, public=False):
        return Record.of(self.to_dict(public=public)).payload
