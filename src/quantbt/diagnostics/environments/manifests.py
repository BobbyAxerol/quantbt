"""Exact anchor provenance and matched candidate readiness, never price splicing."""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from quantbt.diagnostics.access import DEVELOPMENT_ROLES, VALIDATION_ROLES
from quantbt.diagnostics.evidence import FrozenBuffer
from quantbt.diagnostics.identity import digest


def utc_ns(value):
    time = pd.Timestamp(value)
    if pd.isna(time):
        raise ValueError("timestamp required")
    # Reviewed bundle timestamps are naive UTC. No local timezone inference.
    return int((time.tz_localize("UTC") if time.tz is None else time.tz_convert("UTC")).value)


def calendar(values):
    array = np.asarray(values)
    if (array.dtype.kind not in "iu" or array.ndim != 1 or not len(array)
            or np.any(array[1:] <= array[:-1]) or np.any(array > np.iinfo(np.int64).max)
            or np.any(array == np.iinfo(np.int64).min)):
        raise ValueError("strictly ordered nonempty exact calendar required")
    return array.astype(np.int64, copy=False)


@dataclass(frozen=True)
class AnchorManifest:
    manifest_id: str
    source_id: str
    source_pointer: str
    label: str
    family: str
    role: str
    preload_start_ns: int
    score_start_ns: int
    end_ns: int
    end_policy: str
    lifecycle_id: str
    evaluation_mode: str

    def __post_init__(self):
        if (any(not isinstance(v, str) or not v for v in (self.manifest_id, self.source_id,
                self.source_pointer, self.label, self.family, self.lifecycle_id))
                or self.role not in DEVELOPMENT_ROLES | VALIDATION_ROLES
                or any(type(v) is not int for v in (self.preload_start_ns, self.score_start_ns, self.end_ns))
                or not self.preload_start_ns <= self.score_start_ns < self.end_ns
                or self.end_policy not in {"inclusive", "exclusive", "UNVERIFIED"}
                or self.evaluation_mode not in {"CONTINUOUS_PATH_ATTRIBUTION", "CONTIGUOUS_RESET_EPISODES"}):
            raise ValueError("exact environment/financial/role manifest required")

    @classmethod
    def from_historical(cls, name, window, *, source_id, pointer, lifecycle_id,
                        reviewed=False, end_policy="UNVERIFIED"):
        return cls(name, source_id, pointer, window.get("name") or name, "historical_anchor",
            "EXPLORATORY_REVIEWED_2024" if reviewed else "DEVELOPMENT_REVIEWED",
            utc_ns(window["start"]), utc_ns(window["sim_start"]), utc_ns(window["end"]),
            end_policy, lifecycle_id, "CONTIGUOUS_RESET_EPISODES")

    @property
    def identity(self):
        return digest(asdict(self))

    def membership(self, times_ns):
        times = calendar(times_ns)
        if self.end_policy == "UNVERIFIED":
            raise ValueError("historical right boundary unverified; cannot invent a scored membership")
        end = times <= self.end_ns if self.end_policy == "inclusive" else times < self.end_ns
        return FrozenBuffer.from_array("membership", (times >= self.score_start_ns) & end)


class EnvironmentRegistry:
    """Append-only immutable manifests; revisions use a new explicit ID."""

    def __init__(self):
        self._entries = {}

    def register(self, manifest):
        if not isinstance(manifest, AnchorManifest):
            raise TypeError("typed anchor manifest required")
        old = self._entries.get(manifest.manifest_id)
        if old is not None and old != manifest:
            raise ValueError("manifest ID already sealed; create explicit revision")
        self._entries[manifest.manifest_id] = manifest
        return manifest.identity

    def records(self):
        return tuple(asdict(self._entries[k]) for k in sorted(self._entries))


def match_calendar(times_ns, *, score_start_ns, end_ns, candidates):
    """All candidates share one requested score mask; missing preload stays visible.

    Each candidate records required preload and its first actually ready bar.
    No candidate-specific shorter window is silently scored for convenience.
    """
    times = calendar(times_ns)
    if (type(score_start_ns) is not int or type(end_ns) is not int
            or not score_start_ns < end_ns or not candidates):
        raise ValueError("explicit scored interval and candidate witnesses required")
    mask = (times >= score_start_ns) & (times < end_ns)
    if not mask.any():
        raise ValueError("no observed scored bars")
    rows = []
    for name, row in sorted(candidates.items()):
        if set(row) != {"required_preload_ns", "ready_ns"} or any(type(v) is not int for v in row.values()):
            raise ValueError("exact candidate readiness witness required")
        if row["required_preload_ns"] > score_start_ns or row["ready_ns"] < row["required_preload_ns"]:
            raise ValueError("preload cannot start after score")
        ready = row["required_preload_ns"] >= int(times[0]) and row["ready_ns"] <= int(times[mask][0])
        rows.append(dict(candidate_id=name, **row, status="READY" if ready else "NOT_READY"))
    return dict(status="READY" if all(r["status"] == "READY" for r in rows) else "NOT_READY",
        nominal_start_ns=score_start_ns, nominal_end_ns=end_ns, actual_first_ns=int(times[mask][0]),
        actual_last_ns=int(times[mask][-1]), scored_bars=int(mask.sum()),
        matched_calendar_id=digest(times[mask].tolist()), candidates=rows,
        policy="no per-candidate truncation; reject financial scoring until every candidate is ready")
