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
from .execution import (
    OptionDepthFidelity,
    OptionExecutionConfig,
    OptionLimitFidelity,
    OptionPackageExecutionResult,
    execute_option_package,
)
from .greeks import (
    OptionGreeks,
    inverse_black76_greeks_base,
    inverse_black76_greeks_quote,
    linear_black76_greeks,
    scale_greeks_to_reporting_currency,
)
from .iv import IVStatus, ImpliedVolResult, implied_vol_black76, implied_vol_inverse_black76_base
from .packages import (
    OptionPackageExecutionPolicy,
    OptionPackageIntent,
    OptionPackageLeg,
    compile_option_package_orders,
)
from .pricing import (
    black76_intrinsic,
    black76_parity_residual,
    black76_parity_value,
    black76_price,
    inverse_black76_intrinsic_base,
    inverse_black76_parity_residual_base,
    inverse_black76_parity_value_base,
    inverse_black76_price_base,
)
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
from .selectors import (
    OptionSelection,
    OptionSelectionFilters,
    available_option_rows,
    select_atm_option,
    select_target_delta_option,
    select_target_dte_option,
    select_target_moneyness_option,
)
from .surface import SurfaceDiagnostics, TotalVarianceSurface
from .tape import YEAR_NS, OptionTapeSignature, PreparedOptionTape, prepare_option_tape

__all__ = [
    "CANONICAL_OPTION_CHAIN_COLUMNS",
    "ExerciseStyle",
    "InstrumentRegistrySignature",
    "OptionDecisionFillPolicy",
    "OptionDepthFidelity",
    "OptionExecutionConfig",
    "OptionInstrumentRegistry",
    "OptionInstrumentSpec",
    "OptionKind",
    "OptionGreeks",
    "OptionLimitFidelity",
    "OptionPackageExecutionPolicy",
    "OptionPackageExecutionResult",
    "OptionPackageIntent",
    "OptionPackageLeg",
    "OptionVenueConvention",
    "OptionSelection",
    "OptionSelectionFilters",
    "OptionTapeSignature",
    "PremiumConvention",
    "PreparedOptionTape",
    "SettlementStyle",
    "SurfaceDiagnostics",
    "TotalVarianceSurface",
    "YEAR_NS",
    "binance_european_options_convention",
    "black76_intrinsic",
    "black76_parity_residual",
    "black76_parity_value",
    "black76_price",
    "compile_option_package_orders",
    "deribit_inverse_option_convention",
    "deribit_linear_usdc_option_convention",
    "implied_vol_black76",
    "implied_vol_inverse_black76_base",
    "inverse_black76_greeks_base",
    "inverse_black76_greeks_quote",
    "inverse_black76_intrinsic_base",
    "inverse_black76_parity_residual_base",
    "inverse_black76_parity_value_base",
    "inverse_black76_price_base",
    "IVStatus",
    "ImpliedVolResult",
    "linear_black76_greeks",
    "available_option_rows",
    "execute_option_package",
    "prepare_option_tape",
    "scale_greeks_to_reporting_currency",
    "select_atm_option",
    "select_target_delta_option",
    "select_target_dte_option",
    "select_target_moneyness_option",
    "validate_option_chain_frame",
]
