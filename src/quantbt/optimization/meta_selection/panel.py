"""Outcome-blind base panel and explicit required-winner union."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .common import MetaRecordError, digest, utc


@dataclass(frozen=True, slots=True)
class FrozenLabelPanel:
    task_id: str
    base_members: tuple[str, ...]
    required_members: tuple[str, ...]
    extra_union_members: tuple[str, ...]
    sealed_at: pd.Timestamp
    quota_roles: tuple[tuple[str, str], ...]
    base_cap: int = 16
    policy_id: str = "anchor5top5diversity5controls_v1"

    def __post_init__(self):
        for name in ("base_members", "required_members", "extra_union_members"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self, "quota_roles", tuple(tuple(r) for r in self.quota_roles)
        )
        object.__setattr__(self, "sealed_at", utc(self.sealed_at))
        members = self.base_members + self.extra_union_members
        if (
            self.base_cap != 16
            or not self.base_members
            or len(self.base_members) > self.base_cap
            or len(members) != len(set(members))
            or not set(self.required_members).issubset(members)
            or set(self.extra_union_members)
            != set(self.required_members) - set(self.base_members)
            or [r[1] for r in self.quota_roles] != list(self.base_members)
        ):
            raise MetaRecordError("panel membership/budget mismatch")

    @property
    def members(self):
        return self.base_members + self.extra_union_members

    @property
    def panel_id(self):
        return digest({"schema": "qms-label-panel-v1", "panel": self})


def freeze_panel(task, schema, *, required_winners=(), sealed_at, base_cap=16):
    if base_cap != 16:
        raise MetaRecordError(
            "V1 acceptance panel policy is cap16; register another policy before changing it"
        )
    sealed_at = utc(sealed_at)
    if not (task.decision_sealed_at <= sealed_at <= task.first_forward_action_at):
        raise MetaRecordError(
            "panel must seal after decision and before forward economic action"
        )
    if schema.schema_id != task.family.descriptor_schema_id:
        raise MetaRecordError("panel descriptor schema mismatch")
    candidates = {c.evaluation_id: c for c in task.candidates}
    required = tuple(
        sorted(set(required_winners) | {task.anchor_candidate_evaluation_id})
    )
    if not set(required).issubset(candidates):
        raise MetaRecordError("required winner references unknown evaluation")
    order = sorted(
        candidates,
        key=lambda key: (-candidates[key].objective, candidates[key].candidate_id, key),
    )
    members = [task.anchor_candidate_evaluation_id]
    roles = [("anchor", members[0])]
    for key in [k for k in order if k not in members][:5]:
        members.append(key)
        roles.append(("top", key))
    canonical = sorted(candidates)
    geometry = schema.parameter_geometry(candidates[k] for k in canonical)
    position = {key: i for i, key in enumerate(canonical)}
    for _ in range(5):
        remaining = [k for k in canonical if k not in members]
        if not remaining:
            break
        selected = geometry[[position[k] for k in members]]
        distance = {
            k: float(np.min(np.sum((selected - geometry[position[k]]) ** 2, axis=1)))
            for k in remaining
        }
        key = min(
            remaining, key=lambda k: (-distance[k], candidates[k].candidate_id, k)
        )
        members.append(key)
        roles.append(("diversity", key))
    remaining = [k for k in order if k not in members]
    if remaining:
        positions = np.linspace(
            0, len(remaining) - 1, min(5, len(remaining)), dtype=int
        )
        for i in positions:
            members.append(remaining[i])
            roles.append(("control", remaining[i]))
    for key in order:
        if len(members) == base_cap:
            break
        if key not in members:
            members.append(key)
            roles.append(("refill", key))
    extras = tuple(k for k in required if k not in members)
    return FrozenLabelPanel(
        task.task_id,
        tuple(members),
        required,
        extras,
        sealed_at,
        tuple(roles),
        base_cap,
    )
