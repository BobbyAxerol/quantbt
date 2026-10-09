"""Exact actual-feedback checks, with public synthetic orders only."""

from copy import copy
from dataclasses import replace

import pytest

from quantbt import OrderSide
from tools.mode5_admission.conformance import (
    Compilation, FeedbackNotCertified, certify_feedback, chronological_fills, result_signature,
)
from tests.mode5.test_admission_ledger import market, order, run


def fixture():
    data = market()
    commands = (order(data, 1, OrderSide.BUY, 2., "entry"),
                order(data, 3, OrderSide.SELL, 2., "exit", reduce_only=True))
    return data, commands


def test_full_feedback_requires_identical_decisions_and_actual_output():
    data, commands = fixture()
    cert = certify_feedback(
        lambda previous: Compilation(commands, ({"actual_count": 0 if previous is None else len(previous.fills)},),
                                     0 if previous is None else len(previous.fills)),
        lambda tape: run(data, tape))
    assert len(cert.iterations) == 3
    assert cert.iterations[-1]["command_hash"] == cert.iterations[-2]["command_hash"]
    assert cert.iterations[-1]["result_hash"] == cert.iterations[-2]["result_hash"]


@pytest.mark.parametrize("mutation", ("fill_price", "fill_fee", "event_reason", "equity", "position", "margin", "funding", "turnover"))
def test_same_exit_bars_are_not_a_full_feedback_certificate(mutation):
    data, commands = fixture()
    out = run(data, commands)
    before = result_signature(out)
    changed = copy(out)
    if mutation.startswith("fill_"):
        changed.fills = [replace(out.fills[0], **{mutation.removeprefix("fill_"): 1.}), *out.fills[1:]]
    elif mutation == "event_reason":
        changed.metadata = dict(out.metadata)
        changed.metadata["order_events"] = out.metadata["order_events"].copy()
        changed.metadata["order_events"].iloc[-1, -1] = 99
    elif mutation == "turnover":
        changed.diagnostics = copy(out.diagnostics)
        changed.diagnostics["turnover"] = out.diagnostics["turnover"].to_numpy().copy()
        changed.diagnostics.loc[changed.diagnostics.index[-1], "turnover"] += 1.
    else:
        key = "positions" if mutation == "position" else mutation
        value = getattr(out, key).copy()
        value.iloc[-1] += 1.
        setattr(changed, key, value)
    assert result_signature(changed) != before


def test_orphan_feedback_cycle_budget_and_nondeterminism_fail_closed():
    data, commands = fixture()
    with pytest.raises(FeedbackNotCertified, match="incomplete"):
        certify_feedback(lambda previous: Compilation(commands, (), 2, 1), lambda tape: run(data, tape))
    with pytest.raises(FeedbackNotCertified, match="within"):
        certify_feedback(lambda previous: Compilation(commands, (), 0 if previous is None else 2),
                         lambda tape: run(data, tape), max_runs=2)
    calls = []

    def alternating(previous):
        calls.append(1)
        return Compilation(commands, ({"flip": len(calls) % 2},), 2)

    with pytest.raises(FeedbackNotCertified, match="cycle"):
        certify_feedback(alternating, lambda tape: run(data, tape))
    calls.clear()

    def nondeterministic(tape):
        calls.append(1)
        out = run(data, tape)
        out.equity.iloc[-1] += len(calls)
        return out

    with pytest.raises(FeedbackNotCertified, match="different execution"):
        certify_feedback(lambda previous: Compilation(commands, (), 2), nondeterministic)
    with pytest.raises(ValueError, match="two actual"):
        certify_feedback(None, None, max_runs=1)


def test_actual_lifecycle_sequence_not_fill_list_order_is_authoritative():
    data, commands = fixture()
    result = run(data, commands)
    expected = tuple(result.fills)
    result.fills = list(reversed(result.fills))
    assert chronological_fills(result) == expected
    result.metadata["order_events"] = result.metadata["order_events"].iloc[:-1]
    with pytest.raises(FeedbackNotCertified, match="missing"):
        chronological_fills(result)
