"""ACC-01 F09/F16/F17: independent clock/funding controls, not Rust qualification."""

from dataclasses import replace
import pickle

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionContract,
    IntrabarIntentTape,
    IntrabarSessionTape,
    QuantBTEndpoint,
    SessionExecutionPolicy,
    run_intrabar_kernel,
    run_intrabar_reference,
    run_intrabar_session_kernel,
)
from quantbt.core import market_tape
from quantbt.core.market_tape import prepare_market_tape
from quantbt.core.results import BacktestResultV2, NativeAccountingArrays, NativeEventScoreResult


START_NS = 1_704_067_200_000_000_000  # 2024-01-01T00:00:00Z
HOUR_NS = 3_600_000_000_000
DAY_NS = 24 * HOUR_NS
UNITS = ("ns", "us", "ms", "s")


def _clock(unit="ns", *, timezone="UTC", freq="h"):
    index = pd.date_range("2024-01-01", periods=3, freq=freq, tz="UTC")
    index = index.tz_convert(timezone) if timezone else index.tz_localize(None)
    return index.as_unit(unit)


def _frame(index):
    return pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0},
        index=index,
    )


def _market_inputs(index, representation="frame"):
    frame = _frame(index)
    if representation == "frame":
        return {"data": frame}
    if representation == "frames":
        return {"data": {"BTC": frame}}
    if representation == "timestamp_column":
        return {"data": frame.reset_index(names="timestamp")}
    fields = {name + "s": frame[name] for name in ("open", "high", "low", "close", "volume")}
    if representation == "series_maps":
        fields = {name: {"BTC": series} for name, series in fields.items()}
    return fields


def _result(index):
    equity = pd.Series([1000.0, 1100.0, 1045.0][:len(index)], index=index, name="equity")
    return BacktestResultV2(
        equity=equity,
        returns=pd.Series([0.0, 0.1, -0.05][:len(index)], index=index),
        positions=pd.DataFrame({"Position_BTC": 1.0}, index=index),
        closes=pd.DataFrame({"BTC": 100.0}, index=index),
        fees=pd.Series(0.0, index=index),
        funding=pd.Series(0.0, index=index),
        symbols=["BTC"],
        initial_capital=1000.0,
    )


@pytest.mark.parametrize("unit", UNITS)
@pytest.mark.parametrize("timezone", ("UTC", "Asia/Ho_Chi_Minh", None))
def test_f09_accounting_roundtrip_and_report_use_physical_utc_instants(unit, timezone):
    index = _clock(unit, timezone=timezone, freq="D")
    result = _result(index)
    before = result.equity.copy(deep=True)
    accounting = NativeAccountingArrays.from_result(
        result, naive_timezone="UTC" if timezone is None else None,
    )

    np.testing.assert_array_equal(accounting.timestamps, [START_NS, START_NS + DAY_NS, START_NS + 2 * DAY_NS])
    assert accounting.timestamps.dtype == np.dtype("int64")
    assert accounting.datetime_index.unit == "ns"
    assert str(accounting.datetime_index.tz) == "UTC"
    assert accounting.datetime_index[0] == pd.Timestamp("2024-01-01T00:00:00Z")
    assert (accounting.datetime_index[-1] - accounting.datetime_index[0]).total_seconds() == 172800
    score = NativeEventScoreResult(
        accounting=accounting, final_positions=np.array([1.0]), fill_count=0,
        rejection_count=0, cancellation_count=0, liquidated=False, liquidation_bar=-1, metrics={},
    )
    direct_report = result.full_report(scope="full")
    array_report = score.full_report(scope="full")
    assert array_report["total_return_pct"] == pytest.approx(4.5)
    assert array_report["cagr_pct"] == pytest.approx((1.045 ** (365.25 / 2) - 1) * 100)
    for metric in ("total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe"):
        assert array_report[metric] == pytest.approx(direct_report[metric], nan_ok=True)
    pd.testing.assert_series_equal(result.equity, before)
    assert result.equity.index.unit == unit


def test_f09_naive_clock_requires_explicit_utc_declaration():
    result = _result(_clock("us", timezone=None))
    with pytest.raises(ValueError, match="naive_timezone='UTC'"):
        NativeAccountingArrays.from_result(result)
    with pytest.raises(ValueError, match="only explicit naive_timezone='UTC'"):
        NativeAccountingArrays.from_result(result, naive_timezone="Asia/Ho_Chi_Minh")


