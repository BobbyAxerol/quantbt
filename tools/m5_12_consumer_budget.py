"""Call-through search instrumentation, enabled for exactly one pytest call."""

from contextlib import contextmanager, ExitStack
from functools import wraps
from inspect import signature
from unittest.mock import patch

import pytest


class OptimizerBudget:
    def __init__(self, execution_case, proposal_limit=12, financial_limit=23):
        self.execution_case = execution_case
        self.proposal_limit = proposal_limit
        self.financial_limit = financial_limit
        self.active = None
        self.execution_cases = 0
        self.forbidden = []
        self.studies = []
        self.optimize_trials = []
        self.ask_calls = self.tell_calls = self.walkforward_runs = 0

    def reject(self, reason):
        self.forbidden.append(reason)
        raise AssertionError(reason)

    def begin(self, node):
        if self.active is not None:
            self.reject("nested installed test execution")
        if node == self.execution_case:
            if self.execution_cases:
                self.reject("bounded execution cannot retry")
            self.execution_cases += 1
        self.active = node

    def end(self):
        self.active = None

    def pytest_configure(self, config):
        config._m512_optimizer_budget = self

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item):
        self.begin(item.nodeid)
        try:
            return (yield)
        finally:
            self.end()

    def wrap(self, name, original):
        @wraps(original)
        def guarded(*args, **kwargs):
            if self.active != self.execution_case:
                self.reject("optimizer outside precisely named execution case: " + name)
            if name == "create_study":
                if len(self.studies) >= 4:
                    self.reject("study creation budget exceeded")
            elif name in {"ask", "tell", "optimize"}:
                if not args or not any(args[0] is study for study in self.studies):
                    self.reject("optimizer attempted an unobserved/reused study")
                if name == "ask":
                    if self.ask_calls >= self.proposal_limit or self.ask_calls + sum(self.optimize_trials) >= self.proposal_limit:
                        self.reject("Study.ask/shared proposal budget exceeded")
                    self.ask_calls += 1
                elif name == "tell":
                    if self.tell_calls >= self.ask_calls:
                        self.reject("Study.tell has no observed proposal")
                    self.tell_calls += 1
                else:
                    bound = signature(original).bind(*args, **kwargs)
                    bound.apply_defaults()
                    trials = bound.arguments.get("n_trials")
                    jobs = bound.arguments.get("n_jobs", 1)
                    if (type(trials) is not int or trials != 2 or len(self.optimize_trials) >= 2
                            or type(jobs) is not int or jobs != 1
                            or self.ask_calls + sum(self.optimize_trials) + trials > self.proposal_limit):
                        self.reject("missing/changed Study.optimize trial or serial budget")
                    self.optimize_trials.append(trials)
            elif name == "walkforward":
                if self.walkforward_runs >= 3:
                    self.reject("walk-forward invocation budget exceeded")
                self.walkforward_runs += 1
            else:
                self.reject("unknown optimizer instrumentation")
            result = original(*args, **kwargs)
            if name == "create_study":
                if any(result is study for study in self.studies):
                    self.reject("reused study returned by creation")
                self.studies.append(result)
            return result
        return guarded

    @contextmanager
    def protect(self, optuna, engine):
        with ExitStack() as stack:
            for owner, attribute, name in (
                (optuna, "create_study", "create_study"),
                (optuna.study.Study, "optimize", "optimize"),
                (optuna.study.Study, "ask", "ask"),
                (optuna.study.Study, "tell", "tell"),
                (engine, "run", "walkforward"),
            ):
                stack.enter_context(patch.object(owner, attribute, self.wrap(name, getattr(owner, attribute))))
            yield self

    def receipt(self):
        return dict(execution_case=self.execution_case, execution_cases=self.execution_cases,
            proposal_limit=self.proposal_limit, financial_limit=self.financial_limit,
            create_study_calls=len(self.studies), optimize_trials=list(self.optimize_trials),
            ask_calls=self.ask_calls, tell_calls=self.tell_calls, walkforward_runs=self.walkforward_runs,
            forbidden_calls=list(self.forbidden), observed_proposals=self.ask_calls + sum(self.optimize_trials))
