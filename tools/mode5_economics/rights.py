"""Chronology, held-data roles and real dynamic-stress requests, not matching."""
from dataclasses import dataclass

from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness, VALIDATION_ROLES
from quantbt.mode5.dossier.records import Record


def prefix_rights(inputs, *, access, origin_ns):
    if not isinstance(access, AccessPolicy) or access.purpose != "selection" or access.cutoff_ns != origin_ns:
        raise ValueError("exact origin selection policy required")
    if not inputs:
        raise ValueError("whole diagnostic/candidate-discovery input roster required")
    for kind, witness in inputs:
        if kind not in {"diagnostics", "candidate_discovery", "preprocessing", "recipe", "labels", "market"}:
            raise ValueError("explicit pipeline input responsibility required")
        access.require(witness)
    if not {"diagnostics", "candidate_discovery", "recipe", "market"}.issubset({k for k, _ in inputs}):
        raise ValueError("complete pipeline rights, not only final training bars, required")
    return Record.of(dict(status="PREFIX_RIGHTS_VERIFIED", origin_ns=origin_ns,
        inputs=[dict(kind=k, witness=w.identity) for k, w in inputs], whole_procedure_validation=False))


def validation_rights(*, frozen_at_ns, first_execution_ns, witness, access, reviewed_witnesses=(),
                      requested_claim="reviewed_exploratory", parent_claim="none_full_sample_calibration"):
    if (type(frozen_at_ns) is not int or type(first_execution_ns) is not int
            or not frozen_at_ns < first_execution_ns or not isinstance(witness, AccessWitness)):
        raise PermissionError("actual full-pipeline freeze must precede validation execution")
    if parent_claim != "none_full_sample_calibration":
        raise ValueError("validation cannot change the parent calibration claim")
    if requested_claim not in {"reviewed_exploratory", "independent_fixed_vector"}:
        raise ValueError("explicit supported validation claim required")
    access.require(witness)
    overlap = any(w.manifest_id == witness.manifest_id and w.start_ns < witness.end_ns
                  and witness.start_ns < w.end_ns for w in reviewed_witnesses)
    independent = requested_claim == "independent_fixed_vector"
    if independent and (access.purpose != "independent_validation" or witness.role not in VALIDATION_ROLES or overlap):
        raise PermissionError("reviewed/unauthorized histories cannot be laundered into independent validation")
    return Record.of(dict(status="AUTHORIZED", validation_claim=requested_claim,
        parent_validation_claim=parent_claim, reviewed_overlap=overlap, witness_id=witness.identity,
        protocol_frozen_at_ns=frozen_at_ns, first_execution_ns=first_execution_ns,
        whole_procedure_uncertainty=False, deployment_authorized=False))


def cached_validation_rights(*, witness, access, source_receipt_id, requested_claim="reviewed_exploratory"):
    """Reverified historical paths are not new post-freeze financial executions."""
    if requested_claim != "reviewed_exploratory":
        raise PermissionError("historical cache reuse cannot certify independent validation")
    if not isinstance(source_receipt_id, str) or not source_receipt_id:
        raise ValueError("immutable qualified original execution receipt required")
    if not isinstance(access, AccessPolicy) or access.purpose not in {"diagnostic", "validation"}:
        raise ValueError("explicit cached diagnostic access, not new selection authority, required")
    access.require(witness)
    return Record.of(dict(status="CACHED_DIAGNOSTIC_AUTHORIZED", validation_claim=requested_claim,
        witness_id=witness.identity, source_receipt_id=source_receipt_id,
        reexecuted_account=False, new_post_freeze_execution=False,
        deployment_authorized=False, whole_procedure_validation=False))


@dataclass(frozen=True)
class StressRequest:
    baseline_execution_id: str
    params_digest: str
    stressed_economic_contract: str
    changed_policy: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v for v in self.__dict__.values()):
            raise ValueError("explicit baseline/vector/stressed contract and policy required")

    def execute(self, run):
        """The caller supplies the original QuantBT endpoint; no fixed-fill proxy."""
        result = run(self)
        if (result.get("method") != "ACTUAL_ACCOUNT_RESIMULATION"
                or result.get("params_digest") != self.params_digest
                or result.get("economic_contract") != self.stressed_economic_contract
                or not result.get("execution_id") or not result.get("accounting_verified")):
            raise ValueError("stress requires exact actual endpoint/vector/account output; proxy is diagnostic only")
        return Record.of(result)
