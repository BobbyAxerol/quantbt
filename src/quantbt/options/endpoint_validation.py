"""Reject generic facade controls that do not reach option execution."""

from numbers import Real

from .capabilities import OptionCapabilityError


def validate_option_endpoint(config):
    inactive = []
    if not isinstance(config.contract_size, Real) or config.contract_size != 1.0:
        inactive.append("contract_size (use OptionInstrumentSpec)")
    for name in ("qty_step", "lot_size", "slot_size", "min_qty", "min_notional", "execution_contract"):
        if getattr(config, name) is not None:
            inactive.append(name)
    if not isinstance(config.funding_rate, Real) or config.funding_rate != 0.0:
        inactive.append("funding_rate")
    if inactive:
        raise OptionCapabilityError("OPTION_GENERIC_ENDPOINT_CONFIG_UNSUPPORTED",
            "unsupported generic option endpoint controls: " + ", ".join(inactive))


def validate_option_config_overrides(kwargs):
    conflicting = set(kwargs).intersection({"account", "execution", "initial_capital", "leverage",
        "maintenance_ratio", "margin_buffer", "margin_mode", "oms_mode", "fee", "fee_rate", "slippage_bps"})
    if conflicting:
        raise OptionCapabilityError("OPTION_CONFIG_OVERRIDE_CONFLICT",
            "option_config owns financial settings; remove facade overrides: " + ", ".join(sorted(conflicting)))
