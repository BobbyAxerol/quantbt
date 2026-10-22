"""Pre-M5-12 cold option validation extraction contracts, using synthetic inputs."""

import ast
from dataclasses import fields, is_dataclass, replace
from hashlib import sha256
import inspect
from types import FunctionType, SimpleNamespace
from typing import get_type_hints

import numpy as np
import pandas as pd
import pytest

from quantbt.backends import native_option, option_validation
from quantbt.core.schema import AccountConfig, ExecutionConfig, OrderSide
from quantbt.options.capabilities import OptionCapabilityError, OptionSettlementPolicy
from quantbt.options.packages import OptionPackageIntent, OptionPackageLeg


# Captured from the original facade definitions, including signatures/newlines.
_ORIGINAL_SOURCE_SHA256 = {
    "_validate_generic_option_configuration": "db0fd5497b0d6782be811a09d9e07c83aea4a970844e16c80712cb46d71efd7a",
    "_normalize_registry": "d46d01dbe09c091163242dc6ea7215d605b9ef259a0de056b62000639280cc47",
    "_validate_option_requests": "203c9489da5ae3c8daf5c9a3daeca873be6e3dcefa34abcdf97b1111c9becdac",
    "_validate_tape_coverage": "233b3653b43e8473b96153eaee11077b817d0c5b90ef5e417081780dbae5c81e",
}


def _facade_local(name):
    # Rebind the byte-pinned definition to its original global lookup context;
    # no production implementation or historical checkout is copied into tests.
    function = getattr(option_validation, name)
    assert sha256(inspect.getsource(function).encode()).hexdigest() == _ORIGINAL_SOURCE_SHA256[name]
    original = FunctionType(
        function.__code__, vars(native_option), name, function.__defaults__, function.__closure__,
    )
    original.__kwdefaults__ = function.__kwdefaults__
    original.__annotations__ = dict(function.__annotations__)
    return original


