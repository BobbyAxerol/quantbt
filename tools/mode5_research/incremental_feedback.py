"""Causal, current-bar transactional compilation over actual engine feedback.

This research tool owns decisions, never fills or accounting. A replay callback
must return the existing engine's fills/events and dense account paths.
"""

from copy import deepcopy
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FeedbackEvent:
    bar: int
    order_id: str
    kind: str
    fill: object = None
    record: object = None


class IncrementalFeedbackCompiler:
    """Commit a bar only after its generated orders and feedback stabilize.

    The supplied binding translates exactly the original alpha's intents. Its
    snapshot/restore covers all mutable decision state, not financial state.
    New next-bar commands may change the suffix; same-bar protections require a
    transaction retry. Earlier account paths must remain unchanged.
    """

    def __init__(self, binding, execute, *, safe_point=None, max_bar_retries=32):
        if max_bar_retries < 1:
            raise ValueError("positive same-bar retry budget required")
        self.binding, self.execute = binding, execute
        self.safe_point = safe_point or (lambda: None)
        self.max_bar_retries = int(max_bar_retries)
        self.execution_calls = 0
        self.bar_steps = 0
        self.bar_retries = 0

    @staticmethod
    def _prefix_unchanged(before, after, bar):
        if before is None:
            return
        stop = max(0, bar - getattr(before, "path_offset", 0))
        for key in before.paths:
            if not np.array_equal(before.paths[key][:stop], after.paths[key][:stop]):
                raise AssertionError(f"committed account prefix changed: {key}")
        if before.events_before(bar) != after.events_before(bar):
            raise AssertionError("committed lifecycle prefix changed")

    def run(self):
        feedback = None
        executed_commands = None
        for bar in range(self.binding.start, self.binding.stop):
            self.safe_point()
            checkpoint = self.binding.snapshot()
            previous_events = () if feedback is None else feedback.events_at(bar)
            for retry in range(self.max_bar_retries):
                if retry:
                    self.binding.restore(checkpoint)
                    self.bar_retries += 1
                self.binding.advance(bar, previous_events)
                self.bar_steps += 1
                commands = self.binding.commands()
                if commands != executed_commands:
                    self.safe_point()
                    updated = self.execute(commands)
                    self.execution_calls += 1
                    self._prefix_unchanged(feedback, updated, bar)
                    feedback = updated
                    executed_commands = commands
                current_events = () if feedback is None else feedback.events_at(bar)
                if current_events == previous_events:
                    break
                previous_events = current_events
            else:
                raise RuntimeError("same-bar actual feedback did not stabilize")
        if feedback is None:
            feedback = self.execute(())
            self.execution_calls += 1
        self.safe_point()
        return feedback


class DecisionSnapshot:
    """Small snapshot excluding immutable indicators and accumulated records."""

    def __init__(self, adapter, *, immutable=("market", "features", "params")):
        self.immutable = frozenset(immutable)
        self.values = deepcopy({key: value for key, value in vars(adapter).items()
                                if key not in self.immutable and key != "decisions"})
        self.decision_count = len(adapter.decisions)

    def restore(self, adapter):
        for key in tuple(vars(adapter)):
            if key not in self.immutable and key != "decisions":
                delattr(adapter, key)
        vars(adapter).update(deepcopy(self.values))
        del adapter.decisions[self.decision_count:]
