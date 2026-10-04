"""Optional original-pass metric witness ABI; no simulation or metric formulas."""

from types import MappingProxyType

import numpy as np


def extract_prepared_metric_support_v1(matrix, row_count):
    method = getattr(matrix, "qms_metric_support_columns_v1", None)
    if method is None:
        raise RuntimeError(
            "META_METRIC_SUPPORT_MISSING: native score witness capability required"
        )
    names = (
        "sample_count",
        "sample_variance",
        "initial_mark_equity",
        "liquidated",
        "contract_version",
        "annualization_factor",
    )
    dtypes = (
        np.dtype("uint64"),
        np.dtype("float64"),
        np.dtype("float64"),
        np.dtype("bool"),
        np.dtype("uint16"),
        np.dtype("float64"),
    )
    values = method()
    if not isinstance(values, tuple) or len(values) != len(names):
        raise RuntimeError(
            "META_METRIC_SUPPORT_INVALID: fixed witness columns required"
        )
    support = {}
    for name, value, dtype in zip(names, values, dtypes, strict=True):
        array = np.asarray(value)
        if array.shape != (row_count,) or array.dtype != dtype:
            raise RuntimeError("META_METRIC_SUPPORT_INVALID: witness row count/dtype")
        array.flags.writeable = False
        support[name] = array
    return MappingProxyType(support)
