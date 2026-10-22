"""Evidence-only stage spans; no financial or optimizer instrumentation patch."""

from contextlib import ExitStack
from functools import wraps
import inspect
from time import perf_counter
from unittest.mock import patch


class StageProfile:
    names = (
        "plan",
        "prepare",
        "ask_tell",
        "is_score",
        "native_selection",
        "history",
        "meta_fit",
        "meta_rank",
        "label_observer",
        "oos",
        "report",
    )

    def __init__(self):
        self.rows = {
            name: {"calls": 0, "inclusive_seconds": 0.0, "exclusive_seconds": 0.0}
            for name in self.names
        }
        self.stack = []
        self.callbacks = 0
        self.patches = ExitStack()

    def instrument(self, owner, name, stage):
        original = getattr(owner, name)
        descriptor = inspect.getattr_static(owner, name)

        @wraps(original)
        def call(*args, **kwargs):
            if name in {"_call_strategy", "_run_single"}:
                if name == "_call_strategy":
                    self.callbacks += 1
                if self.stack:
                    return original(*args, **kwargs)
            frame = [perf_counter(), 0.0]
            self.stack.append(frame)
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = perf_counter() - frame[0]
                self.stack.pop()
                row = self.rows[stage]
                row["calls"] += 1
                row["inclusive_seconds"] += elapsed
                row["exclusive_seconds"] += elapsed - frame[1]
                if self.stack:
                    self.stack[-1][1] += elapsed

        if isinstance(descriptor, classmethod):
            wrapped = classmethod(lambda cls, *a, **kw: call(*a, **kw))
        elif isinstance(descriptor, staticmethod):
            wrapped = staticmethod(call)
        else:
            wrapped = call
        self.patches.enter_context(patch.object(owner, name, wrapped))

    def __enter__(self):
        import optuna
        import quantbt.walkforward as wf
        from quantbt import QuantBTEndpoint
        from quantbt.optimization.meta_selection.history import MetaHistory
        from quantbt.optimization.meta_selection.model import RidgeLearner
        from quantbt.optimization.meta_selection.selection import MetaSelector
        from quantbt.optimization.meta_selection.runtime import PublicMetaRuntime

        for owner, name, stage in (
            (wf.WalkForwardEngine, "build_folds", "plan"),
            (wf.PreparedWalkForwardContext, "prepare", "prepare"),
            (optuna.Study, "optimize", "ask_tell"),
            (wf.WalkForwardEngine, "evaluate_params_is", "is_score"),
            (wf, "select_is_only_robust_record", "native_selection"),
            (MetaHistory, "snapshot", "history"),
            (RidgeLearner, "fit", "meta_fit"),
            (MetaSelector, "propose", "meta_rank"),
            (PublicMetaRuntime, "observe", "label_observer"),
            (wf.WalkForwardEngine, "_call_strategy", "oos"),
            (QuantBTEndpoint, "_run_single", "oos"),
            (PublicMetaRuntime, "finalize", "report"),
        ):
            self.instrument(owner, name, stage)
        return self

    def __exit__(self, *args):
        self.patches.close()

    def report(self, total):
        measured = sum(row["exclusive_seconds"] for row in self.rows.values())
        return {
            "stages": self.rows,
            "python_strategy_callbacks": self.callbacks,
            "unattributed_seconds": total - measured,
            "scope": "profiled engineering run only; inclusive spans overlap; exclusive spans plus residual reconcile total",
        }
