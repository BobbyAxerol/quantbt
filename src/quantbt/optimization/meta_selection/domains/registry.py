"""Bounded route admission; registration is not empirical promotion."""

from dataclasses import dataclass

from ..common import MetaRecordError
from .contracts import DOMAIN_ABI, InputKind


@dataclass(frozen=True, slots=True)
class DomainCapability:
    route: str
    domain: str
    input_kind: InputKind
    software_status: str
    owner_phase: str
    empirical_status: str = "NOT_ASSESSED_FOR_EXTENSION"
    abi: str = DOMAIN_ABI

    @property
    def activated(self):
        return self.software_status in {"QUALIFIED_EXISTING", "SOFTWARE_VALIDATED_OPT_IN"}


# Future routes have explicit pending gates, never speculative executable adapters.
CAPABILITIES = (
    DomainCapability("signal_notional", "scalar", InputKind.SCALAR_TARGET, "QUALIFIED_EXISTING", "E03", "EXISTING_BOUNDED_EVIDENCE"),
    DomainCapability("pct_equity", "scalar", InputKind.SCALAR_TARGET, "QUALIFIED_EXISTING", "E03", "EXISTING_BOUNDED_EVIDENCE"),
    *[DomainCapability(route, "scalar", InputKind.SCALAR_TARGET, "SOFTWARE_VALIDATED_OPT_IN", "E03", "OWNER_EMPIRICAL_REVIEW_PENDING")
      for route in ("notional", "unit", "dca_ladder")],
    DomainCapability("portfolio", "portfolio", InputKind.POSITION_MATRIX, "SOFTWARE_VALIDATED_OPT_IN", "E04", "REAL_ALPHA_OWNER_REVIEW_PENDING"),
    *[DomainCapability(route, "package", InputKind.PACKAGE, "SOFTWARE_VALIDATED_OPT_IN", "E05", "REAL_PACKAGE_ALPHA_OWNER_REVIEW_PENDING")
      for route in ("basket", "arbitrage")],
    DomainCapability("intrabar", "intrabar", InputKind.INTRABAR_INTENT, "NO_PUBLIC_WFO_ADAPTER", "E06"),
    DomainCapability("reactive_reset", "reactive", InputKind.REACTIVE_WINDOW, "QUALIFIED_EXISTING", "E07", "ENGINEERING_ONLY_DOMAIN_ALPHA_PENDING"),
    DomainCapability("order_commands", "orders", InputKind.ORDER_COMMANDS, "NO_PUBLIC_WFO_ADAPTER", "E07"),
    DomainCapability("options", "options", InputKind.PACKAGE, "FUTURE_ROUTE_ADMISSION", "FUTURE"),
    DomainCapability("nautilus_validation", "nautilus", InputKind.SCALAR_TARGET, "FUTURE_ROUTE_ADMISSION", "FUTURE"),
)


def capability(route, *, abi=DOMAIN_ABI, require_active=False):
    from .scalar_contract import canonical_scalar_route
    route = canonical_scalar_route(route)
    if abi != DOMAIN_ABI:
        raise MetaRecordError("META_DOMAIN_ABI_UNSUPPORTED")
    found = next((row for row in CAPABILITIES if row.route == route), None)
    if found is None:
        raise MetaRecordError(f"META_ROUTE_UNSUPPORTED: unregistered domain route {route!r}")
    if require_active and not found.activated:
        raise MetaRecordError(f"META_ROUTE_UNSUPPORTED: {route}; {found.software_status}; gate {found.owner_phase}")
    return found


def route_metadata(route):
    row = capability(route)
    return dict(meta_domain=row.domain, meta_input_kind=row.input_kind.value,
        meta_adapter_abi=row.abi, meta_software_status=row.software_status,
        meta_empirical_status=row.empirical_status, meta_gate_phase=row.owner_phase,
        meta_optimization_modes=("mode_4_is_only_robust",) if row.activated else (),
        meta_optimization_schedules=("per_fold_causal",) if row.activated else (),
        meta_route_activated=row.activated)


def check_route_inventory(routes):
    """Future public dispatch must declare either an adapter or a pending gate."""
    names = tuple(routes)
    if len(names) != len(set(names)):
        raise MetaRecordError("META_ROUTE_INVENTORY_DUPLICATE")
    for route in names:
        capability(route)
    return True


def adapter_for(runtime):
    scorer = runtime.engine.scorer
    explicit = getattr(scorer, "meta_route_id", "original-endpoint-reset-v1")
    if explicit == "reactive-native-original-reset-v1":
        capability("reactive_reset", require_active=True)
        from .reactive import ReactiveDomainAdapter
        return ReactiveDomainAdapter(runtime)
    if explicit != "original-endpoint-reset-v1":
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: unregistered scorer contract")
    row = capability(runtime.engine.config.target_mode, require_active=True)
    if row.domain == "portfolio":
        from .portfolio import PortfolioDomainAdapter
        return PortfolioDomainAdapter(runtime)
    if row.domain == "package":
        from .package import PackageDomainAdapter
        return PackageDomainAdapter(runtime)
    if row.domain != "scalar":
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH")
    from .scalar import ScalarDomainAdapter
    return ScalarDomainAdapter(runtime)
