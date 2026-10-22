"""Create a new, private, source-bound M5-02 binding admission lane."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.mode5_admission.preparation import prepare  # noqa: E402
from tools.mode5_admission.checks import check, run_retained  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--check-name")
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    if Path(args.attempt).name != args.attempt or args.attempt in {"", ".", ".."}:
        parser.error("--attempt must be one registered path component")
    if args.check_name:
        output = ROOT / "upgrade/private/mode5_upgrade_v1/m5-02" / args.attempt
        if any(path.is_symlink() for path in (output, *output.parents)):
            raise ValueError("symlink lane is forbidden")
        if not (output / "registration.json").is_file():
            raise ValueError("checks require a registered private lane")
        if args.pilot:
            script = ROOT / "upgrade/local/mode5_upgrade_v1/m5-02/pilot_v1.py"
            result = run_retained(ROOT, output, [sys.executable, str(script)], [script], args.check_name)
        else:
            sources = [ROOT / "tests/mode5/test_admission_ledger.py",
                       ROOT / "tests/mode5/test_admission_boundary.py",
                       ROOT / "tests/mode5/test_admission_lifecycle.py",
                       ROOT / "tests/mode5/test_admission_conformance.py",
                       ROOT / "upgrade/local/mode5_upgrade_v1/m5-02/test_private_alpha_contracts.py",
                       ROOT / "upgrade/local/mode5_upgrade_v1/m5-02/test_static_binding.py",
                       ROOT / "upgrade/local/mode5_upgrade_v1/m5-02/test_binding_edges.py"]
            result = check(ROOT, output, sources, args.check_name)
        print(result["stdout"], result["stderr"])
        sys.exit(result["exit_code"] if result["exit_code"] is not None else 124)
    else:
        if args.config is None:
            parser.error("--config is required for preparation")
        registration = prepare(ROOT, args.config, args.attempt)
        print(registration["registration_id"], registration["output"])
