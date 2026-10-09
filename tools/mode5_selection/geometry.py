"""Bridge the qualified M5-06 probe ledger without regenerating strategy probes."""
from tools.mode5_diagnostics.identity import digest
from .contracts import LocalEvidence, Probe


def from_geometry(panel, candidate, neighborhood, evaluations, *, reference_id, reference_scale, validation_ref):
    if neighborhood.role != "selection_probe":
        raise ValueError("held validation probes cannot silently become selection probes")
    ids = tuple(r.point.identity for r in neighborhood.rows if r.status == "READY")
    if set(evaluations) != set(ids) or any(not isinstance(p, Probe) or p.probe_id != key for key, p in evaluations.items()):
        raise ValueError("one typed result for every effective READY probe required")
    statuses = {"SCHEMA_ONLY_NO_CLOUD": "SCHEMA_ONLY_REGISTERED",
        "SCHEMA_ONLY_SPARSE_CLOUD": "SCHEMA_ONLY_INSUFFICIENT",
        "SCHEMA_ONLY_SINGULAR_CLOUD": "SCHEMA_ONLY_INSUFFICIENT",
        "REGULARIZED_PROPOSALS_NOT_HESSIAN": "SCHEMA_PLUS_REGULARIZED_COVARIANCE"}
    return LocalEvidence(candidate.candidate_id, panel.channel, reference_id, reference_scale,
        "weighted_environment_mean_v1", ids, tuple(evaluations[i] for i in ids), neighborhood.coverage["status"],
        statuses[neighborhood.covariance_status], digest(dict(coverage=neighborhood.coverage, seed=neighborhood.seed,
        role=neighborhood.role, covariance_status=neighborhood.covariance_status, effective_probe_ids=ids)), validation_ref)
