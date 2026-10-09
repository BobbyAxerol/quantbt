"""Authorization adapter over the shared bounded cache; no financial state."""

from dataclasses import dataclass
import json
from threading import RLock

from .evidence import ExecutionEvidence
from .identity import canonical


@dataclass(frozen=True)
class AnalysisEvidence:
    execution_id: str
    witness: object
    encoded: str


class DiagnosticReuse:
    def __init__(self, cache, *, access_log):
        self.cache = cache
        self.access_log = access_log
        self.executions = 0
        self._lock = RLock()

    def _authorize(self, witness, policy, *, layer, identity):
        row = dict(layer=layer, identity=identity, witness=witness.identity, policy=policy.identity)
        try:
            policy.require(witness)
        except PermissionError:
            self.access_log({**row, "decision": "DENIED"})
            raise
        self.access_log({**row, "decision": "AUTHORIZED"})

    def evaluate(self, key, witness, policy, plan, execute, *, allow_execution=True):
        self._authorize(witness, policy, layer="execution_request", identity=key.identity)
        # Shared LRU is thread-safe; serialize identical misses as well. There
        # is no adaptive ask/tell scheduling or account timeline in this owner.
        with self._lock:
            with self.cache.borrow(("m5_execution_v1", key.identity)) as prior:
                if prior is not None:
                    self._authorize(prior.witness, policy, layer="execution_hit", identity=key.identity)
                    if prior.witness != witness:
                        raise PermissionError("cached source manifest cannot be relabelled")
                    return prior.require(plan), "REUSED"
            if not allow_execution:
                raise ValueError("AUDIT_ONLY: missing compatible execution; explicit registered replay required")
            self.executions += 1
            output = execute(plan)
            if not isinstance(output, ExecutionEvidence) or output.execution_id != key.identity or output.witness != witness:
                raise ValueError("execution lineage does not match registered request")
            self._authorize(output.witness, policy, layer="execution_output", identity=key.identity)
            output.require(plan)
            retained = self.cache.put(("m5_execution_v1", key.identity), output, size_bytes=output.size_bytes)
            return output, "EXECUTED_RETAINED" if retained else "EXECUTED_BUDGET_BYPASS"

    def retain_existing(self, key, evidence, policy, plan):
        """Import only already-qualified manifest-bound inputs, not summaries."""
        if not isinstance(evidence, ExecutionEvidence) or key.identity != evidence.execution_id:
            raise ValueError("retained execution lineage mismatch")
        self._authorize(evidence.witness, policy, layer="existing_evidence_import", identity=key.identity)
        evidence.require(plan)
        with self._lock:
            return self.cache.put(("m5_execution_v1", key.identity), evidence, size_bytes=evidence.size_bytes)

    def analyze(self, key, evidence, policy, reduce):
        self._authorize(evidence.witness, policy, layer="analysis_request", identity=key.identity)
        if key.execution != evidence.execution_id:
            raise ValueError("analysis execution identity mismatch")
        # Retention can be upgraded only explicitly; don't reuse an old
        # analysis against different retained content under the same run ID.
        slot = ("m5_analysis_v1", key.identity, evidence.content_id)
        with self._lock:
            with self.cache.borrow(slot) as prior:
                if prior is not None:
                    self._authorize(prior.witness, policy, layer="analysis_hit", identity=key.identity)
                    return json.loads(prior.encoded), "REUSED"
            encoded = canonical(reduce(evidence))
            output = AnalysisEvidence(evidence.execution_id, evidence.witness, encoded)
            self.cache.put(slot, output, size_bytes=len(encoded.encode())+len(canonical(
                {"execution": output.execution_id, "witness": output.witness.identity}).encode()))
            return json.loads(encoded), "REDUCED"

    def require_selection(self, key, analyses, evidences, policy):
        if policy.purpose == "independent_validation":
            self.access_log(dict(layer="selection", identity=key.identity,
                policy=policy.identity, decision="DENIED", reason="validation is not selection permission"))
            raise PermissionError("independent validation cannot authorize selection")
        if key.access_scope != policy.identity or tuple(k.identity for k in analyses) != key.analyses:
            raise ValueError("selection scope/ordered analysis identity mismatch")
        if len(analyses) != len(evidences):
            raise ValueError("incomplete selection panel")
        for analysis, evidence in zip(analyses, evidences):
            if analysis.execution != evidence.execution_id:
                raise ValueError("selection execution identity mismatch")
            self._authorize(evidence.witness, policy, layer="selection", identity=key.identity)
