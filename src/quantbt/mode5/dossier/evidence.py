"""Verified source snapshots and exact, independently registered matrix rosters."""
from dataclasses import asdict, dataclass
from pathlib import Path
import json

from quantbt.mode5.artifacts import file_identity
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from .records import Record, pointer, require_text

KINDS = ("parameter_representation", "candidate_environment", "center_neighbor_environment",
         "environment_environment", "recipe_split_seed", "execution_stress")


@dataclass(frozen=True)
class Source:
    source_id: str
    path: str
    sha256: str
    bytes: int
    witness: AccessWitness

    def __post_init__(self):
        require_text(self.source_id)
        if (len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256)
                or type(self.bytes) is not int or self.bytes < 0
                or not isinstance(self.witness, AccessWitness)):
            raise ValueError("typed content/access identity required")


class EvidenceCatalog:
    """One verified immutable snapshot per source, scoped to one assembly."""
    def __init__(self, sources, policy):
        sources = tuple(sources)
        if not isinstance(policy, AccessPolicy) or policy.purpose != "diagnostic":
            raise ValueError("diagnostic access required")
        if not sources or len({s.source_id for s in sources}) != len(sources):
            raise ValueError("distinct source identities required")
        self._sources, self._records = {}, {}
        self.policy = policy
        for source in sources:
            policy.require(source.witness)
            actual = file_identity(Path(source.path))
            if actual["sha256"] != source.sha256 or actual["bytes"] != source.bytes:
                raise ValueError("evidence content changed")
            payload = Path(source.path).read_bytes()
            # Bind the bytes actually parsed, not just an earlier stat/hash check.
            from hashlib import sha256
            if len(payload) != source.bytes or sha256(payload).hexdigest() != source.sha256:
                raise ValueError("evidence changed during read")
            self._sources[source.source_id] = source
            self._records[source.source_id] = json.loads(Record.of({"value": json.loads(payload)}).payload)["value"]

    def read(self, source_id, path=""):
        return Record.of({"value": pointer(self._records[source_id], path)}).data["value"]

    def verify_current(self):
        for source in self._sources.values():
            actual = file_identity(Path(source.path))
            if actual["sha256"] != source.sha256 or actual["bytes"] != source.bytes:
                raise ValueError("source changed since the verified snapshot")

    def ref(self, source_id, path=""):
        self.read(source_id, path)
        return {"source": source_id, "pointer": path,
                "sha256": self._sources[source_id].sha256}

    @property
    def manifest(self):
        return Record.of({"sources": [asdict(s) for s in self._sources.values()],
                          "access": asdict(self.policy)})

    def require_ref(self, ref):
        if ref != self.ref(ref["source"], ref["pointer"]):
            raise ValueError("reference digest mismatch")
        return self.read(ref["source"], ref["pointer"])


@dataclass(frozen=True)
class Matrix:
    record: Record

    @classmethod
    def assemble(cls, kind, roster, catalog):
        if kind not in KINDS or not isinstance(roster, Record):
            raise ValueError("typed matrix/roster required")
        expected = roster.data
        if expected.get("kind") != kind:
            raise ValueError("wrong roster kind")
        entries = expected["entries"]
        ids = [e["row_id"] for e in entries]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("distinct expected rows required")
        rows = []
        for entry in entries:
            require_text(entry["row_id"])
            raw = catalog.require_ref(entry["ref"])
            rows.append({**entry, "value": raw})
        return cls(Record.of({"kind": kind, "roster_id": roster.identity,
                              "roster": expected, "rows": rows}))

    def verify(self, roster, catalog):
        if self != self.assemble(self.record.data["kind"], roster, catalog):
            raise ValueError("omitted, altered, reordered or extra matrix row")


def reconcile_rosters(rosters, registered_inventory):
    """Inventory must be frozen independently, not derived from retained successes."""
    actual = {r.data["kind"]: [e["row_id"] for e in r.data["entries"]] for r in rosters}
    if len(rosters) != len(KINDS) or actual != registered_inventory.data:
        raise ValueError("six expected matrix rosters must reconcile exactly")
