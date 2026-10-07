"""Independent portable bytes and exact entry-block compatibility."""

from dataclasses import dataclass
from enum import Enum, IntEnum
from hashlib import sha256
import json
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.meta_selection import common
from tools.qms_pre05_reference import BLOCKS, entry_module


class Flag(IntEnum):
    ON = 1


class Name(str, Enum):
    ON = "on"


class Integer(int):
    pass


class String(str):
    pass


@dataclass(frozen=True)
class Record:
    when: pd.Timestamp
    payload: object


VALUES = [
    None,
    True,
    False,
    0,
    -7,
    2**80,
    "text",
    "",
    1.25,
    -0.0,
    Flag.ON,
    Name.ON,
    Integer(2),
    String("s"),
    np.int64(8),
    np.float64(0.25),
    np.bool_(True),
    (),
    [],
    {},
    MappingProxyType({"x": [1, True]}),
    Record(pd.Timestamp("2026-10-07T09:00:00+07:00"), (np.int32(2), "x")),
    {"nested": [None, {"values": (1, 0.5, False)}]},
]


@pytest.mark.parametrize("value", VALUES)
def test_entry_portable_canonical_digest_and_freeze_exact(value):
    old, _ = entry_module(common, BLOCKS[0])
    assert common.wire(value) == old["wire"](value)
    assert common.canonical(value) == old["canonical"](value)
    assert common.digest(value) == old["digest"](value)
    assert common.freeze(value) == old["freeze"](value)


def test_independent_expected_bytes_and_negative_zero():
    value = Record(
        pd.Timestamp("2026-10-07T09:00:00+07:00"), {"z": -0.0, "x": (1, False)}
    )
    expected = '{"payload":{"x":[1,false],"z":-0.0},"when":"2026-10-07T02:00:00+00:00"}'
    assert common.canonical(value) == expected
    assert common.digest(value) == sha256(expected.encode()).hexdigest()


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        np.float32("nan"),
        {1: "bad key"},
        {"bad": object()},
        pd.Timestamp("2026-10-07"),
        np.array([1, 2]),
        {1, 2},
    ],
)
def test_invalid_payload_keeps_exact_error(value):
    old, _ = entry_module(common, BLOCKS[0])
    with pytest.raises(common.MetaRecordError) as previous:
        old["canonical"](value)
    with pytest.raises(common.MetaRecordError) as current:
        common.canonical(value)
    assert str(previous.value) == str(current.value)


def test_frozen_records_cannot_be_mutated():
    value = common.freeze({"x": [1, {"y": 2}]})
    with pytest.raises(TypeError):
        value["x"][1]["y"] = 3
    assert json.loads(common.canonical(value)) == {"x": [1, {"y": 2}]}
