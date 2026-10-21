"""Explicit archive coordinates, never old scores or automatic donor ranking.

Build CoordinateDonorTarget.from_contract from the actual destination's
IntendedReuse, with parameter_schema equal to its NormalizedSearchSpace identity.
Embed the complete private plan in the worksheet/pack before sealing. At load
and execution preflight, supply the current destination, geometry, trial budget,
catalog and access again to verify or warm_start_records. Changing any binding
requires a new researcher choice and parent seal; this module executes nothing.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
import math
from typing import Literal

import pandas as pd

from quantbt.mode5.dossier.evidence import EvidenceCatalog
from quantbt.mode5.dossier.records import Record, require_text
from quantbt.optimization.parameter_space import NormalizedSearchSpace

from ..access import AccessPolicy, AccessWitness
from ..archive import ArchiveReview, _object, _ref, _restore
from ..archive_contracts import ArchiveEvidence, IntendedReuse, assess_reuse
from ..geometry.schema import EffectiveGeometry
from ..identity import digest


SCHEMA = "quantbt.archive_coordinate_donors.v1"
TARGET_SCHEMA = "quantbt.coordinate_donor_target.v1"
MAX_BYTES = 16 * 1024**2
MAX_DONORS = 10000
MAX_PARAMS = 256
MAX_PARAM_BYTES = 64 * 1024
REEVALUATION_REASON = "Coordinates only; fresh current-contract evaluation consumes proposal slots."
LIMITATIONS = (
    REEVALUATION_REASON,
    "No scores, observations, model state, account paths or automatic ranking are imported.",
    "Source identity and access eligibility do not establish economic benefit or execution authority.",
    "Full-development dependencies cannot be backdated for a Mode4 prefix.",
)


@dataclass(frozen=True)
class CoordinateDonorTarget:
    """Versioned coordinate-compatible subset of an actual destination contract.

    Account/initial-state/reset, terminal and scored window are omitted
    deliberately: only coordinates are reused. Analysis/metric identities and
    the destination's current parameter point are not imported either. All
    remaining execution semantics, including scenario seed, must match exactly.
    costs is the original ExecutionKey.costs economics fingerprint, not a
    display label or an inferred equivalence between account configurations.
    """

    strategy_identity: str
    space_identity: str
    market_snapshot: str
    instrument: str
    timeframe: str
    clock: str
    route: str
    costs: str
    funding: str
    warmup: str
    scenario_seed: int
    source_backend: str
    mode: Literal["MODE4_PREFIX", "MODE5_CALIBRATION"]
    version: str = TARGET_SCHEMA

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name != "scenario_seed":
                require_text(value)
        if (self.version != TARGET_SCHEMA or self.mode not in {"MODE4_PREFIX", "MODE5_CALIBRATION"}
                or type(self.scenario_seed) is not int):
            raise ValueError("versioned coordinate target and exact scenario seed required")
        _sha256(self.space_identity)

    @property
    def identity(self):
        return digest(asdict(self))

    @classmethod
    def from_contract(cls, intended):
        if not isinstance(intended, IntendedReuse):
            raise TypeError("actual typed destination IntendedReuse required")
        identity, execution = intended.identity, intended.identity.execution
        return cls(execution.alpha_code, identity.parameter_schema, execution.market_snapshot,
            execution.instrument, identity.timeframe, execution.clock, identity.route,
            execution.costs, execution.funding, execution.warmup, execution.scenario_seed,
            execution.source_backend, intended.mode)


def _sha256(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("canonical SHA256 identity required")


def _budget(value):
    if type(value) is not int or not 1 <= value <= MAX_DONORS:
        raise ValueError("positive exact trial budget bounded by 10000 required")


def _params(value):
    if type(value) is not dict or not value or len(value) > MAX_PARAMS:
        raise ValueError("bounded nonempty effective parameter dictionary required")
    for name, item in value.items():
        require_text(name)
        if (type(item) not in (str, int, float, bool, type(None))
                or (type(item) is float and not math.isfinite(item))):
            raise ValueError("finite typed scalar effective parameters required")
    if len(Record.of(value).payload.encode()) > MAX_PARAM_BYTES:
        raise ValueError("effective parameter byte budget exceeded")
    return dict(value)


def _space(geometry):
    if not isinstance(geometry, EffectiveGeometry):
        raise TypeError("shared EffectiveGeometry required")
    geometry.__post_init__()
    ranges = {s.name: ({"kind": "fixed", "value": s.value} if s.fixed else {
        "kind": s.kind,
        **({"choices": list(s.choices)} if s.choices else {
            "low": s.low, "high": s.high, "step": s.step, "log": s.log}),
        **({"active_if": dict(s.active_if)} if s.active_if else {})}) for s in geometry.specs}
    space = NormalizedSearchSpace(ranges)
    if space.specs != geometry.specs:
        raise ValueError("geometry must preserve the existing sampler schema and dimension order")
    return space


def _effective(params, geometry, space):
    params = _params(params)
    # A ref names already-effective coordinates, not a request for casting,
    # missing fixed values, inactive-key removal or other silent repair.
    expected = Record.of(params)
    if (Record.of(geometry.resolve(params).params) != expected
            or Record.of(space.effective(params)) != expected):
        raise ValueError("coordinate ref must contain exact canonical effective params; no repair")
    return params


def _rows(review):
    rows = review.record.data["rows"]
    if len(rows) > MAX_DONORS:
        raise ValueError("archive review row budget exceeded")
    indexed = {row["evidence_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("duplicate archive evidence_id is ambiguous")
    return indexed


def _admit(row, ref, witness, params, access, target):
    evidence = _restore(ArchiveEvidence, row["declared_inputs"]["evidence"])
    intended = _restore(IntendedReuse, row["declared_inputs"]["intended"])
    if evidence.status != "COMPLETE":
        raise ValueError("COMPLETE archive donor required: " + evidence.evidence_id)
    assessment = assess_reuse(evidence, intended, access)
    if assessment.disposition == "RIGHTS_FORBIDDEN":
        raise PermissionError("forbidden donor dependency: " + "; ".join(assessment.reasons))
    if CoordinateDonorTarget.from_contract(intended) != target:
        raise ValueError("donor review does not bind the declared destination target")
    source_target = CoordinateDonorTarget.from_contract(IntendedReuse(evidence.identity, target.mode))
    if source_target != target:
        raise ValueError("incompatible donor strategy/schema/market/clock/route/economics/history/backend")
    if digest(params) != evidence.identity.execution.effective_params:
        raise ValueError("coordinate digest differs from archive execution.effective_params")

    archive_witness = _restore(AccessWitness, row["source_witness"])
    clocks = []
    # Actual execution wall time is provenance, not historical availability.
    for source_witness in (archive_witness, witness):
        access.require(source_witness)
        clocks.extend((source_witness.end_ns, source_witness.ready_ns))
    for node in evidence.nodes:
        access.require(node.witness)
        clocks.extend((node.witness.end_ns, node.witness.ready_ns,
            node.source_cutoff_ns, node.proposal_available_ns,
            node.revision_available_ns, node.publication_ns))
    if any(type(clock) is not int for clock in clocks):
        raise PermissionError("known exact donor dependency clocks required")
    latest = max(clocks)
    if latest >= access.cutoff_ns:
        raise PermissionError("latest donor availability must be strictly before current cutoff")
    donor = dict(evidence_id=evidence.evidence_id, archive_ref=_ref(row["ref"]),
        coordinate_ref=_ref(ref), coordinate_witness=asdict(witness),
        params_digest=digest(params), available_ns=latest,
        review_disposition=row["disposition"], review_reasons=row["reasons"], reason=REEVALUATION_REASON)
    warm = dict(params=params, available_at=pd.Timestamp(latest, unit="ns", tz="UTC").isoformat(),
        space_identity=target.space_identity, strategy_identity=target.strategy_identity)
    return donor, warm


@dataclass(frozen=True)
class ArchiveDonorPlan:
    """Immutable explicit donor roster; no cached approval grants future access."""

    record: Record

    def __post_init__(self):
        if not isinstance(self.record, Record) or len(self.record.payload.encode()) > MAX_BYTES:
            raise ValueError("bounded immutable donor plan Record required")
        d = self.record.data
        required = {"schema", "review", "review_id", "access_id", "target", "target_id",
            "geometry", "geometry_id", "researcher", "reason", "budget", "donors", "warm_start",
            "automatic_ranking", "score_reuse", "limitations"}
        if (set(d) != required or d["schema"] != SCHEMA
                or d["automatic_ranking"] is not False or d["score_reuse"] is not False
                or d["limitations"] != list(LIMITATIONS)):
            raise ValueError("complete versioned coordinates-only donor plan required")
        _budget(d["budget"])
        require_text(d["researcher"])
        require_text(d["reason"])
        review = ArchiveReview(Record.of(d["review"]))
        target = _restore(CoordinateDonorTarget, d["target"])
        access = _restore(AccessPolicy, d["review"]["access_policy"])
        if (review.identity != d["review_id"] or access.identity != d["access_id"]
                or access.purpose != "selection" or target.identity != d["target_id"]
                or type(d["geometry"]) is not dict or digest(d["geometry"]) != d["geometry_id"]):
            raise ValueError("donor review/access/target/geometry binding differs")
        if (type(d["donors"]) is not list or type(d["warm_start"]) is not list
                or not 1 <= len(d["donors"]) <= d["budget"]
                or len(d["donors"]) != len(d["warm_start"])):
            raise ValueError("nonempty ordered donor roster within declared trial budget required")
        rows, seen_ids, seen_params = _rows(review), set(), set()
        try:
            for donor, warm in zip(d["donors"], d["warm_start"], strict=True):
                evidence_id = donor["evidence_id"]
                if evidence_id in seen_ids or evidence_id not in rows:
                    raise ValueError("duplicate or missing explicit donor evidence_id")
                params = _params(warm["params"])
                params_id = digest(params)
                if params_id in seen_params:
                    raise ValueError("duplicate effective donor params")
                rebuilt = _admit(rows[evidence_id], donor["coordinate_ref"],
                    _restore(AccessWitness, donor["coordinate_witness"]), params, access, target)
                if Record.of(dict(donor=donor, warm=warm)) != Record.of(dict(donor=rebuilt[0], warm=rebuilt[1])):
                    raise ValueError("donor rows or warm_start differ from frozen original inputs")
                seen_ids.add(evidence_id)
                seen_params.add(params_id)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("complete typed donor rows and canonical warm_start required") from error

    @classmethod
    def create(cls, *, review, choices, catalog, access, target, geometry,
               researcher, reason, budget):
        """Freeze mapping iteration order: evidence_id -> catalog.ref(params).

        Each ref must resolve to an already-effective scalar parameter dict.
        Archive review dispositions describe score/path reuse, not coordinate
        authority: a lawful account/window mismatch may still donate coordinates.
        """
        _budget(budget)
        require_text(researcher)
        require_text(reason)
        if not isinstance(review, ArchiveReview) or not isinstance(catalog, EvidenceCatalog):
            raise TypeError("typed ArchiveReview and verified EvidenceCatalog required")
        if not isinstance(access, AccessPolicy) or access.purpose != "selection":
            raise TypeError("current canonical selection AccessPolicy required")
        access.__post_init__()
        if not isinstance(target, CoordinateDonorTarget):
            raise TypeError("typed versioned CoordinateDonorTarget required; opaque targets forbidden")
        target.__post_init__()
        space = _space(geometry)
        if target.space_identity != space.identity:
            raise ValueError("target space_identity differs from current sampler geometry")
        if not isinstance(choices, Mapping) or not choices or len(choices) > budget:
            raise ValueError("explicit nonempty researcher-ordered choices within trial budget required")
        chosen = tuple((evidence_id, _ref(ref)) for evidence_id, ref in choices.items())
        for evidence_id, _ in chosen:
            require_text(evidence_id)
        if len({evidence_id for evidence_id, _ in chosen}) != len(chosen):
            raise ValueError("duplicate explicit donor evidence_id")
        review.verify(catalog, access)
        rows = _rows(review)
        sources = {source["source_id"]: source for source in catalog.manifest.data["sources"]}
        donors, starts, seen = [], [], set()
        for evidence_id, ref in chosen:
            if evidence_id not in rows:
                raise ValueError("missing explicit archive donor: " + evidence_id)
            if ref["source"] not in sources:
                raise ValueError("coordinate source absent from verified catalog")
            witness = _restore(AccessWitness, sources[ref["source"]]["witness"])
            access.require(witness)
            params = _effective(catalog.require_ref(ref), geometry, space)
            if digest(params) in seen:
                raise ValueError("duplicate effective donor params")
            donor, warm = _admit(rows[evidence_id], ref, witness, params, access, target)
            donors.append(donor)
            starts.append(warm)
            seen.add(digest(params))
        catalog.verify_current()
        return cls(Record.of(dict(schema=SCHEMA, review=review.to_dict(), review_id=review.identity,
            access_id=access.identity, target=asdict(target), target_id=target.identity,
            geometry=geometry.metadata(), geometry_id=geometry.identity,
            researcher=researcher, reason=reason, budget=budget, donors=donors, warm_start=starts,
            automatic_ranking=False, score_reuse=False, limitations=LIMITATIONS)))

    @property
    def identity(self):
        return self.record.identity

    def verify(self, *, catalog, access, target, geometry, budget):
        """Rebuild every source, DAG, clock and destination binding now."""
        d = self.record.data
        if budget != d["budget"] or type(budget) is not int:
            raise ValueError("changed trial budget requires a revised donor choice and seal")
        rebuilt = self.create(review=ArchiveReview(Record.of(d["review"])),
            choices={row["evidence_id"]: row["coordinate_ref"] for row in d["donors"]},
            catalog=catalog, access=access, target=target, geometry=geometry,
            researcher=d["researcher"], reason=d["reason"], budget=budget)
        if rebuilt != self:
            raise ValueError("donor plan differs from current source/target/geometry; revise choice and seal")
        return self

    def warm_start_records(self, *, catalog, access, target, geometry, budget):
        """Freshly verified four-field records for existing sampler_warm_start."""
        self.verify(catalog=catalog, access=access, target=target, geometry=geometry, budget=budget)
        return tuple(self.record.data["warm_start"])

    @classmethod
    def from_json(cls, payload, *, catalog, access, target, geometry, budget,
                  max_bytes=MAX_BYTES, max_donors=MAX_DONORS):
        if (type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES
                or type(max_donors) is not int or not 1 <= max_donors <= MAX_DONORS):
            raise ValueError("positive bounded donor byte/row limits required")
        if type(payload) is not str or len(payload.encode()) > max_bytes:
            raise ValueError("bounded complete private donor JSON required")
        try:
            data = json.loads(payload, object_pairs_hook=_object)
            if (type(data) is not dict or type(data.get("donors")) is not list
                    or len(data["donors"]) > max_donors):
                raise ValueError("bounded complete private donor rows required")
            return cls(Record.of(data)).verify(catalog=catalog, access=access,
                target=target, geometry=geometry, budget=budget)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("complete private donor plan required; public views are not reloadable") from error

    def to_dict(self, *, public=False):
        if type(public) is not bool:
            raise ValueError("explicit donor disclosure boolean required")
        d = self.record.data
        if not public:
            return d
        return dict(schema=SCHEMA, donor_count=len(d["donors"]), budget=d["budget"],
            automatic_ranking=False, score_reuse=False, limitations=list(LIMITATIONS))

    def to_json(self, *, public=False):
        return Record.of(self.to_dict(public=public)).payload
