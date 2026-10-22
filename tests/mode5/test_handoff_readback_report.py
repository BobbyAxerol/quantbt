"""Shared-renderer retained-value review; no financial owner invoked."""
from pathlib import Path

import pytest

from tools.mode5_research.handoff_readback import readback
from tools.mode5_research.handoff_readback_report import render
from tests.mode5.test_handoff_readback import Stored


def test_retained_review_preserves_source_masks_and_action_boundaries(tmp_path):
    Stored(tmp_path)
    record = readback(Path(tmp_path))
    private = render(record, private=True)
    for title in ("Decision Summary", "Alpha Behavior", "Recipe Comparison", "Run Configuration", "Post-Run Qualification"):
        assert "## " + title in private
    assert "NOT_RUN_ON_PRIVATE_ALPHAS" in private
    assert "R = Q - delta_IS" in private
    assert "Basin status" in private
    assert "Raw winner" in private
    for alpha in record.data["alphas"]:
        assert alpha in private
    assert "A-HASH" not in render(record)
    with pytest.raises(ValueError, match="boolean"):
        render(record, private="yes")
