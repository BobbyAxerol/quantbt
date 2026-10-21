"""Capability validation for the close-target gross-cross portfolio contract."""

from .schema import FillPricePolicy, MarginMode, OmsMode, SameBarPolicy


def validate_gross_cross_account(account, *, allow_margin_buffer=False) -> None:
    if account.margin_mode != MarginMode.CROSS:
        raise NotImplementedError("linear native account supports margin_mode='cross' only")
    if account.oms_mode != OmsMode.NETTING:
        raise NotImplementedError("linear native account supports oms_mode='netting' only")
    if account.margin_buffer != 0.0 and not allow_margin_buffer:
        raise NotImplementedError("this linear account does not approximate margin_buffer; pass 0.0")


def validate_portfolio_configuration(account, execution) -> None:
    validate_gross_cross_account(account)
    if execution.fill_price_policy != FillPricePolicy.CLOSE:
        raise NotImplementedError("portfolio targets execute at close; other fill clocks require an order/intent endpoint")
    if execution.same_bar_policy != SameBarPolicy.CONSERVATIVE:
        raise NotImplementedError("portfolio targets do not implement alternate same_bar_policy")
    if execution.allow_partial_fill:
        raise NotImplementedError("portfolio targets do not implement partial fills")
    if not execution.reject_on_insufficient_margin:
        raise NotImplementedError("portfolio targets require insufficient-margin rejection")
    if execution.slippage_rate >= 1.0:
        raise ValueError("portfolio slippage must produce positive execution prices")