def _assert_same_output(actual, expected):
    assert type(actual) is type(expected)
    if isinstance(actual, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    elif isinstance(actual, pd.Series):
        pd.testing.assert_series_equal(actual, expected, check_exact=True)
    elif is_dataclass(actual):
        for item in fields(actual):
            _assert_same_output(getattr(actual, item.name), getattr(expected, item.name))
    elif isinstance(actual, dict):
        assert list(actual) == list(expected)
        for key in actual:
            _assert_same_output(actual[key], expected[key])
    elif isinstance(actual, (tuple, list)):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            _assert_same_output(left, right)
    else:
        np.testing.assert_equal(actual, expected)


@pytest.fixture
def option_request(option_phase3_registry):
    instrument = option_phase3_registry.instruments[0]
    package = OptionPackageIntent(
        timestamp_ns=1,
        package_id="synthetic",
        legs=(OptionPackageLeg(instrument_id=instrument.symbol, side=OrderSide.BUY, ratio=1.0),),
    )
    event = native_option.OptionSettlementEvent(
        symbol=instrument.symbol, timestamp_ns=instrument.expiry_ns, settlement_price=100_000.0,
    )
    return package, event


@pytest.mark.parametrize("name", _ORIGINAL_SOURCE_SHA256)
def test_extracted_definitions_are_byte_identical_private_aliases(name):
    helper = getattr(option_validation, name)
    assert getattr(native_option, name) is helper
    assert helper.__module__ == option_validation.__name__
    assert inspect.signature(helper) == inspect.signature(_facade_local(name))


def test_option_facade_below_trigger_with_one_focused_helper():
    facade_source = inspect.getsource(native_option)
    assert len(facade_source.splitlines()) < 1000
    facade_defs = {
        node.name for node in ast.parse(facade_source).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert not facade_defs.intersection(_ORIGINAL_SOURCE_SHA256)
    helper_defs = {
        node.name for node in ast.parse(inspect.getsource(option_validation)).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert helper_defs == set(_ORIGINAL_SOURCE_SHA256)


def test_extracted_request_annotations_resolve_in_original_and_helper_namespaces():
    actual = get_type_hints(option_validation._validate_option_requests)
    expected = get_type_hints(_facade_local("_validate_option_requests"))
    assert actual == expected


@pytest.mark.parametrize("account_changes,execution_changes,field", [
    ({}, {}, None),
    ({"margin_buffer": 12.0, "metadata": {"synthetic": True}}, {"metadata": {"synthetic": True}}, None),
    ({"base_currency": "BTC", "leverage": 2.0}, {"slippage_bps": 1.0}, "account.base_currency"),
    ({"leverage": 2.0}, {}, "account.leverage"),
    ({}, {"slippage_bps": 1.0, "allow_partial_fill": True}, "execution.slippage_bps"),
])
def test_generic_configuration_differential_and_first_error(account_changes, execution_changes, field):
    account = AccountConfig(initial_capital=100_000.0, **account_changes)
    execution = ExecutionConfig(**execution_changes)
    for validate in (_facade_local("_validate_generic_option_configuration"),
                     native_option._validate_generic_option_configuration):
        if field is None:
            assert validate(account, execution) is None
        else:
            account_error = field.startswith("account.")
            code = "OPTION_GENERIC_ACCOUNT_CONFIG_UNSUPPORTED" if account_error else "OPTION_GENERIC_EXECUTION_CONFIG_UNSUPPORTED"
            detail = "only its compatibility default is supported" if account_error else "configure option_execution instead"
            with pytest.raises(OptionCapabilityError) as caught:
                validate(account, execution)
            assert str(caught.value) == f"{code}: {field} is inactive for options; {detail}"
            assert caught.value.code == code
            assert caught.value.metadata == {}
    if field is None:
        native_option.NativeOptionConfig(account=account, execution=execution)
    else:
        with pytest.raises(OptionCapabilityError) as caught:
            native_option.NativeOptionConfig(account=account, execution=execution)
        assert field in str(caught.value)


@pytest.mark.parametrize("form", ["registry", "sequence", "mapping"])
def test_registry_normalization_differential_preserves_identity_and_order(option_phase3_registry, form):
    registry = option_phase3_registry
    inputs = {
        "registry": registry,
        "sequence": tuple(reversed(registry.instruments)),
        "mapping": {spec.symbol: spec for spec in reversed(registry.instruments)},
    }
    actual = native_option._normalize_registry(inputs[form])
    expected = _facade_local("_normalize_registry")(inputs[form])
    assert actual == expected
    assert actual.signature == registry.signature
    if form == "registry":
        assert actual is registry
    else:
        assert actual.instruments == tuple(reversed(registry.instruments))
        assert all(left is right for left, right in zip(actual.instruments, reversed(registry.instruments)))


@pytest.mark.parametrize("case,code,message", [
    ("unknown_settlement", "OPTION_SETTLEMENT_UNKNOWN_INSTRUMENT", "settlement event references unknown instrument 'MISSING'"),
    ("duplicate", "OPTION_SETTLEMENT_DUPLICATE_EVENT", "only one settlement event is allowed for {symbol!r}"),
    ("early", "OPTION_SETTLEMENT_BEFORE_EXPIRY", "settlement for {symbol!r} precedes its expiry timestamp"),
    ("expiry", "OPTION_SETTLEMENT_EXPIRY_MISMATCH", "settlement expiry provenance does not match instrument expiry for {symbol!r}"),
    ("last_trading", "OPTION_SETTLEMENT_LAST_TRADING_AFTER_EXPIRY", "last trading timestamp exceeds expiry for {symbol!r}"),
    ("unknown_package", "OPTION_PACKAGE_UNKNOWN_INSTRUMENT", "package 'synthetic' references unknown instrument 'MISSING'"),
    ("expired_package", "OPTION_EXPIRED_INSTRUMENT_ORDER", "package 'synthetic' is at/after expiry for {symbol!r}"),
])
def test_request_errors_differential_precede_tape_and_preserve_order(
    option_phase3_registry, option_request, monkeypatch, case, code, message,
):
    package, event = option_request
    missing_package = replace(package, legs=(replace(package.legs[0], instrument_id="MISSING"),))
    cases = {
        "unknown_settlement": ((missing_package,), (replace(event, symbol="MISSING"),)),
        "duplicate": ((missing_package,), (event, replace(event, expiry_timestamp_ns=event.timestamp_ns + 1))),
        "early": ((missing_package,), (replace(event, timestamp_ns=event.timestamp_ns - 1, expiry_timestamp_ns=1),)),
        "expiry": ((missing_package,), (replace(event, expiry_timestamp_ns=1, last_trading_timestamp_ns=event.timestamp_ns + 1),)),
        "last_trading": ((missing_package,), (replace(event, last_trading_timestamp_ns=event.timestamp_ns + 1),)),
        "unknown_package": ((missing_package,), (event,)),
        "expired_package": ((replace(package, timestamp_ns=event.timestamp_ns),), (event,)),
    }
    packages, events = cases[case]

    def fail_if_prepared(*args, **kwargs):
        pytest.fail("invalid requests must fail before market tape preparation")

    monkeypatch.setattr(native_option, "prepare_option_tape", fail_if_prepared)
    for validate in (_facade_local("_validate_option_requests"), native_option._validate_option_requests):
        with pytest.raises(OptionCapabilityError) as caught:
            validate(packages, events, option_phase3_registry.by_symbol,
                     settlement_policy=OptionSettlementPolicy.EXPLICIT_EVENTS_ONLY)
        assert str(caught.value) == f"{code}: {message.format(symbol=event.symbol)}"
        assert caught.value.code == code
        assert caught.value.metadata == {}
    with pytest.raises(OptionCapabilityError) as caught:
        native_option.NativeOptionBackend().run(
            chain=pd.DataFrame(), instruments=option_phase3_registry,
            packages=packages, settlement_events=events,
        )
    assert str(caught.value) == f"{code}: {message.format(symbol=event.symbol)}"


@pytest.mark.parametrize("policy", [*OptionSettlementPolicy, "unsupported"])
def test_settlement_policy_differential(option_phase3_registry, option_request, policy):
    package, event = option_request
    for validate in (_facade_local("_validate_option_requests"), native_option._validate_option_requests):
        if isinstance(policy, OptionSettlementPolicy):
            assert validate((package,), (event,), option_phase3_registry.by_symbol, settlement_policy=policy) is None
        else:
            with pytest.raises(OptionCapabilityError) as caught:
                validate((package,), (event,), option_phase3_registry.by_symbol, settlement_policy=policy)
            assert str(caught.value) == "OPTION_SETTLEMENT_POLICY_UNSUPPORTED: unsupported settlement policy"


@pytest.mark.parametrize("timestamps", [(), (10,), (20,), (10, 20), (9,), (21,), (10, 21, 9)])
def test_tape_coverage_differential_keeps_inclusive_bounds_and_first_failure(option_request, timestamps):
    package, _ = option_request
    packages = tuple(replace(package, timestamp_ns=value, package_id=str(value)) for value in timestamps)
    tape = SimpleNamespace(timestamp_ns=(10, 20))
    outside = next((value for value in timestamps if value < 10 or value > 20), None)
    for validate in (_facade_local("_validate_tape_coverage"), native_option._validate_tape_coverage):
        if outside is None:
            assert validate(packages, tape) is None
        else:
            with pytest.raises(OptionCapabilityError) as caught:
                validate(packages, tape)
            assert str(caught.value) == (
                f"OPTION_PACKAGE_TIMESTAMP_OUTSIDE_TAPE: package {str(outside)!r} timestamp is outside the prepared market tape"
            )


@pytest.mark.parametrize("max_debit", [None, 0.0])
def test_synthetic_public_result_matches_facade_local_helpers(
    option_phase3_chain, option_phase3_registry, option_request, monkeypatch, max_debit,
):
    package, event = option_request
    package = replace(package, timestamp_ns=int(option_phase3_chain.timestamp_ns.min()), max_debit=max_debit)
    backend = native_option.NativeOptionBackend(native_option.NativeOptionConfig(conversion_rates={"BTC": 100_000.0}))
    inputs = dict(
        chain=option_phase3_chain, instruments=option_phase3_registry,
        packages=(package,), settlement_events=(event,),
    )
    actual = backend.run(**inputs)
    originals = {name: _facade_local(name) for name in _ORIGINAL_SOURCE_SHA256}
    with monkeypatch.context() as patch:
        for name, function in originals.items():
            patch.setattr(native_option, name, function)
        expected = backend.run(**inputs)
    _assert_same_output(actual, expected)
    assert actual.packages_report.iloc[0]["financial_admission"] == ("accepted" if max_debit is None else "rejected")
    assert actual.metadata["accounting_reconciliation"]["reconciled"] is True
