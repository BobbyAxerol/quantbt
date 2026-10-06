"""Verify executed tests and exact artifacts before writing package closure."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from tools.qms_e04_report import executed_tests
from tools.qms_e05_installed import validate_consumer
from tools.qms_e05_source_guard import ROOT, verify


def reference(path):
    path = Path(path).resolve()
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha256(path.read_bytes()).hexdigest(),
                bytes=path.stat().st_size)


def build(package, junit):
    package = Path(package).resolve()
    proof = json.loads((package / "e05-proof.json").read_text())
    source = verify()
    if (proof.get("source_guard") != source or proof.get("core") != "1.1.2"
            or proof.get("native") != "0.4.3" or proof.get("native_rebuilt") is not False
            or proof.get("source_exact_wheel") is not True or proof.get("source_exact_sdist") is not True
            or proof.get("publication") is not False or proof.get("empirical_promotion") is not False
            or set(proof.get("consumers", {})) != {"wheel", "sdist"}):
        raise ValueError("package installed proof missing or source/pair changed")
    for row in proof["consumers"].values():
        validate_consumer(row, (proof["core"], proof["native"]))
    for artifact in proof["artifact_refs"]:
        if reference(ROOT/artifact["path"]) != artifact:
            raise ValueError("retained exact artifact changed")
    if reference(package / "e04-proof.json")["sha256"] != proof["base_proof_sha256"]:
        raise ValueError("underlying E04 proof changed")
    tests = executed_tests(junit)
    cases = [c for path in junit for c in ET.parse(path).getroot().iter("testcase")]
    groups = {f"T{i:02d}": sum(c.get("name", "").startswith(f"test_e05_t{i:02d}_")
        for c in cases) for i in (1, 2, 3, 4, 6)}
    if not all(groups.values()):
        raise ValueError("E05 mandatory software group absent; T05 is empirical, not a synthetic PASS")
    tests["package_groups"] = groups
    return dict(schema="qms-e05-software-closure-v1", source=source, tests=tests,
        installed=reference(package / "e05-proof.json"), artifacts=proof["artifact_refs"],
        gates=dict(software="PASS", installed_wheel_sdist="PASS", original_financial_source="UNCHANGED",
            empirical="NOT_RUN_PROTOCOL_OWNER_INPUT_PENDING", remote="NOT_RUN_CURRENT_BYTES",
            publication="NOT_AUTHORIZED"),
        pending=dict(e03_g01="SCIENTIFIC_COMPATIBILITY_APPROVAL_REQUIRED",
            e04_real_alpha="PROTOCOL_ALPHA_UNIVERSE_DECISION_PENDING",
            e05_real_alpha="DELIVERY_ROLL_SCOPE_AND_ORIGIN_COVERAGE_UNQUALIFIED"),
        economic_promotion=False, source_checkout_consumer=False, publication=False)


def render(receipt):
    return f'''# QMS-E05 Bounded Package Software Closure

## Scope

Read the [unified plan](../../upgrade/implement.md#qms-e05),
[exact package contract](DOMAIN_ADAPTER_CONTRACT.md#e05-package-amendment) and
[runnable example](../../examples/wfo_meta_package.py).
Mode 4 / `per_fold_causal`, original `native_event` financial authority:
frozen best-effort basket, linear non-expiring basis and statistical pair.
The adapter observes original account outputs; it does not replay execution.

## Executed Gates

- Current scoped conformance: **{receipt["tests"]["distinct_tests"]} distinct checks PASS**.
- Exact core **1.1.2** / native **0.4.3**, wheel and sdist consumers: **PASS**.
- Source guards preserve earlier scalar/reactive/portfolio seals and original
  financial/Rust/Ridge/sampler arithmetic. No native rebuild or release here.
- Original IS/forward full-report labels, off/shadow candidate pools/objectives/
  params/accounts, active final account, prepared/reference witnesses and future
  mutations are checked. Fees/slippage/funding and margin-rejected packages have
  independent expected-value cases. Rejected targets are not treated as fills.
- Typed fills and nested rejection metadata are hashed from original records.
  A test-discovered dict hashing defect was repaired without changing accounting.
- An earlier artifact omitted untracked new modules; the final fresh lane verifies
  every canonical module in both artifacts. Failed logs/receipts stay unchanged.

## Remaining Gates

**Not empirical promotion.** Real E04 portfolio on/off R/Q/decay study needs the
alpha/universe/protocol decision; no synthetic result claims better forward edge.
E05 real basis source includes quarterly expiry/roll and limited 2025 coverage.
The bounded non-expiring adapter cannot silently erase settlement or claim the
registered minimum-origin gate from insufficient history. This needs reviewed
domain/data scope before a real package promotion study, not fabricated bars.
E03-G01 prepared-unit liquidation objective compatibility remains open, awaiting
separate approval. No estimator, scientific metric contract or failed historical
study was changed. Remote six-platform/current-artifact and public gates are not
run; workflow wiring is preparation, not runner evidence.

## Invocation And Cleanup

Keep `scoring_backend="endpoint"`, `use_scalar_trial_scoring=False`,
`native_prepared_wfo="off"`, ordered symbols/spec legs and exact aware OHLC maps.
Package strategies return finite window-aligned signal Series. Unsupported
hedges/expiry/quantity/cost/margin/backend requests fail closed. Meta-off default
proxy behavior is unchanged; exchange-native atomicity is not claimed.

Reproduce with `python -m tools.qms_e05_package --help` then
`python -m tools.qms_e05_report --help`. Retain artifacts, source staging, logs,
private inputs and evidence. Remove only reviewed inactive reproducible consumer
scratch; follow [the cleanup runbook](../BUILD_TEST_CLEANUP.md). This report does
not constitute permission to push, merge, tag or publish.
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--junit", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("sealed closure receipt exists; use a fresh receipt")
    receipt = build(args.package, args.junit)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    args.report.write_text(render(receipt))
    print(json.dumps(receipt["gates"], sort_keys=True))
