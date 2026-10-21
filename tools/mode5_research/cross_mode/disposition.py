"""Cold no-finance dispositions, not execution or scientific certification.

Pins identify the caller's reviewed receipts; they do not establish their truth
or grant new rights. Whole-procedure claims stay untested in this contract.
"""

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .inventory import FilePin, canonical, identity


GATE_IDS = tuple(f"XMR-{number:03d}" for number in range(31, 41))
STATUSES = {"VERIFIED_COLD", "VERIFIED_EXISTING", "DEFERRED_APPROVED", "BLOCKED_UPSTREAM"}
SCOPES = {"COLD_DISPOSITION", "ARCHIVED_SUBSCOPE", "NEW_WHOLE_PROCEDURE"}


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("explicit nonempty identity/reason required")


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("content-pinned SHA256 identity required")


def _pins(values):
    if type(values) is not tuple or not values:
        raise ValueError("nonempty immutable receipt references required")
    seen = set()
    for value in values:
        if not isinstance(value, FilePin):
            raise TypeError("typed file pins required")
        if not isinstance(value.path, str) or "\x00" in value.path:
            raise ValueError("canonical NUL-free evidence path required")
        path = PurePosixPath(value.path)
        if (path.is_absolute() or ".." in path.parts or str(path) in {"", "."}
                or str(path) != value.path):
            raise ValueError("repository-relative evidence path required")
        _digest(value.sha256)
        if type(value.bytes) is not int or value.bytes < 0 or value.path in seen:
            raise ValueError("distinct exact source-byte counts required")
        seen.add(value.path)


@dataclass(frozen=True)
class GateDisposition:
    gate_id: str
    scope: str
    status: str
    reason: str
    evidence: tuple[FilePin, ...]

    def __post_init__(self):
        if self.gate_id not in GATE_IDS or self.scope not in SCOPES or self.status not in STATUSES:
            raise ValueError("known gate, evidence scope and explicit disposition required")
        _text(self.reason)
        _pins(self.evidence)
        if self.scope == "NEW_WHOLE_PROCEDURE" and self.status != "DEFERRED_APPROVED":
            raise ValueError("no-finance handoff cannot certify a new whole procedure")
        if self.status == "VERIFIED_COLD" and self.scope != "COLD_DISPOSITION":
            raise ValueError("cold checks cannot promote archived or market experiment evidence")
        if self.status == "VERIFIED_EXISTING" and self.scope != "ARCHIVED_SUBSCOPE":
            raise ValueError("reused receipts retain their original qualified subscope")


@dataclass(frozen=True)
class MethodDisposition:
    cell_id: str
    method_id: str
    decision: str
    support: str
    reason: str
    evidence: tuple[FilePin, ...]

    def __post_init__(self):
        for value in (self.cell_id, self.method_id, self.reason):
            _text(value)
        if self.decision not in {"KEEP_BASELINE", "RESEARCH_ONLY", "INCONCLUSIVE"}:
            raise ValueError("this handoff cannot activate/promote a research replacement")
        if self.support not in {"DESCRIPTIVE", "INCONCLUSIVE", "INSUFFICIENT", "NOT_EVALUATED"}:
            raise ValueError("explicit bounded scientific support required")
        _pins(self.evidence)


def no_finance_handoff(*, snapshot_id, approval, gates, methods, upstream_blockers):
    """Freeze decisions and missing work without creating observations or rights."""
    _digest(snapshot_id)
    _pins((approval,))
    if type(gates) is not tuple or any(not isinstance(g, GateDisposition) for g in gates):
        raise TypeError("immutable typed gate roster required")
    if len(gates) != len(GATE_IDS) or {g.gate_id for g in gates} != set(GATE_IDS):
        raise ValueError("each XMR-031..040 needs exactly one explicit disposition")
    if type(methods) is not tuple or not methods or any(not isinstance(m, MethodDisposition) for m in methods):
        raise TypeError("nonempty immutable typed method roster required")
    if len({(m.cell_id, m.method_id) for m in methods}) != len(methods):
        raise ValueError("duplicate cell/method disposition")
    if type(upstream_blockers) is not tuple or len(set(upstream_blockers)) != len(upstream_blockers):
        raise ValueError("explicit distinct immutable upstream blockers required")
    for item in upstream_blockers:
        _text(item)
    payload = dict(schema="quantbt.cross_mode.no_finance_disposition.v1",
        status="COMPLETE_LOCAL_APPROVED_NO_NEW_FINANCE_SCOPE", source_snapshot_id=snapshot_id,
        private_only=True, public_export_allowed=False,
        owner_scope_approval=asdict(approval),
        gates=[asdict(g) for g in sorted(gates, key=lambda g: g.gate_id)],
        methods=[asdict(m) for m in sorted(methods, key=lambda m: (m.cell_id, m.method_id))],
        upstream_blockers=list(upstream_blockers),
        current_work=dict(optimizer_proposals=0, financial_invocations=0, model_fits=0,
                          new_forward_days=0, new_qualified_origins=0),
        whole_procedure_qualification="NOT_EVALUATED",
        economic_superiority_certified=False, independent_validation=False,
        baseline_retained=True, public_defaults_changed=False,
        parent_research_accepted=False, package_entry_authorized=False,
        remote_or_release_authorized=False,
        interpretation="readback/disposition only; archived evidence and untested claims retain separate authority")
    payload["disposition_id"] = identity(payload)
    return payload


def restore_no_finance_handoff(payload):
    """Revalidate scope after persistence; an updated hash cannot grant authority."""
    if not isinstance(payload, dict):
        raise TypeError("structured disposition required")
    try:
        for key in ("gates", "methods", "upstream_blockers"):
            if type(payload[key]) is not list:
                raise ValueError("persisted immutable collections use explicit JSON lists")
        gates = tuple(GateDisposition(**{**row, "evidence": tuple(FilePin(**p) for p in row["evidence"])})
                      for row in payload["gates"])
        methods = tuple(MethodDisposition(**{**row, "evidence": tuple(FilePin(**p) for p in row["evidence"])})
                        for row in payload["methods"])
        expected = no_finance_handoff(snapshot_id=payload["source_snapshot_id"],
            approval=FilePin(**payload["owner_scope_approval"]), gates=gates, methods=methods,
            upstream_blockers=tuple(payload["upstream_blockers"]))
    except (KeyError, TypeError) as error:
        raise ValueError("incomplete/unknown disposition fields") from error
    if canonical(expected) != canonical(payload):
        raise ValueError("persisted disposition changed; no implicit gate/authority upgrade")
    return expected