@pytest.mark.parametrize("boundary", ("result", "market", "events"))
@pytest.mark.parametrize("defect", ("nat_first", "nat_middle", "nat_last", "duplicate", "unordered", "empty"))
def test_f09_f16_clock_validation_is_strict_at_each_boundary(boundary, defect):
    index = _clock("us")
    if defect.startswith("nat"):
        values = list(index)
        values[{"nat_first": 0, "nat_middle": 1, "nat_last": 2}[defect]] = pd.NaT
        index = pd.DatetimeIndex(values)
        message = "NaT"
    elif defect == "duplicate":
        index, message = index[[0, 1, 1]], "duplicate"
    elif defect == "unordered":
        index, message = index[[1, 0, 2]], "strictly increasing"
    else:
        index, message = index[:0], "empty|nonempty"
    with pytest.raises(ValueError, match=message):
        if boundary == "result":
            NativeAccountingArrays.from_result(_result(index))
        elif boundary == "market":
            prepare_market_tape(data=_frame(index), symbols=["BTC"], use_funding=False)
        else:
            prepare_market_tape(
                data=_frame(_clock()), symbols=["BTC"],
                funding_event_timestamps=index, funding_event_rates=np.zeros(len(index)),
            )


@pytest.mark.parametrize("boundary", ("result", "market", "events"))
@pytest.mark.parametrize("year", (1600, 2500))
def test_f09_f16_ns_overflow_is_rejected_not_wrapped(boundary, year):
    index = pd.DatetimeIndex(np.array([f"{year}-01-01"], dtype="datetime64[us]")).tz_localize("UTC")
    with pytest.raises((ValueError, OverflowError), match="Out of bounds|overflow"):
        if boundary == "result":
            NativeAccountingArrays.from_result(_result(index))
        elif boundary == "market":
            prepare_market_tape(data=_frame(index), symbols=["BTC"], use_funding=False)
        else:
            prepare_market_tape(
                data=_frame(_clock()), symbols=["BTC"],
                funding_event_timestamps=index, funding_event_rates=[0.01],
            )


@pytest.mark.parametrize("representation", ("frame", "frames", "timestamp_column", "series", "series_maps"))
@pytest.mark.parametrize("unit", UNITS)
@pytest.mark.parametrize("timezone", ("UTC", "Asia/Ho_Chi_Minh", None))
def test_f16_market_identity_and_cross_unit_event_alignment_are_canonical(representation, unit, timezone):
    funding = {
        "funding_event_timestamps": _clock("ns", timezone="America/New_York")[[1]],
        "funding_event_rates": pd.Series([0.01], index=_clock("ms")[[1]]),
    }
    canonical = prepare_market_tape(data=_frame(_clock()), symbols=["BTC"], **funding)
    tape = prepare_market_tape(
        **_market_inputs(_clock(unit, timezone=timezone), representation),
        symbols=["BTC"], source_timezone="UTC" if timezone is None else None, **funding,
    )

    np.testing.assert_array_equal(tape.timestamps_ns, [START_NS, START_NS + HOUR_NS, START_NS + 2 * HOUR_NS])
    np.testing.assert_array_equal(tape.funding_event_mask, [False, True, False])
    np.testing.assert_array_equal(tape.funding_rates[:, 0], [0.0, 0.01, 0.0])
    assert tape.signature == canonical.signature
    assert tape.validation_certificate == canonical.validation_certificate
    assert tape.validation_certificate.first_timestamp_ns == START_NS
    assert tape.validation_certificate.last_timestamp_ns == START_NS + 2 * HOUR_NS
    assert tape.validation_certificate.timezone == "UTC"
    assert tape.validation_certificate.finite_ok is True
    assert not tape.timestamps_ns.flags.writeable
    assert not tape.funding_rates.flags.writeable


@pytest.mark.parametrize("representation", ("frame", "frames", "series", "series_maps"))
def test_f16_declared_local_naive_clocks_include_funding_series(representation):
    local = _clock("us", timezone="Asia/Ho_Chi_Minh").tz_localize(None)
    funding = pd.Series([0.0, -0.01, 0.0], index=local)
    with pytest.raises(ValueError, match="timezone-naive"):
        prepare_market_tape(**_market_inputs(local, representation), symbols=["BTC"], funding_rate=funding)
    tape = prepare_market_tape(
        **_market_inputs(local, representation), symbols=["BTC"],
        funding_rate=funding, source_timezone="Asia/Ho_Chi_Minh",
    )
    np.testing.assert_array_equal(tape.timestamps_ns, [START_NS, START_NS + HOUR_NS, START_NS + 2 * HOUR_NS])
    np.testing.assert_array_equal(tape.funding_rates[:, 0], [0.0, -0.01, 0.0])


