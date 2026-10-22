"""Continuous snapshot constructors seal nested immutable array headers."""

from copy import copy, deepcopy
import pickle

import numpy as np
import pytest

from quantbt.mode5.continuous import ContinuousStream
from quantbt.mode5.continuous_retention import ContinuousAccountRetention


CLONES = (
    pytest.param(copy, id="copy"),
    pytest.param(deepcopy, id="deepcopy"),
    pytest.param(lambda value: pickle.loads(pickle.dumps(value, protocol=4)), id="pickle4"),
    pytest.param(lambda value: pickle.loads(pickle.dumps(value, protocol=5)), id="pickle5"),
)


@pytest.mark.parametrize("clone", CLONES)
def test_direct_stream_roundtrip_keeps_detached_readonly_two_column_margin(clone):
    source = np.arange(288, dtype=np.float64).reshape(144, 2)
    expected = source.copy()
    original = ContinuousStream("margin", source)
    source[:] = -123.
    restored = clone(original)

    assert restored.name == original.name == "margin"
    assert restored.values is not original.values
    for stream in (original, restored):
        stream.validate_snapshot()
        assert stream.values.shape == (144, 2)
        assert stream.values.dtype == np.dtype("float64")
        np.testing.assert_array_equal(stream.values, expected)
        assert not np.shares_memory(stream.values, source)
        with pytest.raises(ValueError):
            stream.values[-1, 1] = -1.
        owner = stream.values
        while isinstance(owner, np.ndarray):
            with pytest.raises(ValueError):
                owner.setflags(write=True)
            owner = owner.base
        assert isinstance(owner, bytes)

    restored.values.shape = (288,)
    assert original.values.shape == (144, 2)
    original.validate_snapshot()
    with pytest.raises(ValueError, match="array header changed"):
        restored.validate_snapshot()


@pytest.fixture
def snapshot_tree():
    from tests.mode5 import test_continuous_provider as provider

    inputs = provider.fixture()
    margin = inputs[4].margin
    inputs[4].margin = margin.to_frame(name="used").assign(maintenance=margin * .01)
    account = provider.observe(inputs)
    stream = next(value for value in account.streams if value.name == "margin")
    retention = ContinuousAccountRetention(((account.request.identity, account),))
    return dict(stream=stream, evaluation=account, retention=retention)


@pytest.mark.parametrize("owner", ("stream", "evaluation", "retention"))
@pytest.mark.parametrize("mutation", ("shape", "dtype", "strides"))
def test_header_mutation_rejected_through_each_snapshot_owner(snapshot_tree, owner, mutation):
    target = snapshot_tree[owner]
    control = deepcopy(target)
    target.validate_snapshot()
    control.validate_snapshot()
    array = snapshot_tree["stream"].values
    assert array.ndim == 2 and array.shape[1] == 2
    if mutation == "shape":
        array.shape = (array.size,)
    elif mutation == "dtype":
        array.dtype = np.int64
    else:
        array.strides = (0, 0)

    for operation in (
        lambda value: value.validate_snapshot(),
        copy,
        deepcopy,
        lambda value: pickle.dumps(value, protocol=4),
        lambda value: pickle.dumps(value, protocol=5),
    ):
        with pytest.raises(ValueError, match="array header changed"):
            operation(target)
    control.validate_snapshot()
