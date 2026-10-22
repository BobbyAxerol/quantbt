"""Sequential fresh-process review lanes; no publishing, retries or budget edits."""

from pathlib import Path
import argparse
from hashlib import sha256
import json
import os
import subprocess
import sys
from time import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    worker = Path(__file__).with_name("qms_real_review.py")
    root = worker.parents[1] / "data/local/qms-real-review"
    if args.launch:
        with (root / "remaining.log").open("a") as log:
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve())],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        (root / "remaining.pid").write_text(str(child.pid) + "\n")
        print(f"Review queue launched: pid={child.pid}; log={root / 'remaining.log'}")
        return
    registration = json.loads((root / "registration.json").read_text())
    registration_id = sha256(json.dumps(registration, sort_keys=True).encode()).hexdigest()

    def progress(status, case=None):
        (root / "remaining_progress.json").write_text(json.dumps(
            dict(pid=os.getpid(), status=status, case=case, updated=time()), indent=2,
        ) + "\n")

    cases = [
        ("meta", "shadow", "tpe_legacy"),
        ("meta", "active_reference", "tpe_legacy"),
        ("sampler", "off", "tpe_multivariate_group"),
        ("sampler", "off", "cmaes"),
        ("sampler", "off", "sobol"),
    ]
    for kind, arm, recipe in cases:
        evidence = root / f"{kind}_{arm}_{recipe}.json"
        if evidence.exists():
            completed = json.loads(evidence.read_text())
            if completed["registration_digest"] != registration_id:
                raise ValueError("existing lane has a different registration; refusing overwrite")
            print(f"PRESERVE completed {kind}/{arm}/{recipe}", flush=True)
            continue
        progress("RUNNING", f"{kind}/{arm}/{recipe}")
        print(f"START {kind}/{arm}/{recipe}", flush=True)
        try:
            subprocess.run(
                [sys.executable, str(worker), "worker", "--kind", kind,
                 "--arm", arm, "--recipe", recipe], check=True,
            )
        except Exception:
            progress("FAILED", f"{kind}/{arm}/{recipe}")
            raise
    progress("RUNNING", "summarize")
    try:
        subprocess.run([sys.executable, str(worker), "summarize"], check=True)
        subprocess.run([sys.executable, str(worker.with_name("qms_real_fixed_replay.py"))], check=True)
        subprocess.run([sys.executable, str(worker.with_name("qms_real_profile.py"))], check=True)
    except Exception:
        progress("FAILED", "summarize/profile")
        raise
    progress("COMPLETE")


if __name__ == "__main__":
    main()
