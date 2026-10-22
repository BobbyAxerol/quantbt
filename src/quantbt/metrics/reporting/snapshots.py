"""Validated reconstruction for reporting value objects, never serialized hashes."""

from copy import deepcopy
from dataclasses import fields

import numpy as np


def immutable_storage(array):
    """Share bytes only; always return a private ndarray shape/dtype header."""
    owner, readonly = array, True
    while isinstance(owner, np.ndarray):
        readonly = readonly and not owner.flags.writeable
        owner = owner.base
    if isinstance(owner, bytes) and readonly:
        start = np.frombuffer(owner, dtype=np.uint8).__array_interface__["data"][0]
        offset = array.__array_interface__["data"][0] - start
        return np.ndarray(array.shape, dtype=array.dtype, buffer=owner, offset=offset, strides=array.strides)
    return np.ndarray(array.shape, dtype=array.dtype, buffer=array.tobytes())


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

    def _seal_arrays(self):
        arrays, children = [], []

        def collect(value):
            if isinstance(value, np.ndarray):
                arrays.append((value, value.dtype, value.shape, value.strides,
                               value.__array_interface__["data"][0], value.base))
            elif isinstance(value, SnapshotValue):
                value.validate_snapshot()
                children.append(value)
            elif isinstance(value, tuple):
                for item in value:
                    collect(item)

        for field in fields(self):
            collect(getattr(self, field.name))
        object.__setattr__(self, "_snapshot_layout", (tuple(arrays), tuple(children)))

    def validate_snapshot(self):
        # Bytes are immutable, but NumPy permits replacing dtype/shape/strides/data.
        # Check only headers, not observations, including on a warm cache hit.
        arrays, children = self._snapshot_layout
        for array, dtype, shape, strides, pointer, owner in arrays:
            if (array.dtype != dtype or array.shape != shape or array.strides != strides
                    or array.flags.writeable or array.base is not owner
                    or array.__array_interface__["data"][0] != pointer):
                raise ValueError("reporting snapshot array header changed; construct a new snapshot")
        for child in children:
            child.validate_snapshot()

    def __copy__(self):
        return self.__deepcopy__({})

    def __deepcopy__(self, memo):
        self.validate_snapshot()
        arguments = {field.name: _clone_argument(getattr(self, field.name), memo)
                     for field in fields(self) if field.init}
        restored = type(self)(**arguments)
        memo[id(self)] = restored
        return restored

    def __reduce_ex__(self, protocol):
        self.validate_snapshot()
        arguments = {field.name: getattr(self, field.name) for field in fields(self) if field.init}
        return _restore_snapshot, (type(self), arguments)

    def __setstate__(self, state):
        # Old dataclass pickles contain __dict__ and a derived hash; revalidate it.
        descriptors = fields(self)
        expected = {field.name for field in descriptors}
        if not isinstance(state, dict) or set(state) not in (expected, expected | {"_snapshot_layout"}):
            raise ValueError("complete reporting snapshot state required")
        restored = type(self)(**{field.name: state[field.name] for field in descriptors if field.init})
        for field in descriptors:
            object.__setattr__(self, field.name, getattr(restored, field.name))
        self._seal_arrays()
