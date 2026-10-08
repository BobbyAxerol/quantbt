"""Validated reconstruction for reporting value objects, never serialized hashes."""

from copy import deepcopy
from dataclasses import fields

import numpy as np


def immutable_storage(array):
    """Share bytes only; always return a private ndarray shape/dtype header."""
    owner = array
    while isinstance(owner, np.ndarray):
        owner = owner.base
    if isinstance(owner, bytes):
        return array.view()
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def _restore_snapshot(cls, arguments):
    return cls(**arguments)


def _clone_argument(value, memo):
    if isinstance(value, np.ndarray):
        # The constructor revalidates/freezes storage, including mutable old state.
        return value.view()
    if isinstance(value, tuple):
        return tuple(_clone_argument(item, memo) for item in value)
    return deepcopy(value, memo)


class SnapshotValue:
    """Dataclass copy/pickle reconstruction runs the same validation as creation."""

    def __copy__(self):
        return self.__deepcopy__({})

    def __deepcopy__(self, memo):
        arguments = {field.name: _clone_argument(getattr(self, field.name), memo)
                     for field in fields(self) if field.init}
        restored = type(self)(**arguments)
        memo[id(self)] = restored
        return restored

    def __reduce_ex__(self, protocol):
        arguments = {field.name: getattr(self, field.name) for field in fields(self) if field.init}
        return _restore_snapshot, (type(self), arguments)

    def __setstate__(self, state):
        # Old dataclass pickles contain __dict__ and a derived hash; revalidate it.
        descriptors = fields(self)
        if not isinstance(state, dict) or set(state) != {field.name for field in descriptors}:
            raise ValueError("complete reporting snapshot state required")
        restored = type(self)(**{field.name: state[field.name] for field in descriptors if field.init})
        for field in descriptors:
            object.__setattr__(self, field.name, getattr(restored, field.name))
