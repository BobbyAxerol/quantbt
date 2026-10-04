"""Q7: lossless DSA, exact identity/lifetime and chronological decisions."""

from dataclasses import fields, replace

import numpy as np
import pytest

from quantbt.optimization.meta_selection.common import canonical, digest
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from tests.meta_selection.test_qms03_history import (
    make_task,
    revision_for,
    snapshot,
    stamp,
)


def test_q7_t03_derived_values_do_not_change_portable_bytes_or_replacements():
    task, schema = make_task(n=6)
    revision = revision_for(task, schema)
    history = MetaHistory()
    history.append(revision)
    view = snapshot(history, task, stamp("2022-12-31"))
    fitted = RidgeLearner(
        settings=RidgeSettings(min_matured_origins=1),
        runtime=NumericRuntime(native_policy="reference"),
    ).fit(schema, view, fit_completed_at=stamp("2023-01-01"))
    for record, properties in (
        (task.family, ("family_id",)),
        (task, ("task_id",)),
        (revision.panel, ("panel_id",)),
        (revision, ("content_digest", "training_rows")),
        (view, ("snapshot_id", "origin_count", "training_rows")),
        (fitted.model, ("model_id",)),
    ):
        before = canonical(record)
        for name in properties:
            assert getattr(record, name) is getattr(record, name)
        assert canonical(record) == before
        assert "_derived" not in {f.name for f in fields(record)}
        clone = replace(record)
        assert not hasattr(clone, "_derived")
        assert canonical(clone) == before
        for name in properties:
            assert getattr(clone, name) == getattr(record, name)
    assert revision.content_digest == digest(
        {"schema": "qms-revision-v1", "record": revision}
    )
    changed = replace(view, information_as_of=stamp("2023-12-31"))
    assert changed.snapshot_id != view.snapshot_id


def test_q7_t04_object_owned_memo_has_no_global_retention():
    task, schema = make_task()
    revision = revision_for(task, schema)
    for _ in range(30):
        assert len(revision.training_rows) == 3
        assert revision.revision_id
    assert set(revision._derived) == {"content_digest", "training_rows"}
    assert all(np.isfinite(row.origin_weight) for row in revision.training_rows)
    with pytest.raises((AttributeError, TypeError)):
        revision.outcomes = ()
