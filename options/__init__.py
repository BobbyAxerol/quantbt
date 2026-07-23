"""
QuantBT options domain package.

Phase 1 exposes schema, convention, and canonical chain-data validation only.
Pricing, execution, ledger, margin, endpoint wiring, and Nautilus validation are
added in later phases.
"""

from .conventions import (
    OptionVenueConvention,
    binance_european_options_convention,
    deribit_inverse_option_convention,
    deribit_linear_usdc_option_convention,
)
from .data import CANONICAL_OPTION_CHAIN_COLUMNS, validate_option_chain_frame
from .schema import (
    ExerciseStyle,
    InstrumentRegistrySignature,
    OptionDecisionFillPolicy,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    PremiumConvention,
    SettlementStyle,
)

__all__ = [
    "CANONICAL_OPTION_CHAIN_COLUMNS",
    "ExerciseStyle",
    "InstrumentRegistrySignature",
    "OptionDecisionFillPolicy",
    "OptionInstrumentRegistry",
    "OptionInstrumentSpec",
    "OptionKind",
    "OptionVenueConvention",
    "PremiumConvention",
    "SettlementStyle",
    "binance_european_options_convention",
    "deribit_inverse_option_convention",
    "deribit_linear_usdc_option_convention",
    "validate_option_chain_frame",
]
