"""Compiler-cache and feedback projections, without private alpha sources."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from quantbt import AccountConfig, NativeEventBackend, NativeEventConfig, OrderAction, OrderActivationPolicy
from quantbt import OrderCommand, OrderSide, OrderType
from quantbt.backends._native_event_rust import compile_rust_full_tape
from quantbt.core.constraints import build_quantity_constraints
from tools.mode5_research.prepared_feedback import CachedTapeRows, LazyEngineFeedback
from tools.mode5_research.prepared_feedback import assert_native_audit_equivalent
from tools.mode5_research.prepared_feedback import assert_empty_reference_equivalent


class PreparedFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range("2021-01-01", periods=8, freq="h")
        self.backend = NativeEventBackend(NativeEventConfig(account=AccountConfig(initial_capital=20_000.)))
        self.runner = SimpleNamespace(market_arrays=SimpleNamespace(closes=np.full((8, 1), 100.)),
                                      contract_sizes=np.ones(1))
        self.constraints = build_quantity_constraints(["BTC"], qty_step=.01, min_qty=.01)
        self.cache = CachedTapeRows(self.backend, self.runner, self.index, "BTC", self.constraints)
        entry = OrderCommand(timestamp=self.index[1], symbol="BTC", side=OrderSide.BUY,
                             qty=1.234, order_type=OrderType.MARKET, order_id="entry")
        common = dict(timestamp=self.index[2], symbol="BTC", side=OrderSide.SELL,
                      qty=.5, reduce_only=True, parent_order_id="entry", oco_group_id="pair",
                      group_id="campaign", activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL)
        stop = OrderCommand(**common, order_id="stop", order_type=OrderType.STOP_MARKET, trigger_price=95.)
        tp = OrderCommand(**common, order_id="tp", order_type=OrderType.LIMIT, price=105., expires_at=self.index[6])
        amend = OrderCommand(timestamp=self.index[3], order_id="amend", action=OrderAction.AMEND,
                             target_order_id="tp", price=106.)
        cancel = OrderCommand(timestamp=self.index[4], order_id="cancel", action=OrderAction.CANCEL,
                              target_order_id="stop")
        cancel_all = OrderCommand(timestamp=self.index[5], order_id="clear", action=OrderAction.CANCEL_ALL,
                                  symbol="BTC")
        self.commands = (entry, stop, tp, amend, cancel, cancel_all)

    def assert_full_pack(self, commands):
        ptr, codes, values, expiry, ids = self.cache.pack(commands)
        effective, _ = self.backend._apply_command_quantity_constraints(idx=self.index,
            commands=commands, closes=self.runner.market_arrays.closes, symbol_list=["BTC"],
            contract_sizes=self.runner.contract_sizes, constraints=self.constraints)
        compiled = self.backend.compile_order_commands(self.index, effective, symbols=["BTC"])
        original_ptr, original_codes, original_values, original_expiry = compile_rust_full_tape(compiled)
        np.testing.assert_array_equal(ptr, original_ptr)
        np.testing.assert_array_equal(values, original_values)
        np.testing.assert_array_equal(expiry, original_expiry)
        ordinary = [i for i in range(16) if i not in (6, 7, 8, 9, 10)]
        np.testing.assert_array_equal(codes[:, ordinary], original_codes[:, ordinary])
        for column in (6, 7, 8, 9, 10):
            decode = lambda a, names: [None if value < 0 else names[value] for value in a]
            self.assertEqual(decode(codes[:, column], ids),
                             decode(original_codes[:, column], compiled.id_values))

    def test_incremental_rows_preserve_quantities_relationships_and_expiry(self):
        for stop in range(len(self.commands)+1):
            self.assert_full_pack(self.commands[:stop])
        self.assertEqual(self.cache.compiled_rows, len(self.commands))
        self.assert_full_pack(self.commands)
        self.assertEqual(self.cache.compiled_rows, len(self.commands))

    def test_changed_row_and_rolled_back_same_bar_keep_opaque_ids_correct(self):
        self.assert_full_pack(self.commands[:3])
        self.assert_full_pack(self.commands[:1])
        changed = self.commands[:2] + (replace(self.commands[2], price=107.),) + self.commands[3:]
        self.assert_full_pack(changed)
        self.assertEqual(self.cache.compiled_rows, len(self.commands)+1)

    def test_unqualified_order_and_duplicate_identity_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "unique explicit"):
            self.cache.pack((self.commands[0], self.commands[0]))
        with self.assertRaisesRegex(ValueError, "chronological"):
            self.cache.pack(self.commands[::-1])

    def feedback(self):
        a = SimpleNamespace(id_values=("entry", "cancel"),
            event_bar=np.array([1, 2]), event_kind=np.array([4, 1]), event_order_id=np.array([0, 1]),
            event_target_id=np.array([-1, 0]), event_status=np.array([2, 4]),
            event_symbol=np.array([0, 0]), event_reject_code=np.array([0, 0]),
            fill_bar=np.array([1]), fill_order_id=np.array([0]), fill_symbol=np.array([0]),
            fill_side=np.array([1]), fill_qty=np.array([1.]), fill_price=np.array([100.]), fill_fee=np.array([.05]),
            fill_reason=np.array([0]), fill_ambiguity=np.array([0]), fill_order_type=np.array([0]))
        for key in ("equity", "positions", "fees", "funding", "turnover", "initial_margin", "maintenance_margin"):
            setattr(a, key, np.ones(8))
        return LazyEngineFeedback(a, self.commands, self.index, 100, "BTC")

    def test_feedback_is_lazy_and_uses_absolute_strategy_bar(self):
        feedback = self.feedback()
        self.assertFalse(feedback.cache)
        event, = feedback.events_at(101)
        self.assertEqual(event.fill.timestamp, self.index[1])
        self.assertEqual(event.bar, 101)
        self.assertEqual(event.fill.qty, 1.)
        self.assertEqual(feedback.events_at(102), ())

    def test_prefix_witness_includes_cancel_amend_and_oco_not_only_fills(self):
        feedback = self.feedback()
        original = feedback.events_before(103)
        feedback.audit.event_status[1] += 1
        self.assertNotEqual(original, feedback.events_before(103))
        self.assertEqual(feedback.events_before(102)[0][0], np.array([1]).tobytes())

    def test_duplicate_partial_fill_requires_separate_transport(self):
        feedback = self.feedback()
        feedback.audit.fill_bar = np.array([1, 1])
        feedback.audit.fill_order_id = np.array([0, 0])
        with self.assertRaisesRegex(ValueError, "partial fill"):
            feedback.events_at(101)

    def test_committed_fill_semantics_and_liquidity_cannot_change(self):
        for field in ("fill_reason", "fill_ambiguity", "fill_order_type"):
            feedback = self.feedback()
            original = feedback.events_before(103)
            getattr(feedback.audit, field)[0] += 1
            self.assertNotEqual(original, feedback.events_before(103))

    def test_terminal_numeric_difference_does_not_use_pandas_relative_tolerance(self):
        paths = {key: np.ones(3) for key in ("equity", "returns", "positions", "fees", "funding", "margin")}
        meta = {key: pd.DataFrame({"status": [100.]}) for key in
            ("order_report", "order_events", "command_report", "active_orders",
             "command_outcome_report_v1", "lifecycle_event_report_v1")}
        meta.update(native_terminal_state_v1={"available": True}, lifecycle_counters={"fills": 1},
                    execution_contract_id="event_lifecycle_v2_next_bar_close")
        left = SimpleNamespace(**paths, fills=(), diagnostics=pd.DataFrame({"turnover": [0., 1., 0.]}),
                               metadata=meta, liquidated=False, liquidation_bar=-1)
        right = deepcopy(left)
        right.metadata["command_report"].loc[0, "status"] += 1e-5
        with self.assertRaises(AssertionError):
            assert_native_audit_equivalent(left, right)

    def test_completed_parity_detects_terminal_and_liquidation_change(self):
        paths = {key: np.ones(3) for key in ("equity", "returns", "positions", "fees", "funding", "margin")}
        meta = {key: pd.DataFrame({"status": [1]}) for key in
            ("order_report", "order_events", "command_report", "active_orders",
             "command_outcome_report_v1", "lifecycle_event_report_v1")}
        meta.update(native_terminal_state_v1={"available": True}, lifecycle_counters={"fills": 1},
                    execution_contract_id="event_lifecycle_v2_next_bar_close")
        left = SimpleNamespace(**paths, fills=(), diagnostics=pd.DataFrame({"turnover": [0., 1., 0.]}),
                               metadata=meta, liquidated=False, liquidation_bar=-1)
        right = deepcopy(left)
        assert_native_audit_equivalent(left, right)
        right.metadata["command_report"].loc[0, "status"] = 2
        with self.assertRaises(AssertionError):
            assert_native_audit_equivalent(left, right)
        right = deepcopy(left)
        right.liquidated = True
        with self.assertRaisesRegex(AssertionError, "liquidation"):
            assert_native_audit_equivalent(left, right)

    def test_empty_python_event_schema_does_not_skip_account_checks(self):
        paths = {key: np.ones(3) for key in ("equity", "returns", "positions", "fees", "funding", "margin")}
        left = SimpleNamespace(**paths, fills=(), diagnostics=SimpleNamespace(turnover=np.zeros(3)),
            metadata={"order_events": pd.DataFrame(), "execution_contract_id": "v2"},
            liquidated=False, liquidation_bar=-1)
        right = deepcopy(left)
        right.metadata["order_events"] = pd.DataFrame(columns=["timestamp", "order_id"])
        assert_empty_reference_equivalent(left, right, ())
        right.equity[-1] = 2.
        with self.assertRaises(AssertionError):
            assert_empty_reference_equivalent(left, right, ())
        right = deepcopy(left)
        right.liquidated = True
        with self.assertRaisesRegex(AssertionError, "liquidation"):
            assert_empty_reference_equivalent(left, right, ())


if __name__ == "__main__":
    unittest.main()
