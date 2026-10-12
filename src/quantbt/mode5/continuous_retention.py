"""Immutable cold-path ownership of complete continuous query observations."""

from dataclasses import dataclass

from ..metrics.reporting.snapshots import SnapshotValue
from .continuous import ContinuousAccountEvaluation


@dataclass(frozen=True)
class ContinuousAccountRetention(SnapshotValue):
    entries: tuple[tuple[str, ContinuousAccountEvaluation], ...]

    def __post_init__(self):
        if (type(self.entries) is not tuple or any(type(r) is not tuple or len(r) != 2
                or not isinstance(r[0], str) or len(r[0]) != 64
                or any(c not in "0123456789abcdef" for c in r[0])
                or not isinstance(r[1], ContinuousAccountEvaluation) for r in self.entries)
                or len({r[0] for r in self.entries}) != len(self.entries)):
            raise ValueError("unique complete immutable continuous query observations required")

    def metadata(self):
        return dict(schema="quantbt.mode5.continuous_retention.v1", count=len(self.entries),
            ownership="returned_walk_forward_result_or_failure_exception",
            entries=[dict(query_id=q, evaluation_identity=e.identity) for q, e in self.entries])
