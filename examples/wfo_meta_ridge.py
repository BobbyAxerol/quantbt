"""Internal QMS-04 fit on original engine-produced labels; no public activation."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quantbt.optimization.meta_selection.common import wire
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from tools.qms03_history import financial_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path)
    args = parser.parse_args()
    module = None
    if args.extension:
        from tools.build_qms04_candidate import load_candidate

        module = load_candidate(args.extension)
    _, revisions, _ = financial_fixture()
    history = MetaHistory()
    for revision in revisions:
        history.append(revision)
    cutoff = max(r.revision_available_at for r in revisions) + pd.Timedelta(seconds=1)
    task = revisions[0].task
    view = history.snapshot(
        family_id=task.family.family_id,
        authorized_corpora=(task.corpus_id,),
        outcome_origins=(task.outcome_origin,),
        research_exposures=(task.research_exposure,),
        information_as_of=cutoff,
    )
    runtime = NumericRuntime(
        native_policy="require" if module else "auto", native_module=module
    )
    fitted = RidgeLearner(
        settings=RidgeSettings(min_matured_origins=2), runtime=runtime
    ).fit(
        DescriptorSchema({"window": (3, 31, 2)}),
        view,
        fit_completed_at=cutoff + pd.Timedelta(seconds=1),
    )
    print(
        "Original engine labels on synthetic OHLCV; no real-market edge or public meta activation"
    )
    print(
        json.dumps(
            wire(
                {
                    "model_id": fitted.model.model_id,
                    "snapshot_id": view.snapshot_id,
                    "matured_origins": fitted.origin_count,
                    "labels": len(view.training_rows),
                    "coefficients": fitted.model.coefficients,
                    "diagnostics": fitted.model.diagnostics,
                    "backend": runtime.metadata,
                }
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
