"""Cold archive eligibility, not accounting verification or execution authority.

Callers bind reviewed metadata to immutable receipts. Content hashes establish
identity, not truth. Every assessment checks the supplied policy and DAG anew.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.diagnostics.identity import AnalysisKey, ExecutionKey, Fingerprint, digest


Disposition = Literal["EXACT_REUSE", "DERIVED_READBACK_ALLOWED", "TARGETED_EXECUTION_REQUIRED",
                      "RIGHTS_FORBIDDEN", "INCOMPATIBLE"]
Status = Literal["COMPLETE", "PENDING", "PARTIAL_INTERRUPTED", "MISSING", "UNAVAILABLE",
                 "UNDEFINED", "INVALID", "PRUNED", "FAILED"]
PURPOSES = {"MODE4_PREFIX": "selection", "MODE5_CALIBRATION": "selection",
            "RETROSPECTIVE_READBACK": "diagnostic", "HELD_ASSESSMENT": "independent_validation"}
KINDS = {"source", "candidate", "outcome", "revision", "analysis", "recipe", "preprocessing"}
REQUIRED_KINDS = {"source", "candidate", "outcome", "revision"}


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("explicit nonempty contract identity/reason required")


def _strings(values, *, nonempty=False):
    if type(values) is not tuple or (nonempty and not values):
        raise ValueError("immutable explicit tuple required")
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise ValueError("duplicate contract references")


@dataclass(frozen=True)
class ArchiveIdentity(Fingerprint):
    execution: ExecutionKey
    analysis: AnalysisKey
    parameter_schema: str
    timeframe: str
    route: str
    start_ns: int
    end_ns: int
    metric_unit: str

    def __post_init__(self):
        if not isinstance(self.execution, ExecutionKey) or not isinstance(self.analysis, AnalysisKey):
            raise ValueError("canonical execution and analysis keys required")
        super().__post_init__()
        if (type(self.start_ns) is not int or type(self.end_ns) is not int
                or self.start_ns >= self.end_ns or self.analysis.execution != self.execution.identity):
            raise ValueError("exact half-open window and execution-bound analysis required")

    @property
    def financial_identity(self):
        return digest({k: v for k, v in asdict(self).items() if k not in {"analysis", "metric_unit"}})


@dataclass(frozen=True)
class DependencyNode(Fingerprint):
    node_id: str
    kind: str
    witness: AccessWitness
    source_cutoff_ns: int | None
    proposal_available_ns: int | None
    revision_available_ns: int | None
    publication_ns: int | None
    actual_execution_ns: int
    dependencies: tuple[str, ...]
    purposes: tuple[str, ...]
    backdating: Literal["PREFIX_SAFE", "NOT_BACKDATABLE"]

    def __post_init__(self):
        super().__post_init__()
        if (self.kind not in KINDS or not isinstance(self.witness, AccessWitness)
                or type(self.actual_execution_ns) is not int
                or self.backdating not in {"PREFIX_SAFE", "NOT_BACKDATABLE"}):
            raise ValueError("typed dependency, actual clock and backdating marker required")
        _strings(self.dependencies)
        _strings(self.purposes, nonempty=True)
        if not set(self.purposes) <= set(PURPOSES.values()):
            raise ValueError("unknown downstream purpose")
        for name in ("source_cutoff_ns", "proposal_available_ns", "revision_available_ns", "publication_ns"):
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                raise ValueError("exact integer availability or explicit unknown required")
        for value in (self.revision_available_ns, self.publication_ns):
            if value is not None and value < self.witness.ready_ns:
                raise ValueError("publication/revision cannot precede outcome readiness")


@dataclass(frozen=True)
class DerivedReadback:
    identity: ArchiveIdentity
    required_inputs: tuple[str, ...]
    reducer: str

    def __post_init__(self):
        if not isinstance(self.identity, ArchiveIdentity):
            raise ValueError("complete target identity required")
        _text(self.reducer)
        _strings(self.required_inputs, nonempty=True)


@dataclass(frozen=True)
class ArchiveEvidence:
    evidence_id: str
    identity: ArchiveIdentity
    candidate_id: str
    execution_id: str
    state_id: str
    content_digest: str
    roots: tuple[str, ...]
    nodes: tuple[DependencyNode, ...]
    status: Status
    reason: str | None
    retained_inputs: tuple[str, ...]
    readbacks: tuple[DerivedReadback, ...]

    def __post_init__(self):
        for value in (self.evidence_id, self.candidate_id, self.execution_id, self.state_id, self.content_digest):
            _text(value)
        if (not isinstance(self.identity, ArchiveIdentity) or len(self.content_digest) != 64
                or any(c not in "0123456789abcdef" for c in self.content_digest)):
            raise ValueError("typed identity and pinned SHA256 required")
        _strings(self.roots, nonempty=True)
        _strings(self.retained_inputs)
        if (type(self.nodes) is not tuple or any(not isinstance(n, DependencyNode) for n in self.nodes)
                or len({n.node_id for n in self.nodes}) != len(self.nodes)
                or type(self.readbacks) is not tuple
                or any(not isinstance(r, DerivedReadback) for r in self.readbacks)):
            raise ValueError("immutable distinct nodes and typed readbacks required")
        if self.status not in {"COMPLETE", "PENDING", "PARTIAL_INTERRUPTED", "MISSING", "UNAVAILABLE",
                               "UNDEFINED", "INVALID", "PRUNED", "FAILED"}:
            raise ValueError("explicit archive disposition required")
        if self.status == "COMPLETE":
            if self.reason is not None:
                raise ValueError("complete metadata has no missingness reason")
        else:
            _text(self.reason)
        if (any(r.identity.financial_identity != self.identity.financial_identity for r in self.readbacks)
                or len({r.identity.identity for r in self.readbacks}) != len(self.readbacks)):
            raise ValueError("distinct same-financial-identity readbacks required")


@dataclass(frozen=True)
class IntendedReuse:
    identity: ArchiveIdentity
    mode: Literal["MODE4_PREFIX", "MODE5_CALIBRATION", "RETROSPECTIVE_READBACK", "HELD_ASSESSMENT"]
    required_inputs: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.identity, ArchiveIdentity) or self.mode not in PURPOSES:
            raise ValueError("typed target and explicit intended use required")
        _strings(self.required_inputs)


@dataclass(frozen=True)
class ReuseAssessment:
    disposition: Disposition
    reasons: tuple[str, ...]
    missing_inputs: tuple[str, ...] = ()

    def __post_init__(self):
        if self.disposition not in {"EXACT_REUSE", "DERIVED_READBACK_ALLOWED", "TARGETED_EXECUTION_REQUIRED",
                                    "RIGHTS_FORBIDDEN", "INCOMPATIBLE"}:
            raise ValueError("unknown reuse disposition")
        _strings(self.reasons, nonempty=True)
        _strings(self.missing_inputs)


def _graph(evidence, intended, policy):
    reasons, missing, seen, active = set(), set(), set(), set()
    nodes = {node.node_id: node for node in evidence.nodes}
    # Iterative DFS retains cycle detection without depending on recursion depth.
    stack = [(root, False) for root in reversed(evidence.roots)]
    while stack:
        ref, leaving = stack.pop()
        if leaving:
            active.remove(ref)
            seen.add(ref)
            continue
        if ref in active:
            reasons.add("dependency cycle: " + ref)
            continue
        if ref in seen:
            continue
        node = nodes.get(ref)
        if node is None:
            reasons.add("missing dependency node: " + ref)
            missing.add("dependency:" + ref)
            continue
        active.add(ref)
        stack.append((ref, True))
        stack.extend((dep, False) for dep in reversed(node.dependencies))
        try:
            policy.require(node.witness)
        except PermissionError as error:
            reasons.add(ref + ": " + str(error))
        if policy.purpose not in node.purposes:
            reasons.add(ref + ": original purpose forbids requested use")
        if intended.mode == "MODE4_PREFIX" and node.backdating == "NOT_BACKDATABLE":
            reasons.add(ref + ": NOT_BACKDATABLE full-development/retrospective dependency")
        for name in ("source_cutoff_ns", "proposal_available_ns", "revision_available_ns", "publication_ns"):
            value = getattr(node, name)
            if value is None:
                reasons.add(ref + ": unknown " + name)
                missing.add(ref + ":" + name)
            elif value > policy.cutoff_ns or (name != "source_cutoff_ns" and value == policy.cutoff_ns):
                reasons.add(ref + ": cutoff excludes " + name)
    for kind in REQUIRED_KINDS - {nodes[ref].kind for ref in seen}:
        reasons.add("missing dependency kind: " + kind)
        missing.add("dependency-kind:" + kind)
    for ref in nodes.keys() - seen:
        reasons.add("unreferenced dependency node: " + ref)
        missing.add("dependency-edge:" + ref)
    return tuple(sorted(reasons)), tuple(sorted(missing))


def assess_reuse(evidence: ArchiveEvidence, intended: IntendedReuse, policy: AccessPolicy) -> ReuseAssessment:
    """Classify each call independently; never return measurements or run a reducer.

    Proposal, publication and revision equality is excluded: no publication-order
    witness exists here. Actual execution time is provenance, not simulated time.
    """
    if not isinstance(evidence, ArchiveEvidence) or not isinstance(intended, IntendedReuse):
        raise TypeError("typed archive evidence and intended reuse required")
    if not isinstance(policy, AccessPolicy):
        raise TypeError("current canonical AccessPolicy required on every call")
    policy.__post_init__()
    reasons, missing = _graph(evidence, intended, policy)
    if policy.purpose != PURPOSES[intended.mode]:
        reasons += ("current policy purpose does not authorize intended use",)
    if reasons:
        return ReuseAssessment("RIGHTS_FORBIDDEN", reasons, missing)
    old, new = evidence.identity, intended.identity
    changed = [name for name in ("parameter_schema", "timeframe", "route")
               if getattr(old, name) != getattr(new, name)]
    for name, value in asdict(old.execution).items():
        if name not in {"initial_state", "account", "terminal", "warmup"} and value != getattr(new.execution, name):
            changed.append("execution." + name)
    if changed:
        return ReuseAssessment("INCOMPATIBLE", tuple("identity mismatch: " + name for name in changed))
    if old.financial_identity != new.financial_identity:
        return ReuseAssessment("TARGETED_EXECUTION_REQUIRED",
                               ("account/state/carry/terminal/history/window mismatch; paths cannot substitute",),
                               ("execution:" + new.financial_identity,))
    if evidence.status != "COMPLETE":
        return ReuseAssessment("TARGETED_EXECUTION_REQUIRED",
                               ("archive status " + evidence.status + ": " + evidence.reason,),
                               ("measurement:" + evidence.evidence_id,))
    readback = next((r for r in evidence.readbacks if r.identity == new), None)
    required = set(intended.required_inputs) | (set(readback.required_inputs) if readback else set())
    missing = tuple(sorted(required - set(evidence.retained_inputs)))
    if missing:
        return ReuseAssessment("TARGETED_EXECUTION_REQUIRED", ("required retained inputs unavailable",), missing)
    if old == new:
        return ReuseAssessment("EXACT_REUSE", ("complete semantic metadata identity; accounting truth not certified",))
    if readback is not None:
        return ReuseAssessment("DERIVED_READBACK_ALLOWED",
                               ("declared source-bound reducer " + readback.reducer + "; not executed",))
    return ReuseAssessment("INCOMPATIBLE", ("analysis/unit mismatch without declared complete-identity readback",),
                           ("readback:" + new.identity,))


def candidate_alias_key(evidence: ArchiveEvidence) -> str:
    """Conservative physical-evaluation grouping only; never permission or a label."""
    if not isinstance(evidence, ArchiveEvidence):
        raise TypeError("typed archive evidence required")
    return digest(dict(identity=evidence.identity.identity, execution=evidence.execution_id, state=evidence.state_id,
                       content=evidence.content_digest,
                       status=evidence.status, reason=evidence.reason, roots=evidence.roots,
                       nodes=sorted((asdict(n) for n in evidence.nodes), key=lambda n: n["node_id"])))
