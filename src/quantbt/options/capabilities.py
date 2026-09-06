"""Explicit V1.1 capability contract for native option simulations.

The option route is intentionally Python-primary in V1.1. This module makes
the boundary machine-readable so unsupported lifecycle or accounting semantics
fail before a tape is prepared or a fill can affect a ledger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, Iterable, Mapping, Optional

from .execution import OptionExecutionConfig, OptionLimitFidelity
from .margin import OptionMarginConfig, OptionMarginModel
from .schema import ExerciseStyle, OptionInstrumentSpec, PremiumConvention, SettlementStyle


class OptionCapabilityStatus(str, Enum):
    """Truthful validation state for an option-domain capability."""

    CERTIFIED = "certified"
    RESEARCH_APPROXIMATION = "research_approximation"
    UNSUPPORTED = "unsupported"


class OptionSettlementPolicy(str, Enum):
    """How expiry settlement may enter a native option run."""

    EXPLICIT_EVENTS_ONLY = "explicit_events_only"
    LEGACY_LAST_TAPE_MARK_RESEARCH = "legacy_last_tape_mark_research"


class OptionCapabilityError(ValueError):
    """Actionable fail-fast error for an unsupported option request."""

    def __init__(self, code: str, message: str, *, metadata: Optional[Mapping] = None):
        self.code = str(code)
        self.metadata = dict(metadata or {})
        super().__init__(f"{self.code}: {message}")


@dataclass(frozen=True)
class OptionCapabilityAssessment:
    symbol: str
    exercise_style: str
    premium_convention: str
    settlement_style: str
    margin_model: str
    execution_model: str
    status: OptionCapabilityStatus
    code: str
    certified: bool
    notes: str

    def as_dict(self) -> Dict:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


def assess_option_capability(
    instrument: OptionInstrumentSpec,
    *,
    margin: OptionMarginConfig,
    execution: OptionExecutionConfig,
    allow_future_then_cash_research: bool = False,
    require_venue_exact_margin: bool = False,
    external_margin_validator: object | None = None,
) -> OptionCapabilityAssessment:
    """Assess one instrument before tape construction or package execution."""

    common = {
        "symbol": instrument.symbol,
        "exercise_style": instrument.exercise_style.value,
        "premium_convention": instrument.premium_convention.value,
        "settlement_style": instrument.settlement_style.value,
        "margin_model": margin.model.value,
        "execution_model": execution.limit_fidelity.value,
    }
    if instrument.exercise_style is not ExerciseStyle.EUROPEAN:
        return OptionCapabilityAssessment(
            **common,
            status=OptionCapabilityStatus.UNSUPPORTED,
            code="OPTION_EXERCISE_MODEL_REQUIRED",
            certified=False,
            notes="American exercise/assignment requires an authoritative lifecycle model.",
        )
    if instrument.premium_convention is PremiumConvention.QUANTO:
        return OptionCapabilityAssessment(
            **common,
            status=OptionCapabilityStatus.UNSUPPORTED,
            code="OPTION_QUANTO_UNSUPPORTED",
            certified=False,
            notes="Quanto payoff, FX conversion, and collateral accounting are outside V1.1.",
        )
    if instrument.settlement_style is SettlementStyle.PHYSICAL:
        return OptionCapabilityAssessment(
            **common,
            status=OptionCapabilityStatus.UNSUPPORTED,
            code="OPTION_PHYSICAL_SETTLEMENT_UNSUPPORTED",
            certified=False,
            notes="Physical delivery requires an assignment and delivered-instrument lifecycle.",
        )
    if instrument.settlement_style is SettlementStyle.FUTURE_THEN_CASH:
        if not allow_future_then_cash_research:
            return OptionCapabilityAssessment(
                **common,
                status=OptionCapabilityStatus.UNSUPPORTED,
                code="OPTION_FUTURE_SETTLEMENT_MODEL_REQUIRED",
                certified=False,
                notes="Set allow_future_then_cash_research=True only for an explicitly labelled economic-cash bridge.",
            )
        return OptionCapabilityAssessment(
            **common,
            status=OptionCapabilityStatus.RESEARCH_APPROXIMATION,
            code="OPTION_FUTURE_THEN_CASH_ECONOMIC_BRIDGE",
            certified=False,
            notes="Future-then-cash is represented as an economic cash bridge, not a delivered-future lifecycle.",
        )
    if require_venue_exact_margin and (
        margin.model is not OptionMarginModel.EXTERNAL_VALIDATOR or external_margin_validator is None
    ):
        return OptionCapabilityAssessment(
            **common,
            status=OptionCapabilityStatus.UNSUPPORTED,
            code="OPTION_VENUE_EXACT_MARGIN_VALIDATOR_REQUIRED",
            certified=False,
            notes="Venue-exact margin requires an external validator with venue fixtures.",
        )
    if execution.limit_fidelity is OptionLimitFidelity.MAKER_TOUCH:
        return OptionCapabilityAssessment(
            **common,
            status=OptionCapabilityStatus.RESEARCH_APPROXIMATION,
            code="OPTION_MAKER_TOUCH_APPROXIMATION",
            certified=False,
            notes="Maker-touch uses a top-of-book touch approximation; queue priority is not modeled.",
        )
    return OptionCapabilityAssessment(
        **common,
        status=OptionCapabilityStatus.CERTIFIED,
        code="OPTION_EUROPEAN_CASH_V1_1",
        certified=True,
        notes="European cash-settled linear/inverse lifecycle with explicit settlement provenance.",
    )


def validate_option_capabilities(
    instruments: Iterable[OptionInstrumentSpec],
    *,
    margin: OptionMarginConfig,
    execution: OptionExecutionConfig,
    allow_future_then_cash_research: bool = False,
    require_venue_exact_margin: bool = False,
    external_margin_validator: object | None = None,
) -> tuple[OptionCapabilityAssessment, ...]:
    """Return all assessments or fail before a simulation has observable work."""

    assessments = tuple(
        assess_option_capability(
            instrument,
            margin=margin,
            execution=execution,
            allow_future_then_cash_research=allow_future_then_cash_research,
            require_venue_exact_margin=require_venue_exact_margin,
            external_margin_validator=external_margin_validator,
        )
        for instrument in instruments
    )
    unsupported = next((item for item in assessments if item.status is OptionCapabilityStatus.UNSUPPORTED), None)
    if unsupported is not None:
        raise OptionCapabilityError(
            unsupported.code,
            unsupported.notes,
            metadata=unsupported.as_dict(),
        )
    return assessments


def option_capability_registry_v1() -> Dict[str, Dict[str, str]]:
    """Public static support matrix used by docs and endpoint support output."""

    return {
        "european_linear_cash": {
            "status": OptionCapabilityStatus.CERTIFIED.value,
            "backend": "native_option",
            "route": "QuantBTEndpoint.options",
            "notes": "Explicit settlement event/source required for certified expiry result.",
        },
        "european_inverse_cash": {
            "status": OptionCapabilityStatus.CERTIFIED.value,
            "backend": "native_option",
            "route": "QuantBTEndpoint.options",
            "notes": "Explicit settlement event/source required; inverse fee schedule is supported.",
        },
        "future_then_cash_economic_bridge": {
            "status": OptionCapabilityStatus.RESEARCH_APPROXIMATION.value,
            "backend": "native_option",
            "route": "allow_future_then_cash_research=True",
            "notes": "Opt-in only; not a delivered future lifecycle.",
        },
        "american_exercise_assignment": {
            "status": OptionCapabilityStatus.UNSUPPORTED.value,
            "backend": "none",
            "route": "V1.2 authoritative lifecycle model required",
            "notes": "Requires observed exercise/assignment or an authoritative model.",
        },
        "quanto": {
            "status": OptionCapabilityStatus.UNSUPPORTED.value,
            "backend": "none",
            "route": "V1.2 multi-currency authority required",
            "notes": "Requires FX/quanto payoff and collateral authority.",
        },
        "physical_settlement": {
            "status": OptionCapabilityStatus.UNSUPPORTED.value,
            "backend": "none",
            "route": "V1.2 delivered-instrument lifecycle required",
            "notes": "Requires delivered-instrument lifecycle authority.",
        },
        "venue_exact_portfolio_margin": {
            "status": "external_validator_required",
            "backend": "native_option",
            "route": "OptionMarginModel.EXTERNAL_VALIDATOR",
            "notes": "Only an external validator returning venue_exact=True can support this claim.",
        },
        "maker_touch": {
            "status": OptionCapabilityStatus.RESEARCH_APPROXIMATION.value,
            "backend": "native_option",
            "route": "OptionLimitFidelity.MAKER_TOUCH",
            "notes": "Top-of-book touch approximation; no queue priority or L2 matching.",
        },
    }


__all__ = [
    "OptionCapabilityAssessment",
    "OptionCapabilityError",
    "OptionCapabilityStatus",
    "OptionSettlementPolicy",
    "assess_option_capability",
    "option_capability_registry_v1",
    "validate_option_capabilities",
]
