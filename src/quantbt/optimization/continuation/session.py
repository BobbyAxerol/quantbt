"""Owned public-API replay; no evaluator, arbitrary pickle, or account replay."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading

import optuna

from ..callbacks import SingleObjectiveEarlyStopping
from ..space import stable_params_key
from .contract import (MAX_EVENTS, SCHEMA, ContinuationError, binding_payload,
                       canonical, clone, decode, digest, runtime_identity)
from .storage import read_checkpoint, write_checkpoint


@dataclass(frozen=True)
class Proposal:
    number: int
    requested: dict
    effective: dict
    duplicate: bool


class _CallbackStudy:
    def __init__(self, session):
        self.session = session

    @property
    def best_value(self):
        return self.session._study.best_value

    def stop(self):
        # Study.stop() requires Study.optimize(); this owned runner uses ask/tell.
        self.session._stopped = True


class ExactStudySession:
    def __init__(self, config, *, binding):
        self.config = config
        self._config = clone(config.payload())
        self._binding = binding_payload(binding)
        self._runtime = runtime_identity()
        self._owner_thread = threading.get_ident()
        self._bridge = config.bridge()
        sampler = self._bridge.sampler(result_constraints=config.result_constraints)
        pruner_class = optuna.pruners.NopPruner if config.pruner["name"] == "nop" else optuna.pruners.MedianPruner
        self._study = optuna.create_study(study_name=config.study_name, direction=config.direction,
                                          sampler=sampler, pruner=pruner_class(**config.pruner["kwargs"]))
        self._bridge.enqueue(self._study, config.warm_start)
        self._pending, self._seen, self._journal = {}, set(), []
        self._attempts, self._stopped, self._poisoned = 0, False, False
        self._early = None if config.early_stopping is None else SingleObjectiveEarlyStopping(
            direction=config.direction, **config.early_stopping)

    def _check(self):
        if threading.get_ident() != self._owner_thread:
            raise ContinuationError("owned session cannot be driven from another thread")
        if self._poisoned:
            raise ContinuationError("session has an uncommitted operation; discard or explicitly recover externally")
        if clone(self.config.payload()) != self._config:
            raise ContinuationError("session config mutated")

    def _record(self, event):
        if len(self._journal) >= MAX_EVENTS:
            self._poisoned = True
            raise ContinuationError("checkpoint event limit exceeded")
        self._journal.append(clone(event))

    def ask(self):
        self._check()
        if self._stopped or self._attempts >= self.config.budget:
            raise ContinuationError("study stopped or trial budget exhausted")
        self._poisoned = True
        trial = self._study.ask()
        requested, effective = self._bridge.suggest(trial)
        key = stable_params_key(effective)
        duplicate = key in self._seen
        self._seen.add(key)
        self._pending[trial.number] = (trial, duplicate)
        self._attempts += 1
        self._record(dict(op="ask", number=trial.number, requested=requested,
                          effective=effective, duplicate=duplicate))
        self._poisoned = False
        return Proposal(trial.number, clone(requested), clone(effective), duplicate)

    def _trial(self, number):
        self._check()
        if type(number) is not int or number not in self._pending:
            raise ContinuationError("trial is not owned RUNNING work")
        return self._pending[number][0]

    def report(self, number, value, step):
        trial = self._trial(number)
        value = _finite(value)
        reports = self._study.get_trials(deepcopy=False)[number].intermediate_values
        if type(step) is not int or step < 0 or step in reports:
            raise ContinuationError("report requires a unique nonnegative integer step")
        self._poisoned = True
        trial.report(value, step)
        self._record(dict(op="report", number=number, value=value, step=step))
        self._poisoned = False

    def should_prune(self, number):
        trial = self._trial(number)
        self._poisoned = True
        answer = bool(trial.should_prune())
        self._record(dict(op="prune", number=number, answer=answer))
        self._poisoned = False
        return answer

    def tell(self, number, value=None, *, state="COMPLETE", constraints=(), reason=None):
        trial = self._trial(number)
        if state not in {"COMPLETE", "PRUNED", "FAIL"}:
            raise ContinuationError("tell requires a terminal trial state")
        value = _finite(value) if state == "COMPLETE" else value
        if state != "COMPLETE" and value is not None:
            raise ContinuationError("non-COMPLETE tell cannot supply an objective")
        constraints = [_finite(v) for v in constraints]
        if constraints and not self.config.result_constraints:
            raise ContinuationError("constraints not declared in session config")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ContinuationError("reason must be a nonempty string or null")
        duplicate = self._pending[number][1]
        if duplicate and self.config.duplicate_policy == "prune":
            if state != "PRUNED":
                raise ContinuationError("duplicate requires explicit PRUNED terminal disposition")
            reason = "DUPLICATE_EFFECTIVE_PARAMS"
        self._poisoned = True
        self._bridge.constraints(trial, constraints)
        if reason is not None:
            trial.set_user_attr("qms_rejection_reason", reason)
        frozen = self._study.tell(trial, value, state=optuna.trial.TrialState[state])
        del self._pending[number]
        if self._early is not None:
            self._early(_CallbackStudy(self), frozen)
        self._record(dict(op="tell", number=number, value=value, state=state,
                          constraints=constraints, reason=reason, stopped=self._stopped))
        self._poisoned = False

    @property
    def stopped(self):
        return self._stopped

    @property
    def trials(self):
        return self._study.get_trials(deepcopy=True)

    @property
    def best_trial(self):
        return self._study.best_trial

    def witness(self):
        self._check()
        rows = []
        for trial in self.trials:
            attrs = {key: value for key, value in trial.user_attrs.items()
                     if key != "qms_proposal_seconds"}
            rows.append(dict(number=trial.number, state=trial.state.name, params=trial.params,
                             values=trial.values, attrs=attrs,
                             distributions={k: optuna.distributions.distribution_to_json(v)
                                            for k, v in trial.distributions.items()},
                             intermediate=list(trial.intermediate_values.items())))
        observed = self._bridge.observed
        return clone(dict(rows=rows, seen=sorted(self._seen), attempts=self._attempts,
                          stopped=self._stopped, early=None if self._early is None else dict(
                              best=self._early._best, stale=self._early._stale,
                              completed=self._early._completed),
                          events=observed.events, independent=dict(observed.independent),
                          relative=observed.relative, relative_spaces=observed.relative_spaces))

    def dumps(self):
        self._check()
        if self._pending:
            raise ContinuationError("checkpoint barrier requires no RUNNING trials")
        if runtime_identity() != self._runtime:
            raise ContinuationError("execution source/runtime changed")
        payload = dict(config=self._config, binding=self._binding, runtime=self._runtime,
                       events=self._journal, witness=self.witness())
        content_digest = digest(payload)
        return canonical(dict(schema=SCHEMA, payload=payload, digest=content_digest)), content_digest

    def save(self, path, *, previous_digest=None):
        text, content_digest = self.dumps()
        write_checkpoint(path, text, previous_digest=previous_digest)
        return content_digest

    @classmethod
    def loads(cls, text, *, config, binding, expected_digest):
        payload = decode(text, expected_digest=expected_digest)
        if not isinstance(payload, dict) or set(payload) != {"config", "binding", "runtime", "events", "witness"}:
            raise ContinuationError("checkpoint payload fields invalid")
        if canonical(payload["config"]) != canonical(config.payload()) or payload["binding"] != binding_payload(binding):
            raise ContinuationError("checkpoint config/binding/cutoff identity mismatch")
        if payload["runtime"] != runtime_identity():
            raise ContinuationError("checkpoint dependency/runtime/source mismatch")
        events = payload["events"]
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ContinuationError("checkpoint event limit/type invalid")
        session = cls(config, binding=binding)
        try:
            for event in events:
                if not isinstance(event, dict) or "op" not in event:
                    raise ContinuationError("invalid checkpoint event")
                op = event["op"]
                if op == "ask":
                    session.ask()
                elif op == "report":
                    session.report(event["number"], event["value"], event["step"])
                elif op == "prune":
                    session.should_prune(event["number"])
                elif op == "tell":
                    session.tell(event["number"], event["value"], state=event["state"],
                                 constraints=event["constraints"], reason=event["reason"])
                else:
                    raise ContinuationError("unsupported checkpoint operation")
                if canonical(session._journal[-1]) != canonical(event):
                    raise ContinuationError("replayed proposal/pruner/tell divergence")
            if session._pending or canonical(session.witness()) != canonical(payload["witness"]):
                raise ContinuationError("checkpoint pending/final state witness mismatch")
        except ContinuationError:
            raise
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ContinuationError("corrupt or unsupported checkpoint state") from exc
        return session

    @classmethod
    def load(cls, path, **kwargs):
        return cls.loads(read_checkpoint(path), **kwargs)


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ContinuationError("objective/report/constraint must be finite numeric data")
    return float(value)
