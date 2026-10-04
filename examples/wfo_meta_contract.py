"""Complete QMS software cases on synthetic data, never economic/live evidence.

Run: python -m examples.wfo_meta_contract --case history
"""

from __future__ import annotations

import argparse
import json

from examples.wfo_meta_selection import run_demo
from examples.wfo_samplers import run as sampler_demo
from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.persistence import (
    dumps_revision,
    loads_revision,
)


def run_case(case):
    if case == "unsupported":
        try:
            QuantBTEndpoint.walk_forward(
                strategy_class=lambda *a: None,
                optimization_mode="mode_1_decay",
                optimization_schedule="per_fold_decay",
                optuna_trials=6,
                optimization_config={"meta_selection": {"mode": "active"}},
            )
        except ValueError as error:
            if "META_METHODOLOGY_UNSUPPORTED" not in str(error):
                raise
            return {"case": case, "error": str(error), "evaluation_started": False}
        raise AssertionError("unsupported methodology accepted")
    if case == "sampler":
        _endpoint, result = sampler_demo("sobol")
        return {
            "case": case,
            "sampler": "sobol",
            "meta_enabled": False,
            "studies": len(result.metadata["walk_forward"]["sampler_studies"]),
        }
    _endpoint, result, context = run_demo(
        "off" if case == "off" else "active", min_origins=1
    )
    if case == "off":
        assert "meta_selection" not in result.metadata["walk_forward"]
        return {
            "case": case,
            "meta_enabled": False,
            "final_equity": float(result.equity.iloc[-1]),
        }
    meta = result.metadata["walk_forward"]["meta_selection"]
    snapshot = context.history.snapshot(
        family_id=meta["tasks"][-1].family.family_id,
        authorized_corpora=context.authorized_corpora,
        outcome_origins=context.outcome_origins,
        research_exposures=context.research_exposures,
        information_as_of=meta["tasks"][-1].forward_end,
    )
    restored = MetaHistory()
    for revision in snapshot.revisions:
        # Demo-only explicit review: a real host must supply its own reviewed
        # IDs/complete original-output witnesses, not trust self-hashed JSON.
        observations = [
            *(c.observation for c in revision.task.candidates),
            *(o.observation for o in revision.outcomes),
        ]
        copied = loads_revision(
            dumps_revision(revision),
            verified_output_witnesses={o.output_ref: digest(o) for o in observations},
            reviewed_revision_ids=(revision.revision_id,),
        )
        assert copied.revision_id == revision.revision_id
        restored.append(copied)
    again = restored.snapshot(
        family_id=snapshot.family_id,
        authorized_corpora=snapshot.authorized_corpora,
        outcome_origins=snapshot.outcome_origins,
        research_exposures=snapshot.research_exposures,
        information_as_of=snapshot.information_as_of,
    )
    assert again.snapshot_id == snapshot.snapshot_id
    return {
        "case": case,
        "snapshot_id": snapshot.snapshot_id,
        "reviewed_origins": again.origin_count,
        "selected_params": meta["records"][-1]["selected_params"],
        "support_override": 1,
        "product_default_origins": 12,
        "current_oos_used": False,
        "live_trading_authorized": False,
        "scope": "synthetic engineering and reviewed JSON replay, not market edge",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", choices=("off", "sampler", "history", "unsupported"), default="off"
    )
    print(json.dumps(wire(run_case(parser.parse_args().case)), indent=2))
