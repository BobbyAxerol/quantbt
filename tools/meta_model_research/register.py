"""ML-01 create-once registration. This command does not fit any learner."""

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import argparse
import importlib.metadata
import os

from .admission import PUBLIC, ROOT, pin, read, save_new, verify_freeze
from .protocol import StudyProtocol


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--owner-approval", required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC / "ml01_registration.json")
    args = parser.parse_args()
    inventory = read(args.inventory)
    if inventory["new_fits"] != 0 or inventory["new_financial_calls"] != 0:
        raise ValueError("registration must precede new model outcomes")
    protocol = StudyProtocol()
    if inventory["cpu_seconds"] > protocol.max_admission_cpu_seconds:
        raise ValueError("admission CPU budget exceeded")
    space = os.statvfs(ROOT)
    if space.f_bavail * space.f_frsize < protocol.min_disk_free_bytes + protocol.max_incremental_bytes:
        raise ValueError("projected disk reserve unavailable")
    payload = dict(
        schema="quantbt.m4ml01.registration.v1", created_at=datetime.now(timezone.utc).isoformat(),
        timezone="Asia/Saigon", owner_approval=args.owner_approval,
        protocol=asdict(protocol), protocol_id=protocol.protocol_id,
        baseline=verify_freeze(), inventory=pin(args.inventory),
        source_pins=[pin(Path(__file__).with_name(n)) for n in
                     ("__init__.py", "admission.py", "protocol.py", "register.py")],
        runtime_dependencies={name: importlib.metadata.version(name)
                              for name in ("numpy", "scipy", "pandas", "arch", "threadpoolctl")},
        corpus_groups={g: dict(stratum=c["stratum"], family_id=c["family_id"],
                             schema_id=c["schema_id"], folds=c["folds"], d=c["d"])
                       for g, c in inventory["corpora"].items()},
        calibration_frontier="actual earliest evaluation task.data_cutoff; strict label/revision availability",
        base_sensitivity="base-only is a derived sensitivity view; original union revisions remain immutable",
        pilot="first actual mature, fold40 and fold56 for each of four groups; 12 total fits",
        budgets=dict(max_fits=4000, max_cpu_seconds=3600, new_optimization=0, new_finance=0,
                     incremental_bytes=protocol.max_incremental_bytes),
        scientific_claim="bounded reviewed-exploratory procedure-transfer study",
        shortlist_rule="loss reduction >=2%; family95% upper delta-loss<=0; lower deltaQ/deltaR>=-0.05; "
                       ">=12 paired origins/365 days/group; full intact calendar for numerical CI",
        uncertainty="shared 3-month calendar blocks;16384 draws;seed731;Bonferroni over 2 policies x (loss,Q,R); "
                    "conditional fixed-label-panel loss, not independent full-pipeline power",
        new_fits=0, new_financial_calls=0, model_activation=False, release=False,
        free_bytes=space.f_bavail * space.f_frsize, free_inodes=space.f_favail,
    )
    print(save_new(args.output, payload))


if __name__ == "__main__":
    main()
