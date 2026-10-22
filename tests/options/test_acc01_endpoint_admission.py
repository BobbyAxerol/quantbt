"""ACC-01 final sibling admission controls: no silently ignored facade flags."""

from dataclasses import replace

import pandas as pd
import pytest

from quantbt import AccountConfig, ExecutionConfig, NativeEventConfig, NativeOptionConfig, QuantBTEndpoint
from quantbt.core.schema import FillPricePolicy, SameBarPolicy
from quantbt.options.capabilities import OptionCapabilityError


@pytest.mark.parametrize("override", [dict(fill_price_policy=FillPricePolicy.OPEN),
    dict(same_bar_policy=SameBarPolicy.ENTRY_FIRST), dict(allow_partial_fill=True),
    dict(reject_on_insufficient_margin=False)])
def test_acc01_generic_event_execution_nondefaults_fail_before_execution(override):
    with pytest.raises(NotImplementedError, match="generic execution"):
        NativeEventConfig(account=AccountConfig(initial_capital=1000.), execution=ExecutionConfig(**override))


@pytest.mark.parametrize("contract", ["event_lifecycle_v2_next_bar_close", "event_lifecycle_v3_next_open"])
def test_acc01_event_named_clocks_remain_supported_with_default_generic_flags(contract):
    config = NativeEventConfig(account=AccountConfig(initial_capital=1000.), execution_contract=contract)
    assert config.execution_contract.contract_id == contract


@pytest.mark.parametrize("kwargs", [dict(contract_size=2.), dict(contract_size={"X": 1.}),
    dict(qty_step=.1), dict(lot_size=.1), dict(slot_size=.1), dict(min_qty=0.),
    dict(min_notional=10.), dict(funding_rate=.01), dict(funding_rate=float("nan")),
    dict(funding_rate=pd.Series([0.])), dict(execution_contract="event_lifecycle_v3_next_open")])
@pytest.mark.parametrize("complete_config", [False, True])
def test_acc01_option_generic_endpoint_controls_reject(kwargs, complete_config):
    with pytest.raises(OptionCapabilityError, match="OPTION_GENERIC_ENDPOINT_CONFIG_UNSUPPORTED"):
        QuantBTEndpoint.options(**kwargs, **(dict(option_config=NativeOptionConfig()) if complete_config else {}))


@pytest.mark.parametrize("override", [dict(initial_capital=2000.), dict(leverage=2.),
    dict(account=AccountConfig(initial_capital=1000.)), dict(execution=ExecutionConfig()), dict(fee_rate=.01)])
def test_acc01_complete_option_config_cannot_silently_ignore_financial_overrides(override):
    with pytest.raises(OptionCapabilityError, match="OPTION_CONFIG_OVERRIDE_CONFLICT"):
        QuantBTEndpoint.options(option_config=NativeOptionConfig(), **override)


def test_acc01_direct_option_endpoint_cannot_bypass_generic_control_validation(option_phase3_chain, option_phase3_registry):
    valid = QuantBTEndpoint.options()
    invalid = QuantBTEndpoint(replace(valid.config, contract_size=2.))
    with pytest.raises(OptionCapabilityError, match="contract_size"):
        invalid.backtest(chain=option_phase3_chain, instruments=option_phase3_registry)


def test_acc01_option_defaults_and_explicit_funding_off_keep_instrument_authority():
    for kwargs in ({}, dict(use_funding=False, funding_rate=0., contract_size=1.)):
        endpoint = QuantBTEndpoint.options(**kwargs)
        assert endpoint.config.option_config.account.initial_capital == 100000.
