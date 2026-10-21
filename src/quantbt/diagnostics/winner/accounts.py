"""Cold profiles of the selected original continuous Mode5 account only."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import math

import numpy as np
import pandas as pd

from quantbt.mode5.dossier.records import Record, require_text
from quantbt.mode5.evaluation import array_identity
from quantbt.mode5.statistics.moments import moments

from ..access import AccessPolicy, AccessWitness
from ..account_profile import account_profile
from ..environments.attribution import DAY_NS, daily_path
from ..evidence import ExecutionEvidence, FrozenBuffer, MissingInputs
from ..identity import digest
from ..research_contracts import DiagnosticAccount

__all__ = ["WinnerStateView", "profile_selected_account"]

_STREAMS = ("equity", "positions", "fees", "funding", "margin")
_MODE = "CONTINUOUS_PATH_ATTRIBUTION"
_CLOSED_UNIT = "engine_closed_records_not_closed_actions_or_inferred_campaigns"


@dataclass(frozen=True)
class WinnerStateView:
    """One supplied daily state family, including its own availability rights."""

    name: str
    labels: FrozenBuffer
    witness: AccessWitness
    source_ref: str
    label_names: tuple[tuple[int, str], ...]
    purpose: str = "asof_calibration_descriptive"

    def __post_init__(self):
        require_text(self.name)
        require_text(self.source_ref)
        if not isinstance(self.labels, FrozenBuffer) or not isinstance(self.witness, AccessWitness):
            raise TypeError("immutable daily labels and their own AccessWitness required")
        labels = self.labels.array()
        if labels.ndim != 1 or labels.dtype.kind not in "iu" or np.any(labels < -1):
            raise ValueError("one exact integer state per observed UTC day; -1 means unknown")
        if (type(self.label_names) is not tuple
                or any(type(pair) is not tuple or len(pair) != 2 for pair in self.label_names)):
            raise ValueError("immutable distinct state label_names required")
        if (any(type(k) is not int or k < -1 or not isinstance(v, str) or not v.strip()
                for k, v in self.label_names)
                or len(dict(self.label_names)) != len(self.label_names)):
            raise ValueError("immutable distinct state label_names required")
        if self.purpose not in {"decision_vintage", "asof_calibration_descriptive"}:
            raise ValueError("explicit existing label purpose required; no new fits")


def _retained_inputs(result, observation):
    """Check original shapes before adapting singleton DataFrame columns."""
    equity = getattr(result, "equity", None)
    if not isinstance(equity, (pd.Series, pd.DataFrame)):
        raise MissingInputs(("original indexed equity",))
    index = equity.index
    if (not isinstance(index, pd.DatetimeIndex) or index.tz is None or str(index.tz) != "UTC"
            or index.hasnans or not index.is_unique or not index.is_monotonic_increasing or not len(index)):
        raise ValueError("original complete timezone-aware UTC equity calendar required")
    times = index.as_unit("ns").asi8
    start, stop = observation["start_ns"], observation["stop_ns"]
    step, remainder = divmod(stop - start, len(times))
    if (remainder or step <= 0 or DAY_NS % step or int(times[0]) != start
            or int(times[-1]) + step != stop or np.any(np.diff(times) != step)):
        raise ValueError("equity calendar differs from original whole_observation start_ns/stop_ns")
    arrays = {}
    for name in _STREAMS:
        item = getattr(result, name, None)
        if item is None:
            if name in observation["finance"]:
                raise MissingInputs((name,))
            continue
        if name not in observation["finance"]:
            raise ValueError("financial stream lacks original retained hash: " + name)
        if isinstance(item, (pd.Series, pd.DataFrame)) and not item.index.equals(index):
            raise ValueError("financial stream calendar/timezone differs from equity: " + name)
        array = np.asarray(item)
        if (array.dtype.kind not in "biuf" or array.ndim not in {1, 2}
                or len(array) != len(times) or not np.isfinite(array).all()
                or array.ndim == 2 and array.shape[1] == 0):
            raise ValueError("finite original financial stream aligned to equity required: " + name)
        if name in {"equity", "fees", "funding"} and array.ndim == 2 and array.shape[1] != 1:
            raise ValueError("unsupported multi-column account stream: " + name)
        if array_identity(array) != observation["finance"][name]:
            raise ValueError("original retained finance hash mismatch: " + name)
        arrays[name] = array
    capital = getattr(result, "initial_capital", None)
    if (isinstance(capital, (bool, np.bool_)) or not isinstance(capital, (int, float, np.number))
            or not math.isfinite(capital) or capital != observation["initial_capital"]
            or float(arrays["equity"].reshape(-1)[-1]) != observation["final_equity"]):
        raise ValueError("original initial/final capital mismatch")
    terminal = getattr(result, "final_equity", None)
    if terminal is not None and terminal != observation["final_equity"]:
        raise ValueError("original result final equity mismatch")
    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        raise TypeError("original current result metadata required")
    if metadata.get("account_policy") in {"reset_flat", "independent_reset_flat_v1", "CONTIGUOUS_RESET_EPISODES"}:
        raise ValueError("reset account cannot supply original continuous attribution")
    for field, key in (("execution_backend", "backend"), ("execution_contract", "execution_contract")):
        if field in observation and observation[field] != metadata.get(key):
            raise ValueError("original execution backend/clock mismatch: " + field)
    return arrays, times, step


def _fills(metadata):
    # This is the existing native-event counter, not len(trades) or transitions.
    counters = metadata.get("lifecycle_counters")
    if metadata.get("backend") == "native_event" and isinstance(counters, dict) and "fill_count" in counters:
        value = counters["fill_count"]
        if type(value) is not int or value < 0:
            raise ValueError("invalid authoritative lifecycle_counters.fill_count")
        return dict(status="RECORDED", value=value, unit="executed_fills",
            metadata_field="lifecycle_counters.fill_count", reason=None)
    return dict(status="NOT_SUPPLIED", value=None, unit="executed_fills",
        reason="No authoritative current-result fill counter supplied; close-mark transitions are not fills.")


def _state_family(view, account, path, access, start, stop):
    access.require(view.witness)
    if view.witness.start_ns > start or view.witness.end_ns < stop:
        raise PermissionError("state label witness must cover the full original account scope")
    labels = view.labels.array()
    if labels.shape != path.times.shape:
        raise ValueError("state labels must align one per original observed UTC day")
    labelled = replace(account, labels=view.labels, label_witness=view.witness,
        label_source_ref=view.source_ref, label_names=view.label_names, label_purpose=view.purpose)
    profile = account_profile(labelled, access)
    returns, valid = path.returns.array(), path.return_valid.array()
    for row in profile["groups"]:
        mask = labels == row["state"]
        reason = "Unknown state labels (-1)." if row["state"] == -1 else (
            "Nonpositive account base; no invalid days dropped." if not valid[mask].all() else None)
        estimate = moments(returns[mask], backend="python") if reason is None else None
        row["conditional_sharpe"] = dict(value=estimate.sharpe_period if estimate is not None else None,
            status="OBSERVED" if estimate is not None and estimate.status == "VALID" else "MISSING",
            reason=reason if estimate is None else estimate.reason,
            estimator_status=estimate.status if estimate is not None else "UNAVAILABLE",
            sample_count=int(mask.sum()), unit="daily_return_ratio", annualized=False)
        row["annualized_sharpe"] = None
    return dict(name=view.name, source_ref=view.source_ref, witness=asdict(view.witness), purpose=view.purpose,
        label_identity=digest(dict(name=view.labels.name, dtype=view.labels.dtype, shape=view.labels.shape,
            sha256=sha256(view.labels.data).hexdigest())), label_names=view.label_names,
        unknown_states=profile["unknown_states"], groups=profile["groups"], attribution=profile["attribution"],
        independent_sample_count=None)


def profile_selected_account(result, observation, *, access, witness, source_ref, state_views=()) -> dict:
    """Describe original marks without replay, fitting, selection or raw-path output.

    ``observation`` must be the selected original continuous ``whole_observation``
    from a validated DecisionReport. Its validation and winner binding belong to
    the caller. Only complete timezone-aware UTC paths are supported here.
    The returned ordinary metadata dictionary is frozen by the report owner.

    Stable payload: ``activity`` is the existing account profile plus named
    support/cost fields; ``states`` carries status/reason and a ``families``
    list. Each family contains ``groups`` and original monetary ``attribution``.
    The helper's successful status is ``OBSERVED``; the parent owns any report
    qualification status. No paths, daily return arrays or label buffers escape.
    """
    if not isinstance(access, AccessPolicy) or not isinstance(witness, AccessWitness):
        raise TypeError("typed current access and full-development witness required")
    require_text(source_ref)
    access.require(witness)
    if access.purpose != "diagnostic":
        raise PermissionError("winner profiles require full-development diagnostic access, not selection/validation rights")
    if not isinstance(observation, Mapping):
        raise TypeError("original continuous whole_observation mapping required")
    original = Record.of(dict(observation))
    row = original.data
    if row.get("environment_id") != "whole_path" or row.get("account_policy") != _MODE:
        raise ValueError("original continuous whole_observation required; requests/annual/reset views are unsupported")
    start, stop = row.get("start_ns"), row.get("stop_ns")
    if (type(start) is not int or type(stop) is not int or start >= stop or start % DAY_NS or stop % DAY_NS):
        raise ValueError("original complete UTC-day start_ns/stop_ns required")
    if witness.start_ns > start or witness.end_ns < stop:
        raise PermissionError("full-development witness must cover original start_ns/stop_ns")
    finance = row.get("finance")
    if (not isinstance(finance, dict) or not {"equity", "positions"} <= finance.keys()
            or not finance.keys() <= set(_STREAMS)
            or any(not isinstance(v, str) or len(v) != 64 for v in finance.values())):
        raise ValueError("original retained equity/positions and all finance hashes required")
    for name in ("initial_capital", "final_equity"):
        value = row.get(name)
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError("finite original capital required: " + name)
    if row["initial_capital"] <= 0:
        raise ValueError("positive original scope-entry capital required")
    require_text(row.get("metric_contract"))
    if type(row.get("closed_records")) is not int or row["closed_records"] < 0 or row.get("closed_record_unit") != _CLOSED_UNIT:
        raise ValueError("original engine closed record count/unit required")
    if (type(state_views) is not tuple or any(not isinstance(v, WinnerStateView) for v in state_views)
            or len({v.name for v in state_views}) != len(state_views)):
        raise ValueError("distinct immutable WinnerStateView tuple required")
    arrays, times, step = _retained_inputs(result, row)
    shapes = {name: values.shape for name, values in arrays.items()}
    adapted = {name: values[:, 0] if name in {"equity", "fees", "funding"} and values.ndim == 2 else values
               for name, values in arrays.items()}
    account_witness = replace(witness, start_ns=start, end_ns=stop)
    evidence = ExecutionEvidence.from_arrays(original.identity, account_witness, dict(adapted, timestamps=times),
        source_ref=source_ref, backend="retained_original_result")
    frozen = evidence.arrays()
    for name in arrays:
        if array_identity(frozen[name].reshape(shapes[name])) != finance[name]:
            raise ValueError("finance changed while taking immutable snapshot: " + name)
    account = DiagnosticAccount(original.identity, original.identity, evidence, row["initial_capital"], "account_currency")
    activity = account_profile(account, access)
    activity.update(exposure_unit="occupied_close_marks", engine_closed_records=row["closed_records"],
        engine_closed_record_unit=row["closed_record_unit"], fills=_fills(result.metadata),
        fee_status="OBSERVED" if "fees" in finance else "NOT_SUPPLIED",
        funding_status="OBSERVED" if "funding" in finance else "NOT_SUPPLIED")
    families = []
    if state_views:
        path = daily_path(evidence, access, initial_equity=account.initial_equity)
        families = [_state_family(view, account, path, access, start, stop) for view in state_views]
    payload = dict(status="OBSERVED", view="full_development", decision_use="NOT_BACKDATABLE",
        source_ref=source_ref, witness=asdict(witness), account_witness=asdict(account_witness),
        observation_identity=original.identity,
        metric_contract=row["metric_contract"], finance=dict(finance), execution_content_id=evidence.content_id,
        calendar=dict(start_ns=start, stop_ns=stop, step_ns=step, bars=len(times), timezone="UTC"),
        activity=activity, states=dict(status="OBSERVED" if families else "NOT_SUPPLIED", families=families,
            reason=None if families else "No source-bound regime/state evidence supplied; calendar years are not regimes.",
            independent_sample_count=None, aggregation="Separate overlapping dependent views; never sum across state families."))
    # Re-read the live result, not just the snapshot: a reducer must not mutate it.
    _, final_times, final_step = _retained_inputs(result, row)
    if (final_step != step or not np.array_equal(final_times, frozen["timestamps"])
            or Record.of(dict(observation)) != original):
        raise ValueError("original observation/calendar changed during winner profiling")
    return payload
