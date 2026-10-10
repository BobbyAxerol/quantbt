"""Ordered ask/evaluate/tell over shared samplers; no financial ownership."""
import math
from time import perf_counter

import optuna

from ..core.runtime_governance import RuntimeCanceledError


def run_ordered_study(study, *, budget, batch_size, suggest, evaluate,
                      cancellation=None, deadline_seconds=None):
    """Sequential if size=1, otherwise ask a fixed batch before ordered tells.

    Python callbacks evaluate serially. This batches optimizer observation,
    not an unsupported promise of parallel callback execution. Pruned/failed
    and canceled work remains terminal, never a synthetic negative score.
    """
    if type(budget) is not int or budget < 1 or type(batch_size) is not int or batch_size < 1:
        raise ValueError("positive integer query budget and batch size required")
    if deadline_seconds is not None and (not math.isfinite(deadline_seconds) or deadline_seconds < 0):
        raise ValueError("finite nonnegative deadline required")
    started = perf_counter()
    attempted = 0
    while attempted < budget:
        if (cancellation is not None and cancellation.canceled) or (
                deadline_seconds is not None and perf_counter()-started >= deadline_seconds):
            raise RuntimeCanceledError("calibration canceled before next ask")
        trials = [study.ask() for _ in range(min(batch_size, budget-attempted))]
        fatal = None
        for trial in trials:
            try:
                if (fatal is not None or (cancellation is not None and cancellation.canceled)
                        or (deadline_seconds is not None and perf_counter()-started >= deadline_seconds)):
                    trial.set_user_attr("termination", "CANCELED")
                    study.tell(trial, state=optuna.trial.TrialState.FAIL)
                    fatal = fatal or RuntimeCanceledError("calibration canceled")
                    continue
                params = suggest(trial)
                value = evaluate(trial, params)
                if not math.isfinite(value):
                    raise optuna.TrialPruned("undefined objective")
                trial.report(value, step=0)
                if trial.should_prune():
                    raise optuna.TrialPruned("declared pruner")
                study.tell(trial, value)
            except optuna.TrialPruned as exc:
                trial.set_user_attr("termination", str(exc))
                study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            except Exception as exc:
                trial.set_user_attr("termination", "CANCELED" if isinstance(exc, RuntimeCanceledError) else "FAILED")
                trial.set_user_attr("error_type", type(exc).__name__)
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                fatal = exc
        attempted += len(trials)
        if fatal is not None:
            raise fatal
