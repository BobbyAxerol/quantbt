"""Research evidence only: no optimizer, simulation or deployment authority."""
from .contracts import EconomicProtocol, DailyAccount
from .inference import paired_economics
from .measurement import account_summary, cost_margin, fixed_decay, profit_factor
from .rights import validation_rights, cached_validation_rights, prefix_rights, StressRequest

__all__ = ["EconomicProtocol", "DailyAccount", "paired_economics", "account_summary",
           "cost_margin", "fixed_decay", "profit_factor", "validation_rights", "cached_validation_rights", "prefix_rights", "StressRequest"]
