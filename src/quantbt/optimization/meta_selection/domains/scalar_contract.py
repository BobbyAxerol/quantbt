"""E03 scalar admission: describe existing execution, never implement finance."""

from dataclasses import dataclass

from ..common import MetaRecordError, digest


ALIASES = {"single_signal": "signal_notional", "%_equity": "pct_equity"}
SCALAR_ROUTES = frozenset(("signal_notional", "pct_equity", "notional", "unit", "dca_ladder"))


def canonical_scalar_route(route):
    name = str(route).lower().strip()
    return ALIASES.get(name, name)


def validate_scalar_payload(payload, index, route):
    import numpy as np
    import pandas as pd

    if not isinstance(payload, pd.Series) or not payload.index.equals(index):
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: exact scalar target Series required")
    values = payload.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: finite scalar targets required")
    if canonical_scalar_route(route) == "dca_ladder" and not np.equal(values, np.trunc(values)).all():
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: ladder targets are signed integer structural caps")


@dataclass(frozen=True, slots=True)
class ScalarExecutionContract:
    route: str
    backend: str
    timing: str
    sizing: str
    legacy_family: bool
    ladder_policy_id: str = "not_applicable"
    schema: str = "qms-scalar-execution-e03-v1"

    @property
    def scorer_contract(self):
        if self.legacy_family:
            return "original-endpoint-reset-v1"
        return f"{self.schema}/{self.route}/{self.backend}/{self.timing}/{self.ladder_policy_id}"


def scalar_execution_contract(config, wf_config):
    from ....endpoint import _resolve_backend, _walkforward_scoring_config

    route = canonical_scalar_route(wf_config.target_mode)
    if route not in SCALAR_ROUTES:
        raise MetaRecordError(f"META_ROUTE_UNSUPPORTED: scalar route {route!r}")
    expected = {"pct_equity": {"pct_equity", "%_equity"},
                "signal_notional": {"signal_notional", "signal"},
                "dca_ladder": {"dca_ladder", "dca"}}.get(route, {route})
    if config.sizing not in expected:
        raise MetaRecordError("META_DOMAIN_SIZING_MISMATCH: target_mode and hedge_type/sizing differ")
    score = _walkforward_scoring_config(config, wf_config.target_mode)
    backend = _resolve_backend(score)
    final_backend = _resolve_backend(config)
    if route in {"pct_equity", "dca_ladder"}:
        if final_backend != "legacy":
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: legacy scalar sizing cannot substitute another backend")
    elif backend != final_backend or backend not in {"legacy", "native_vectorized", "native_event"}:
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: scalar scorer/final financial backend mismatch")
    if backend == "legacy":
        # The original compatibility engine consumes fee/slippage, not V2
        # overrides. Reject disagreement rather than change old accounting.
        reason = None
        if abs(config.v2_fee_rate - config.fee / 2.0) > 1e-15:
            reason = "legacy fee_rate must equal fee / 2"
        elif config.execution.slippage_rate and abs(config.execution.slippage_rate - config.slippage) > 1e-15:
            reason = "legacy slippage and slippage_bps disagree"
        if reason is not None:
            if route == "pct_equity" and wf_config.metadata.get("native_prepared_wfo", "off") == "require":
                from ....backends.native_wfo_public import NativePreparedPublicWfoUnsupported
                raise NativePreparedPublicWfoUnsupported(reason)
            raise MetaRecordError(f"META_DOMAIN_ECONOMICS_MISMATCH: {reason}")
    if route == "dca_ladder":
        if wf_config.metadata.get("native_prepared_wfo", "off") == "require":
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: structural ladder has no prepared-native scorer")
        timing = "structural-high-low-limits-close-base-v1"
    elif backend == "native_event":
        if wf_config.metadata.get("native_prepared_wfo", "off") == "require":
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: event rebalance cannot use same-close prepared targets")
        timing = "original-native-event-rebalance-v1"
    elif route == "pct_equity":
        timing = "legacy-equity-transition-v1"
    else:
        timing = "original-close-target-v1"
    legacy = route == "pct_equity" or (route == "signal_notional" and backend == "native_vectorized")
    ladder = digest(config.dca_kwargs) if route == "dca_ladder" else "not_applicable"
    return ScalarExecutionContract(route, backend, timing, score.sizing, legacy, ladder)