def test_f16_declared_local_naive_event_rate_series_aligns_by_instant():
    local_events = _clock("us", timezone="Asia/Ho_Chi_Minh")[[1]].tz_localize(None)
    tape = prepare_market_tape(
        data=_frame(_clock("ms")), symbols=["BTC"], source_timezone="Asia/Ho_Chi_Minh",
        funding_event_timestamps=local_events, funding_event_rates=pd.Series([-0.01], index=local_events),
    )
    np.testing.assert_array_equal(tape.funding_rates[:, 0], [0.0, -0.01, 0.0])


def test_f16_preserves_submicrosecond_precision_and_long_spans_without_diff_overflow():
    fine = _clock()[:1].append(pd.DatetimeIndex([pd.Timestamp("2024-01-01T00:00:00.000000001Z")]))
    tape = prepare_market_tape(data=_frame(fine), symbols=["BTC"], use_funding=False)
    np.testing.assert_array_equal(tape.timestamps_ns, [START_NS, START_NS + 1])
    accounting = NativeAccountingArrays.from_result(_result(fine))
    np.testing.assert_array_equal(accounting.timestamps, [START_NS, START_NS + 1])
    wide = pd.DatetimeIndex(["1680-01-01", "1970-01-01", "2250-01-01"], tz="UTC")
    wide_tape = prepare_market_tape(data=_frame(wide), symbols=["BTC"], use_funding=False)
    assert int(wide_tape.timestamps_ns[-1]) - int(wide_tape.timestamps_ns[0]) > np.iinfo(np.int64).max
    wide_accounting = NativeAccountingArrays.from_result(_result(wide))
    assert wide_accounting.datetime_index.equals(wide.as_unit("ns"))


def test_f16_obsolete_prepared_certificate_is_not_reused():
    tape = prepare_market_tape(data=_frame(_clock()), symbols=["BTC"], use_funding=False)
    assert prepare_market_tape(data=tape) is tape
    obsolete = replace(
        tape, timestamps_ns=_clock("us").asi8,
        validation_certificate=replace(tape.validation_certificate, validator_version="market_tape_v1"),
    )
    with pytest.raises(ValueError, match="obsolete.*reprepare"):
        prepare_market_tape(data=pickle.loads(pickle.dumps(obsolete)))
    with pytest.raises(ValueError, match="bar_timestamp_semantics"):
        prepare_market_tape(data=tape, bar_timestamp_semantics="open")


@pytest.mark.parametrize("source", (
    "events", "event_series", "event_mapping", "event_mapping_series",
    "series", "mapping_series", "mapping_scalar", "scalar",
))
@pytest.mark.parametrize("invalid", (np.nan, np.inf, -np.inf))
def test_f17_rejects_nonfinite_funding_before_certificate(monkeypatch, source, invalid):
    index = _clock("us")
    event_index = _clock("ns")[[1]]
    if source.startswith("event"):
        value = pd.Series([invalid], index=event_index) if "series" in source else [invalid]
        rates = {"BTC": value} if "mapping" in source else value
        kwargs = {"funding_event_timestamps": event_index, "funding_event_rates": rates}
    else:
        value = invalid if "scalar" in source else pd.Series([0.0, invalid, 0.0], index=index)
        rates = {"BTC": value} if "mapping" in source else value
        kwargs = {"funding_rate": rates, "missing_funding_policy": "zero"}

    def unexpected_certificate(*args, **kwargs):
        pytest.fail("invalid funding reached certificate construction")

    monkeypatch.setattr(market_tape, "MarketValidationCertificate", unexpected_certificate)
    with pytest.raises(ValueError, match="finite"):
        prepare_market_tape(data=_frame(index), symbols=["BTC"], **kwargs)


@pytest.mark.parametrize("invalid", (np.nan, np.inf, -np.inf))
def test_f17_aligned_first_row_and_every_symbol_are_validated(invalid):
    index = _clock("ms")
    frames = {"BTC": _frame(index), "ETH": _frame(index)}
    for kwargs in (
        {"funding_rate": {"BTC": pd.Series(0.0, index=index), "ETH": pd.Series([invalid, 0.0, 0.0], index=index)}},
        {"funding_event_timestamps": index[[1]], "funding_event_rates": {"BTC": [0.01], "ETH": [invalid]}},
    ):
        with pytest.raises(ValueError, match="finite"):
            prepare_market_tape(data=frames, symbols=["BTC", "ETH"], **kwargs)


