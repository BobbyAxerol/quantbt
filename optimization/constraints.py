"""Formal constraint helpers for Optuna-backed optimization."""

from __future__ import annotations

from typing import Sequence


CONSTRAINTS_USER_ATTR = "quantbt_constraints"


def set_trial_constraints(trial, constraints: Sequence[float]) -> tuple[float, ...]:
    """Store constraints on an Optuna trial using QuantBT's canonical key."""

    values = tuple(float(value) for value in constraints)
    trial.set_user_attr(CONSTRAINTS_USER_ATTR, values)
    return values


def constraints_from_trial(frozen_trial) -> tuple[float, ...]:
    """Optuna sampler callback returning trial constraints."""

    return tuple(float(value) for value in frozen_trial.user_attrs.get(CONSTRAINTS_USER_ATTR, ()))
