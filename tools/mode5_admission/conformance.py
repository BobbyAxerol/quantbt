"""Bounded actual-engine feedback certification, never a fill simulator.

This offline admission utility qualifies a compiler, not an online callback
capability. Only the supplied QuantBT execution result may provide feedback.
"""

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import math

import numpy as np
import pandas as pd

from tools.mode5_baseline.isolation import canonical_digest


class FeedbackNotCertified(RuntimeError):
    pass


def representation(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: representation(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, pd.DataFrame):
        return dict(index=representation(tuple(value.index)), columns=list(value.columns),
                    records=representation(value.to_dict("records")))
    if isinstance(value, pd.Series):
        return dict(index=representation(tuple(value.index)), values=representation(value.to_numpy()))
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            return representation(value.tolist())
        return dict(shape=list(value.shape), dtype=str(value.dtype),
                    sha256=sha256(np.ascontiguousarray(value).tobytes()).hexdigest())
    if isinstance(value, dict):
        return {str(key): representation(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [representation(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)) or value is pd.NaT:
        return str(value)
    if isinstance(value, np.generic):
        return representation(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return dict(nonfinite=repr(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported witness type: {type(value).__name__}")


def result_signature(result):
    """Include full lifecycle and accounting paths, not exit bars/equity alone."""
    paths = {name: representation(getattr(result, name)) for name in
             ("equity", "returns", "positions", "fees", "funding", "margin")}
    paths["turnover"] = representation(result.diagnostics.turnover)
    return canonical_digest(dict(paths=paths, fills=representation(result.fills),
        orders=representation(result.orders), trades=representation(result.trades),
        events=representation(result.metadata["order_events"]),
        terminal={key: representation(result.metadata.get(key)) for key in
                  ("order_report", "command_report", "active_orders", "quantity_preflight")},
        liquidated=result.liquidated, liquidation_bar=result.liquidation_bar,
        contract=result.metadata["execution_contract_id"],
        requested_backend=result.metadata["native_event_backend_requested"],
        resolved_backend=result.metadata["native_event_backend_resolved"]))


def chronological_fills(result):
    """Project command-ordered fills into the engine's actual event sequence."""
    fills = {(fill.timestamp, fill.order_id): fill for fill in result.fills}
    if len(fills) != len(result.fills):
        raise FeedbackNotCertified("multiple fills per order need an explicit partial-fill transport")
    ordered = []
    for event in result.metadata["order_events"].to_dict("records"):
        if event["event_name"] == "fill":
            key = event["timestamp"], event["order_id"]
            if key not in fills:
                raise FeedbackNotCertified("fill event has no matching actual fill")
            ordered.append(fills.pop(key))
    if fills:
        raise FeedbackNotCertified("actual fills missing from lifecycle event witness")
    return tuple(ordered)


@dataclass
class Compilation:
    commands: tuple
    decisions: tuple
    feedback_count: int = 0
    unmapped_feedback: int = 0

    def signature(self):
        return canonical_digest(representation(self))


@dataclass
class FeedbackCertificate:
    result: object
    compilation: Compilation
    iterations: tuple


def certify_feedback(build, execute, *, max_runs=256):
    """Recompile from real feedback until commands AND all outputs are exact.

    Every pass starts a fresh strategy/account. Cycles and insufficient budget
    fail closed. A second identical actual execution is required at exit.
    """
    if max_runs < 2:
        raise ValueError("at least two actual executions are required")
    previous = None
    previous_compilation = None
    previous_result_hash = None
    seen = set()
    iterations = []
    for ordinal in range(max_runs):
        compilation = build(previous)
        command_hash = compilation.signature()
        result = execute(compilation.commands)
        result_hash = result_signature(result)
        iterations.append(dict(run=ordinal + 1, commands=len(compilation.commands),
            fills=len(result.fills), command_hash=command_hash, result_hash=result_hash,
            unmapped_feedback=compilation.unmapped_feedback))
        if previous_compilation == command_hash:
            if previous_result_hash != result_hash:
                raise FeedbackNotCertified("identical compilation produced different execution witness")
            if compilation.unmapped_feedback or compilation.feedback_count != len(result.fills):
                raise FeedbackNotCertified("incomplete actual feedback at fixed point")
            return FeedbackCertificate(result, compilation, tuple(iterations))
        key = command_hash, result_hash
        if key in seen:
            raise FeedbackNotCertified("actual-feedback compilation cycle")
        seen.add(key)
        previous, previous_compilation, previous_result_hash = result, command_hash, result_hash
    raise FeedbackNotCertified(f"no full-feedback fixed point within {max_runs} actual runs")