@pytest.mark.parametrize("rates", (0.01, [[0.01]], [0.01, 0.02]))
def test_f17_event_rates_require_one_scalar_per_event(rates):
    with pytest.raises(ValueError, match="scalar|one-dimensional|length"):
        prepare_market_tape(
            data=_frame(_clock()), symbols=["BTC"],
            funding_event_timestamps=_clock("us")[[1]], funding_event_rates=rates,
        )


@pytest.mark.parametrize("source", ("events", "series"))
def test_f16_f17_rate_series_cannot_relabel_misaligned_instants(source):
    index = _clock("us")
    shifted = _clock("ns") + pd.Timedelta(minutes=1)
    kwargs = (
        {"funding_event_timestamps": index[[1]], "funding_event_rates": pd.Series([0.01], index=shifted[[1]])}
        if source == "events" else {"funding_rate": pd.Series([0.0, 0.01, 0.0], index=shifted)}
    )
    with pytest.raises(ValueError, match="align"):
        prepare_market_tape(data=_frame(index), symbols=["BTC"], **kwargs)


@pytest.mark.parametrize("when,message", (
    ("2024-01-01T00:00:00Z", "first bar"),
    ("2024-01-01T00:30:00Z", "align exactly"),
    ("2024-01-01T03:00:00Z", "align exactly"),
))
def test_f16_f17_explicit_events_keep_exact_alignment_and_first_bar_rules(when, message):
    with pytest.raises(ValueError, match=message):
        prepare_market_tape(
            data=_frame(_clock("us")), symbols=["BTC"],
            funding_event_timestamps=pd.DatetimeIndex([when]).as_unit("ns"), funding_event_rates=[-0.01],
        )


def test_f17_aligned_series_keeps_first_bar_mask_and_signed_rates():
    index = _clock("us")
    tape = prepare_market_tape(
        data=_frame(index), symbols=["BTC"], funding_rate=pd.Series([-0.02, -0.01, 0.0], index=index),
    )
    np.testing.assert_array_equal(tape.funding_rates[:, 0], [-0.02, -0.01, 0.0])
    np.testing.assert_array_equal(tape.funding_event_mask, [False, True, False])
    assert tape.validation_certificate.finite_ok is True


def _execute(tape, runner):
    kwargs = {
        "tape": tape,
        "intent": IntrabarIntentTape.from_arrays(entry_side=[1, 0, 0], entry_size=[1.0, 0.0, 0.0]),
        "account": AccountConfig(initial_capital=1000.0),
        "contract": ExecutionContract.intrabar_bracket(close_on_last_bar=False),
    }
    if runner == "reference":
        return run_intrabar_reference(**kwargs)
    if runner == "kernel":
        return run_intrabar_kernel(**kwargs, report_level="audit")
    session = IntrabarSessionTape.from_index(
        pd.to_datetime(tape.timestamps_ns, unit="ns", utc=True),
        timezone="Asia/Ho_Chi_Minh", entry_windows=(("08:00", "09:00"),),
    )
    np.testing.assert_array_equal(session.entry_allowed_at_open, [False, True, True])
    return run_intrabar_session_kernel(
        **kwargs, session_tape=session, session_policy=SessionExecutionPolicy(), report_level="audit",
    )


@pytest.mark.parametrize("runner", ("reference", "kernel", "session_kernel"))
@pytest.mark.parametrize("unit", UNITS)
@pytest.mark.parametrize("rate", (0.01, -0.01))
@pytest.mark.parametrize("source", ("events", "event_mapping", "series", "mapping_series"))
def test_f16_f17_execution_clock_and_signed_funding_have_independent_oracles(runner, unit, rate, source):
    if source.startswith("event"):
        kwargs = {
            "funding_event_timestamps": _clock("ns")[[1]],
            "funding_event_rates": {"BTC": [rate]} if source == "event_mapping" else [rate],
        }
    else:
        series = pd.Series([0.0, rate, 0.0], index=_clock("ms"))
        kwargs = {"funding_rate": {"BTC": series} if source == "mapping_series" else series}
    tape = prepare_market_tape(
        data=_frame(_clock(unit)), symbols=["BTC"], **kwargs,
    )
    result = _execute(tape, runner)
    cost = 1.0 if rate > 0 else -1.0  # Long one at 100: .01 costs one; -.01 credits one.
    np.testing.assert_allclose(result.equity, [1000.0, 1000.0 - cost, 1000.0 - cost], rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.funding, [0.0, cost, 0.0], rtol=0, atol=1e-12)
    np.testing.assert_array_equal(result.position, [0.0, 1.0, 1.0])
    np.testing.assert_array_equal(result.equity.index.asi8, [START_NS, START_NS + HOUR_NS, START_NS + 2 * HOUR_NS])
    assert (result.equity.index[-1] - result.equity.index[0]).total_seconds() == 7200
    assert str(result.equity.index.tz) == "UTC"
    assert len(result.fills) == 1
    assert result.fills[0].timestamp == pd.Timestamp("2024-01-01T01:00:00Z")


