"""Read-only reporting snapshots, with explicit scope and observation coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

import numpy as np

from ..report_contracts import ReportingContractV1, ReportingCoverageV1
from .snapshots import SnapshotValue, immutable_storage


def frozen_array(values, dtype, *, integer=False):
    original = np.asarray(values)
    if original.ndim != 1:
        raise ValueError("one-dimensional observations required")
    if integer and original.size and original.dtype.kind not in "iu":
        raise ValueError("UTC nanoseconds require integers, not rounded timestamps")
    if integer and original.size and original.dtype.kind == "u" and int(original.max()) > np.iinfo(np.int64).max:
        raise ValueError("UTC nanoseconds exceed signed int64 range")
    array = np.ascontiguousarray(original, dtype=dtype)
    if integer and np.any(array == np.iinfo(np.int64).min):
        raise ValueError("missing NaT timestamp is not a UTC nanosecond observation")
    if dtype == np.float64 and not np.isfinite(array).all():
        raise ValueError("finite observations required; invalid rows cannot be dropped")
    return immutable_storage(array)


def identity(metadata, *arrays):
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, allow_nan=False,
                                       separators=(",", ":")).encode("utf-8"))
    for array in arrays:
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(str(array.shape).encode("ascii"))
        digest.update(memoryview(array))
    return digest.hexdigest()


def validate_account_path(times, equity):
    if not len(times) or len(times) != len(equity):
        raise ValueError("nonempty aligned account path required")
    if np.any(times[1:] <= times[:-1]):
        raise ValueError("strictly ordered account times required")


def validate_account_scope(times, contract):
    if contract.unit != "account_period":
        raise ValueError("account reducer requires account_period contract")
    if times[0] < contract.baseline_time_ns or times[-1] != contract.scope_end_ns:
        raise ValueError("path must end at declared scope end and start at/after baseline")
    bounds = np.iinfo(np.int64)
    if not bounds.min <= contract.baseline_time_ns <= bounds.max or contract.scope_end_ns - contract.baseline_time_ns > bounds.max:
        raise ValueError("observation duration exceeds signed int64 nanoseconds")


def _return_headers(end_times_ns, partial_mask, sampling, witness):
    times = frozen_array(end_times_ns, np.int64, integer=True)
    original = np.asarray(partial_mask)
    if original.size and original.dtype.kind != "b":
        raise ValueError("explicit boolean partial-period mask required")
    partial = frozen_array(original, np.bool_)
    if len(times) != len(partial):
        raise ValueError("aligned return values/times/partial mask required")
    if len(times) > 1 and np.any(times[1:] <= times[:-1]):
        raise ValueError("strictly ordered return times required")
    if sampling not in {"observed_bar", "observed_daily_utc", "explicit_period_returns"}:
        raise ValueError("unknown return sampling")
    if not witness or not isinstance(witness, str):
        raise ValueError("producer must disclose the return/partial-period witness")
    return times, partial


@dataclass(frozen=True, kw_only=True)
class ReturnObservations(SnapshotValue):
    values: np.ndarray
    end_times_ns: np.ndarray
    partial_mask: np.ndarray
    sampling: str
    witness: str

    def __post_init__(self):
        values = frozen_array(self.values, np.float64)
        times, partial = _return_headers(self.end_times_ns, self.partial_mask, self.sampling, self.witness)
        if len(values) != len(times) or len(values) != len(partial):
            raise ValueError("aligned return values/times/partial mask required")
        for name, array in (("values", values), ("end_times_ns", times), ("partial_mask", partial)):
            object.__setattr__(self, name, array)
        self._seal_arrays()


@dataclass(frozen=True, kw_only=True)
class UndefinedPeriodReturns(SnapshotValue):
    """Observed period boundaries without invented returns after bankruptcy."""

    end_times_ns: np.ndarray
    partial_mask: np.ndarray
    sampling: str
    witness: str
    first_undefined_time_ns: int

    @property
    def reason(self):
        return "period return after nonpositive equity is undefined"

    def __post_init__(self):
        times, partial = _return_headers(self.end_times_ns, self.partial_mask, self.sampling, self.witness)
        if type(self.first_undefined_time_ns) is not int or self.first_undefined_time_ns not in times:
            raise ValueError("undefined period must identify an observed boundary")
        object.__setattr__(self, "end_times_ns", times)
        object.__setattr__(self, "partial_mask", partial)
        self._seal_arrays()


class UndefinedPeriodReturn(ValueError):
    def __init__(self, observations):
        super().__init__(observations.reason)
        self.observations = observations


@dataclass(frozen=True, kw_only=True)
class AccountObservations(SnapshotValue):
    times_ns: np.ndarray
    equity: np.ndarray
    coverage: ReportingCoverageV1
    returns: ReturnObservations | UndefinedPeriodReturns | None = None
    identity: str = field(init=False)

    def __post_init__(self):
        times = frozen_array(self.times_ns, np.int64, integer=True)
        equity = frozen_array(self.equity, np.float64)
        validate_account_path(times, equity)
        if not isinstance(self.coverage, ReportingCoverageV1):
            raise ValueError("typed producer coverage required")
        arrays = [times, equity]
        metadata = dict(coverage=self.coverage.__dict__)
        if self.returns is not None:
            if not isinstance(self.returns, (ReturnObservations, UndefinedPeriodReturns)):
                raise ValueError("typed return observations required")
            self.returns.validate_snapshot()
            arrays.extend((self.returns.end_times_ns, self.returns.partial_mask))
            if isinstance(self.returns, ReturnObservations):
                arrays.insert(2, self.returns.values)
            else:
                metadata.update(undefined_period_reason=self.returns.reason,
                                first_undefined_time_ns=self.returns.first_undefined_time_ns)
            metadata.update(sampling=self.returns.sampling, witness=self.returns.witness)
        object.__setattr__(self, "times_ns", times)
        object.__setattr__(self, "equity", equity)
        object.__setattr__(self, "identity", identity(metadata, *arrays))
        self._seal_arrays()

    def validate_contract(self, contract: ReportingContractV1):
        self.validate_snapshot()
        validate_account_scope(self.times_ns, contract)
        if self.returns is not None:
            if self.returns.sampling != contract.sampling:
                raise ValueError("return sampling does not match reporting contract")
            times = self.returns.end_times_ns
            if len(times) and (times[0] < contract.baseline_time_ns or times[-1] > contract.scope_end_ns):
                raise ValueError("return observations outside declared scope")

    def with_derived_returns(self, contract, *, partial_mask, witness):
        """Observe bars or UTC day closes; never synthesize a missing-day mark."""
        self.validate_contract(contract)
        returns = derived_returns(self.times_ns, self.equity, contract,
                                  partial_mask=partial_mask, witness=witness)
        return AccountObservations(times_ns=self.times_ns, equity=self.equity,
                                   coverage=self.coverage, returns=returns)


def derived_returns(times, equity, contract, *, partial_mask, witness):
    """Derive the same observed periods without all-bar fancy-index copies."""
    if contract.sampling == "explicit_period_returns":
        raise ValueError("explicit return sampling requires producer-supplied returns")
    marks, ends = equity, times
    if contract.sampling == "observed_daily_utc":
        days = times // 86_400_000_000_000
        selected = np.r_[days[1:] != days[:-1], True]
        marks, ends = equity[selected], times[selected]
    previous = np.r_[contract.baseline_equity, marks[:-1]]
    invalid = previous <= 0
    if np.any(invalid):
        ends, partial = _return_headers(ends, partial_mask, contract.sampling, witness)
        raise UndefinedPeriodReturn(UndefinedPeriodReturns(end_times_ns=ends, partial_mask=partial,
            sampling=contract.sampling, witness=witness,
            first_undefined_time_ns=int(ends[np.argmax(invalid)])))
    return ReturnObservations(values=marks / previous - 1, end_times_ns=ends,
        partial_mask=partial_mask, sampling=contract.sampling, witness=witness)
