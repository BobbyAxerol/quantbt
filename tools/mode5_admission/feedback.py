"""Map external long-flat decisions to the existing public callback route."""

from __future__ import annotations

import numpy as np

from quantbt import OrderCommand, OrderSide, OrderType, quantize_signed_quantity
from quantbt.wfo_execution import _CallbackCalendarCursor


class UnsupportedFinancialBinding(NotImplementedError):
    pass


def require_binding(*, requires_fill_reaction=False, assumed_fills=False,
                    unmapped_intents=0, ladder_collapsed=False):
    if assumed_fills or unmapped_intents or ladder_collapsed:
        raise UnsupportedFinancialBinding("unqualified or approximated financial binding")
    if requires_fill_reaction:
        raise UnsupportedFinancialBinding(
            "same-bar actual-fill protection requires a certified fill-reaction boundary; "
            "bar-close feedback must not be silently delayed or called equivalent"
        )


def require_exercised(witness, *, minimum_fills=2, minimum_closed_campaigns=1):
    if minimum_fills < 1 or minimum_closed_campaigns < 1:
        raise ValueError("binding support thresholds must be positive")
    if (witness.fill_count < minimum_fills or
            len(witness.closed_campaigns) < minimum_closed_campaigns):
        raise ValueError("INSUFFICIENT_ACTUAL_BINDING_SUPPORT")


class BarCloseBinding:
    """External adapter owns decisions; QuantBT owns every execution event.

    This version is deliberately limited to next-open entries/technical exits
    without fill-relative protections. It does not claim that arbitrary alpha
    adapters can be faithfully routed through the bar-close callback contract.
    """

    def __init__(self, adapter, *, symbol, index, score_start_bar, notional,
                 fill_factory, kind_type, qty_step=0., min_qty=0., min_notional=0.):
        self.adapter = adapter
        self.symbol, self.index = symbol, index
        self.score_start_bar = int(score_start_bar)
        self.notional = float(notional)
        self.fill_factory, self.kind_type = fill_factory, kind_type
        self.qty_step, self.min_qty, self.min_notional = qty_step, min_qty, min_notional
        self.events = []
        self.fill_feedback_count = 0
        self.preflight_rejections = []
        self.entry_capacity = 0.
        self._calendar = _CallbackCalendarCursor(index)

    def initialize(self, context):
        self.adapter.prepare()
        self.adapter._prepared = True
        return ()

    def on_bar_close(self, context):
        if self._calendar.index is not self.index:
            self._calendar = _CallbackCalendarCursor(self.index)
        offset = self._calendar.locate(context.timestamp)
        if offset is None:
            offset = int(self.index.get_indexer([context.timestamp])[0])
        if offset < 0:
            raise ValueError("engine callback is outside the registered feature calendar")
        for fill in context.fills_this_bar:
            kind = self.kind_type(fill.metadata["admission_intent_kind"])
            follow = self.adapter.on_fill(self.fill_factory(
                index=offset, side=fill.side.sign, quantity=fill.qty * fill.side.sign,
                price=fill.price, intent_kind=kind, fee=fill.fee,
            ))
            if follow:
                raise UnsupportedFinancialBinding("bar-close binding cannot execute fill-relative protection")
            self.fill_feedback_count += 1
            if self.adapter.state.position == 0.:
                self.entry_capacity = 0.
        for event in context.order_events_this_bar:
            if event.event_name == "reject":
                self.adapter.state.pending_entry_side = 0
                self.adapter.state.pending_exit = False
                if self.adapter.state.position == 0.:
                    self.entry_capacity = 0.
        actual, expected = self.adapter.state.position, context.positions[self.symbol]
        scalar_match = (type(actual) in (float, np.float64) and type(expected) in (float, np.float64)
            and (actual == expected or abs(float(actual) - float(expected)) <= 1e-12
                 or (actual != actual and expected != expected)))
        if not scalar_match:
            np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12,
                                       err_msg="strategy actual-fill feedback mismatch")
        if offset < self.score_start_bar:
            raise ValueError("financial run must exclude feature-only preload")
        decision = self.adapter.on_bar_close(offset)
        commands = []
        for ordinal, intent in enumerate(decision.intents):
            kind = intent.kind.value
            if intent.earliest_phase.value != "next_open" or kind not in {"enter_long", "enter_short", "exit_all"}:
                raise UnsupportedFinancialBinding("unmapped financial intent")
            if kind == "exit_all":
                position = context.positions[self.symbol]
                quantity = abs(position)
                side = OrderSide.SELL if position > 0 else OrderSide.BUY
            else:
                price = float(context.close[0])
                quantity = quantize_signed_quantity(
                    self.notional / price, price=price, contract_size=1.,
                    qty_step=self.qty_step, min_qty=self.min_qty, min_notional=self.min_notional,
                )
                side = OrderSide.BUY if kind == "enter_long" else OrderSide.SELL
            self.events.append(dict(decision_bar=offset, kind=kind, quantity=float(quantity)))
            if quantity == 0:
                self.preflight_rejections.append(dict(bar=offset, reason="QUANTITY_CONSTRAINT"))
                self.adapter.state.pending_entry_side = 0
                self.adapter.state.pending_exit = False
                continue
            raw_quantity = (self.entry_capacity if kind == "exit_all" else self.notional / float(context.close[0]))
            if kind != "exit_all":
                self.entry_capacity = raw_quantity
            commands.append(OrderCommand(
                timestamp=context.timestamp, symbol=self.symbol, side=side,
                order_type=OrderType.MARKET, qty=raw_quantity,
                reduce_only=kind == "exit_all", order_id=f"admission-{offset}-{ordinal}",
                metadata={"admission_intent_kind": kind, "admission_decision_bar": offset,
                          "requested_quote_notional": self.notional if kind != "exit_all" else None,
                          "sizing_contract": "observation_close_quote_next_open_execution"},
            ))
        return tuple(commands)

    def finalize(self, context):
        return ()
