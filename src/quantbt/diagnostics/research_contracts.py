"""Optional cold-report inputs with explicit chronology and source ownership."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import math

from quantbt.mode5.dossier.records import Record, require_text
from quantbt.mode5.dossier.dossier import Dossier

from .access import AccessWitness
from .evidence import ExecutionEvidence, FrozenBuffer
from .identity import digest


@dataclass(frozen=True)
class DiagnosticTrial:
    trial_id: str
    ordinal: int
    status: str
    evaluation_id: str | None = None
    reason: str | None = None
    elapsed_seconds: float | None = None

    def __post_init__(self):
        require_text(self.trial_id)
        if type(self.ordinal) is not int or self.ordinal < 0 or self.status not in {
                "COMPLETE", "PRUNED", "FAILED", "INFEASIBLE", "CANCELLED"}:
            raise ValueError("exact attempt order and terminal disposition required")
        if self.evaluation_id is not None:
            require_text(self.evaluation_id)
        if self.status == "COMPLETE" and self.evaluation_id is None:
            raise ValueError("completed attempt requires its actual observation")
        if self.status != "COMPLETE":
            require_text(self.reason)
        if self.elapsed_seconds is not None and (type(self.elapsed_seconds) not in {int, float}
                or not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0):
            raise ValueError("finite nonnegative observed attempt time or null required")


@dataclass(frozen=True)
class DiagnosticAccount:
    evaluation_id: str
    observation_identity: str
    evidence: ExecutionEvidence
    initial_equity: float
    monetary_unit: str
    labels: FrozenBuffer | None = None
    label_witness: AccessWitness | None = None
    label_source_ref: str | None = None
    label_names: tuple[tuple[int, str], ...] = ()
    label_purpose: str = "decision_vintage"
    evaluation_mode: str = "CONTINUOUS_PATH_ATTRIBUTION"

    def __post_init__(self):
        for value in (self.evaluation_id, self.observation_identity, self.monetary_unit):
            require_text(value)
        if (not isinstance(self.evidence, ExecutionEvidence)
                or type(self.initial_equity) not in {int, float}
                or not math.isfinite(self.initial_equity) or self.initial_equity <= 0
                or self.evaluation_mode not in {"CONTINUOUS_PATH_ATTRIBUTION", "CONTIGUOUS_RESET_EPISODES"}
                or self.label_purpose not in {"decision_vintage", "asof_calibration_descriptive"}):
            raise ValueError("actual account, initial equity and attribution contract required")
        if self.labels is None:
            if self.label_witness is not None or self.label_source_ref is not None or self.label_names:
                raise ValueError("absent labels cannot claim a labelled environment")
        else:
            if not isinstance(self.labels, FrozenBuffer) or not isinstance(self.label_witness, AccessWitness):
                raise ValueError("immutable labels and their own availability witness required")
            require_text(self.label_source_ref)
            values = self.labels.array()
            if values.ndim != 1 or values.dtype.kind not in "iu" or (values < -1).any():
                raise ValueError("exact daily integer labels; -1 means unknown")
        if (type(self.label_names) is not tuple or len(dict(self.label_names)) != len(self.label_names)
                or any(type(k) is not int or k < -1 or not isinstance(v, str) or not v.strip()
                       for k, v in self.label_names)):
            raise ValueError("immutable distinct source-provided state names required")


@dataclass(frozen=True)
class DiagnosticResearch:
    """An optional report request, never a search or selection policy."""

    context_id: str
    witness: AccessWitness
    source_ref: str
    view: str = "prefix"
    trials: tuple[DiagnosticTrial, ...] = ()
    requested_trials: int | None = None
    accounts: tuple[DiagnosticAccount, ...] = ()
    dossier: Dossier | None = None
    dossier_geometry_ref: Record | None = None

    def __post_init__(self):
        require_text(self.context_id)
        require_text(self.source_ref)
        if (not isinstance(self.witness, AccessWitness)
                or self.view not in {"prefix", "full_development", "retrospective"}
                or type(self.trials) is not tuple or any(not isinstance(t, DiagnosticTrial) for t in self.trials)
                or type(self.accounts) is not tuple or any(not isinstance(a, DiagnosticAccount) for a in self.accounts)):
            raise ValueError("typed frozen research inputs and explicit view required")
        if self.dossier is not None and not isinstance(self.dossier, Dossier):
            raise ValueError("existing typed Dossier required; never a relabelled matrix dictionary")
        if self.dossier_geometry_ref is not None and (self.dossier is None or not isinstance(self.dossier_geometry_ref,Record)):
            raise ValueError("a legacy composite-schema bridge requires a typed catalog reference and dossier")
        if self.requested_trials is not None and (type(self.requested_trials) is not int or self.requested_trials < 1):
            raise ValueError("positive declared trial budget or null required")
        if len({t.trial_id for t in self.trials}) != len(self.trials):
            raise ValueError("duplicate attempt identity")
        if tuple(t.ordinal for t in self.trials) != tuple(range(len(self.trials))):
            raise ValueError("ordered contiguous attempt ledger required; missing slots cannot be hidden")
        if len({a.evaluation_id for a in self.accounts}) != len(self.accounts):
            raise ValueError("one actual account per evaluation; do not duplicate support")

    @property
    def identity(self):
        accounts=[]
        for account in self.accounts:
            labels=account.labels
            accounts.append(dict(evaluation_id=account.evaluation_id,
                observation_identity=account.observation_identity,
                execution_content_id=account.evidence.content_id,
                initial_equity=account.initial_equity,monetary_unit=account.monetary_unit,
                evaluation_mode=account.evaluation_mode,label_purpose=account.label_purpose,
                label_names=account.label_names,label_source_ref=account.label_source_ref,
                label_witness=asdict(account.label_witness) if account.label_witness is not None else None,
                labels=None if labels is None else dict(dtype=labels.dtype,shape=labels.shape,
                    name=labels.name,sha256=sha256(labels.data).hexdigest())))
        return digest(dict(context_id=self.context_id,witness=asdict(self.witness),
            source_ref=self.source_ref,view=self.view,trials=[asdict(t) for t in self.trials],
            requested_trials=self.requested_trials,accounts=accounts,
            dossier_id=self.dossier.record.identity if self.dossier is not None else None,
            dossier_geometry_ref=self.dossier_geometry_ref.data if self.dossier_geometry_ref is not None else None))
