"""Scheduling tests only; real economic parity uses the private alpha pilots."""

from copy import deepcopy
from types import SimpleNamespace
import unittest

import numpy as np

from tools.mode5_research.incremental_feedback import (
    DecisionSnapshot, FeedbackEvent, IncrementalFeedbackCompiler,
)


class Binding:
    start, stop = 0, 3

    def __init__(self):
        self.rows, self.calls = [], []

    def snapshot(self):
        return deepcopy(self.rows)

    def restore(self, state):
        self.rows = deepcopy(state)

    def advance(self, bar, events):
        self.calls.append((bar, tuple(event.kind for event in events)))
        if bar == 0 and not self.rows:
            self.rows.append("entry")
        if bar == 1 and events and "protect" not in self.rows:
            self.rows.append("protect")

    def commands(self):
        return tuple(self.rows)


def feedback(commands, *, changed_prefix=False, fill_bar=1):
    events = (FeedbackEvent(fill_bar, "entry", "fill"),)
    if "protect" in commands:
        events += (FeedbackEvent(fill_bar, "protect", "fill"),)
    return SimpleNamespace(paths={"equity": np.array([9. if changed_prefix else 10., 10., 10.])},
        events_at=lambda bar: events if bar == fill_bar else (),
        events_before=lambda bar: events if fill_bar < bar else ())


class IncrementalFeedbackTests(unittest.TestCase):
    def test_same_bar_protection_retries_only_current_bar(self):
        binding = Binding()
        compiler = IncrementalFeedbackCompiler(binding, feedback)
        compiler.run()
        self.assertEqual(binding.commands(), ("entry", "protect"))
        self.assertEqual(compiler.execution_calls, 2)
        self.assertEqual(compiler.bar_retries, 1)
        self.assertEqual(sum(bar == 0 for bar, _ in binding.calls), 1)

    def test_committed_account_prefix_change_is_rejected(self):
        compiler = IncrementalFeedbackCompiler(Binding(),
            lambda commands: feedback(commands, changed_prefix="protect" in commands))
        with self.assertRaisesRegex(AssertionError, "committed account"):
            compiler.run()

    def test_same_bar_retry_budget_is_explicit(self):
        compiler = IncrementalFeedbackCompiler(Binding(), feedback, max_bar_retries=1)
        with self.assertRaisesRegex(RuntimeError, "did not stabilize"):
            compiler.run()

    def test_no_trade_runs_one_actual_empty_tape(self):
        class Empty(Binding):
            def advance(self, bar, events):
                pass
        compiler = IncrementalFeedbackCompiler(Empty(), lambda commands: SimpleNamespace(
            paths={"equity": np.ones(3)}, events_at=lambda bar: (), events_before=lambda bar: ()))
        compiler.run()
        self.assertEqual(compiler.execution_calls, 1)

    def test_guard_failure_prevents_execution(self):
        def stop():
            raise TimeoutError("cap")
        with self.assertRaises(TimeoutError):
            IncrementalFeedbackCompiler(Binding(), lambda *_: self.fail("executed"), safe_point=stop).run()

    def test_snapshot_keeps_immutable_features_and_restores_mutable_state(self):
        features = np.arange(4.)
        adapter = SimpleNamespace(market=object(), features=features, params={"x": 1},
            decisions=["prior"], state={"position": 0}, staged=[1])
        snapshot = DecisionSnapshot(adapter)
        adapter.state["position"] = 5
        adapter.staged.append(2)
        adapter.decisions.append("uncommitted")
        adapter.new_mutable = True
        snapshot.restore(adapter)
        self.assertIs(adapter.features, features)
        self.assertEqual(adapter.state, {"position": 0})
        self.assertEqual(adapter.staged, [1])
        self.assertEqual(adapter.decisions, ["prior"])
        self.assertFalse(hasattr(adapter, "new_mutable"))


if __name__ == "__main__":
    unittest.main()