@pytest.mark.parametrize("runner", ("reference", "kernel", "session_kernel"))
@pytest.mark.parametrize("semantics", ("open", "close"))
def test_f17_event_position_order_is_not_remapped_to_coarse_funding(runner, semantics):
    tape = prepare_market_tape(
        data=_frame(_clock("us")), symbols=["BTC"], bar_timestamp_semantics=semantics,
        funding_event_timestamps=_clock("ns")[[1, 2]], funding_event_rates=[0.01, 0.01],
    )
    result = _execute(tape, runner)
    # Open funding precedes the new entry; close funding sees that same entry.
    expected_funding = [0.0, 0.0, 1.0] if semantics == "open" else [0.0, 1.0, 1.0]
    expected_equity = [1000.0, 1000.0, 999.0] if semantics == "open" else [1000.0, 999.0, 998.0]
    np.testing.assert_allclose(result.funding, expected_funding, rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.equity, expected_equity, rtol=0, atol=1e-12)


@pytest.mark.parametrize("unit", UNITS)
@pytest.mark.parametrize("with_session", (False, True))
def test_f16_public_prepared_identity_and_accounting_share_one_utc_clock(unit, with_session):
    index = _clock(unit, timezone="Asia/Ho_Chi_Minh")
    session = IntrabarSessionTape.from_index(index) if with_session else None
    endpoint = QuantBTEndpoint.intrabar_bracket(
        initial_capital=1000.0, fee_rate=0.0, use_funding=True, close_on_last_bar=False,
        report_level="audit", session_policy=SessionExecutionPolicy() if with_session else None,
    )
    funding = {"funding_event_timestamps": _clock("ns")[[1]], "funding_event_rates": [-0.01]}
    canonical = endpoint.prepare_intrabar(data=_frame(_clock()), symbols=["BTC"], session_tape=session, **funding)
    prepared = endpoint.prepare_intrabar(data=_frame(index), symbols=["BTC"], session_tape=session, **funding)
    assert prepared.profile_metadata["prepared_signature"] == canonical.profile_metadata["prepared_signature"]
    assert prepared.market.signature == canonical.market.signature

    result = prepared.run(IntrabarIntentTape.from_arrays(entry_side=[1, 0, 0], entry_size=[1.0, 0.0, 0.0]))
    np.testing.assert_allclose(result.equity, [1000.0, 1001.0, 1001.0], rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.funding, [0.0, -1.0, 0.0], rtol=0, atol=1e-12)
    accounting = NativeAccountingArrays.from_result(result)
    np.testing.assert_array_equal(accounting.timestamps, [START_NS, START_NS + HOUR_NS, START_NS + 2 * HOUR_NS])
    assert accounting.datetime_index.equals(result.equity.index)


@pytest.mark.parametrize("unit", ("ns", "us"))
@pytest.mark.parametrize("rate", (0.01, -0.01))
@pytest.mark.parametrize("with_session", (False, True))
def test_f16_f17_exact_native_binding_preserves_clock_funding_and_session(unit, rate, with_session):
    from quantbt.backends.native_intrabar_rust import run_rust_intrabar_kernel

    tape = prepare_market_tape(data=_frame(_clock(unit)), symbols=["BTC"],
        funding_event_timestamps=_clock("ns")[[1]], funding_event_rates=[rate])
    session = IntrabarSessionTape.from_index(pd.to_datetime(tape.timestamps_ns, unit="ns", utc=True)) if with_session else None
    result = run_rust_intrabar_kernel(tape=tape,
        intent=IntrabarIntentTape.from_arrays(entry_side=[1, 0, 0], entry_size=[1., 0., 0.]),
        account=AccountConfig(initial_capital=1000.),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=False),
        fee_rate=0., slippage_rate=0., report_level="audit", session_tape=session,
        session_policy=SessionExecutionPolicy() if with_session else None)
    assert result.metadata["rust_intrabar_authority"] is True
    np.testing.assert_allclose(result.equity, [1000., 1000. - rate * 100., 1000. - rate * 100.], atol=1e-12)
    np.testing.assert_allclose(result.funding, [0., rate * 100., 0.], atol=1e-12)
    assert result.equity.index[0] == pd.Timestamp("2024-01-01T00:00:00Z")
    assert (result.equity.index[-1] - result.equity.index[0]).total_seconds() == 7200
