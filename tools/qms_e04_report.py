"""Render bounded E04 software evidence; never manufacture empirical promotion."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from tools.qms_e04_installed import validate_consumer
from tools.qms_e04_source_guard import ROOT, verify


def ref(path):
    path = Path(path).resolve()
    return dict(path=str(path.relative_to(ROOT)), sha256=sha256(path.read_bytes()).hexdigest())


def executed_tests(paths):
    cases = [c for p in paths for c in ET.parse(p).getroot().iter("testcase")]
    ids = {(c.get("classname"), c.get("name")) for c in cases}
    if not cases or len(ids) != len(cases):
        raise ValueError("missing or duplicate executed test identities")
    if any(c.find(s) is not None for c in cases for s in ("failure", "error", "skipped")):
        raise ValueError("E04 software receipt requires no failures/errors/skips")
    groups = {f"T{i:02d}": sum(c.get("name", "").startswith(f"test_e04_t{i:02d}_")
                              for c in cases) for i in (1, 2, 3, 4, 6)}
    if not all(groups.values()):
        raise ValueError("E04 software test group absent; T05 is a separate empirical gate")
    return dict(distinct_tests=len(ids), groups=groups, empirical_t05="NOT_RUN",
                evidence=[ref(p) for p in paths])


def validate_profile(profile):
    if (profile.get("schema") != "qms-e04-public-portfolio-profile-v1"
            or profile.get("real_alpha") is not False
            or profile.get("economic_claim") is not False
            or profile.get("publication") is not False
            or profile.get("exact_parity") is not True):
        raise ValueError("invalid synthetic portfolio profile")
    rows = profile["rows"]
    if set(rows) != {"off", "reference", "prepared"}:
        raise ValueError("missing matched profile arm")
    if rows["reference"]["identity"] != rows["prepared"]["identity"]:
        raise ValueError("reference/prepared search/account/pool mismatch")
    for name in ("account", "params", "trials"):
        if rows["off"]["identity"][name] != rows["prepared"]["identity"][name]:
            raise ValueError("off/shadow search/account mismatch")
    if any(r["warm_median_seconds"] <= 0 or r["observer_failures"] for r in rows.values()):
        raise ValueError("invalid timings or observer failure")
    return rows


def build(*, package, junit, profile, baseline):
    source = verify()
    artifact = json.loads((package / "e04-proof.json").read_text())
    if (artifact.get("source_guard") != source or artifact.get("publication") is not False
            or artifact.get("empirical_promotion") is not False
            or artifact.get("source_exact_wheel") is not True
            or artifact.get("source_exact_sdist") is not True):
        raise ValueError("unbound installed portfolio source/artifact receipt")
    if set(artifact["consumers"]) != {"wheel", "sdist"}:
        raise ValueError("both installed artifact kinds required")
    for consumer in artifact["consumers"].values():
        validate_consumer(consumer, (artifact["core"], artifact["native"]))
    for item in artifact["artifact_refs"]:
        path = ROOT / item["path"]
        if ref(path)["sha256"] != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError("installed artifact bytes changed")
    base = package / "e03-proof.json"
    if ref(base)["sha256"] != artifact["base_proof_sha256"]:
        raise ValueError("existing scalar/package consumers are not bound")
    old = json.loads(Path(baseline).read_text())
    if old.get("exact_parity") is not True:
        raise ValueError("historical source/search/account compatibility is not PASS")
    values = json.loads(Path(profile).read_text())
    validate_profile(values)
    return dict(schema="qms-e04-software-closure-v1", source=source,
        tests=executed_tests(junit), installed=ref(package / "e04-proof.json"),
        pair=[artifact["core"], artifact["native"]], profile=values,
        evidence=[ref(profile), ref(baseline)],
        software_gate="PASS", installed_gate="PASS", empirical_gate="NOT_RUN",
        owner_promotion="PENDING", remote_gate="NOT_RUN_FOR_CURRENT_BYTES",
        publication=False, empirical_promotion=False)


def render(receipt):
    rows = receipt["profile"]["rows"]
    table = "\n".join(f"| {name} | {r['warm_median_seconds']:.3f} | "
        f"{r['fresh_process_peak_rss_mib']:.1f} |" for name, r in rows.items())
    speedup = rows["reference"]["warm_median_seconds"] / rows["prepared"]["warm_median_seconds"]
    return f"""# QMS-E04 Portfolio Software Closure

Generated from exact local receipts, not handwritten economic outcomes.
Read the [unified plan](../../upgrade/implement.md#qms-e04),
[domain contract](DOMAIN_ADAPTER_CONTRACT.md#e04-portfolio-amendment)
and [example](../../examples/wfo_meta_portfolio.py).

## Scope And Authority

Mode 4 / `per_fold_causal`, `target_mode=\"portfolio\"`, original
`native_portfolio` shared account. Exact ordered universe/calendar and positions
are required. IS and forward metrics come from the original aggregate full
report, never mean symbol Sharpe. Diagnostic accounts reset; final OOS positions
are stitched once into the existing continuous account. No financial replay,
new portfolio engine, Ridge mathematics or sampler changes.

## Gates

| Gate | Result |
|---|---|
| Scoped software | PASS: {receipt['tests']['distinct_tests']} distinct checks |
| Source/historical scalar/reactive/account locks | PASS |
| Installed wheel and sdist, pair {receipt['pair'][0]} / {receipt['pair'][1]} | PASS |
| Real portfolio alpha, paired R/Q/decay (T05) | NOT_RUN |
| Empirical promotion / owner review | PENDING |
| Remote / public release | NOT_RUN for current bytes / NOT_AUTHORIZED |

Earlier failed XML/build/install lanes remain unchanged. A software receipt
does not waive E03-G01 prepared-unit liquidation metric incompatibility.

## Matched Synthetic Performance

730 daily bars, two symbols, four folds, six attempts/fold, seed 731, one thread.
Each arm has its own fresh process/account; warm values use two full-study runs.

| Arm | Warm median (s) | Process peak RSS (MiB) |
|---|---:|---:|
{table}

Prepared witness/reference speedup: {speedup:.2f}x. Off and shadow have exact
account, selected params and trial identities; reference and prepared also
share the exact candidate pool. Meta still costs more than off, including
post-seal label observations. This fixture is synthetic, not evidence of lower
decay, economic edge, a universal speedup or Rust portfolio promotion.

## Invocation And Limitations

Use the existing `QuantBTEndpoint.walk_forward`, original `portfolio_mode` and
`sizing`, an explicit `symbols` list, `scoring_backend=\"endpoint\"`,
`use_scalar_trial_scoring=False`, `native_prepared_wfo=\"off\"` and an opt-in
`meta_selection` policy. Prepared portfolio arrays are a separate owner from
the scalar Rust scorer. Missing/stale observations retain caller policy;
unaligned source calendars are rejected, not resampled.

No W3 multi-symbol carry, options/venue-specific portfolio margin, additional
meta methodology or official empirical promotion is certified here. Real
alpha/universe/search/R/Q analysis must be frozen before results, with no
gain-driven retuning. NEXT: finish the separately approved real portfolio gate;
E05 requires its own authoritative package scorer and original-account proof.

## Reproduce And Cleanup

Run `python -m tools.qms_e04_package --help` for a fresh isolated offline
wheel/sdist lane, then `python -m tools.qms_e04_report --help` for receipt-bound
report generation. Reuse the repository build environment, not an alpha venv.
Retain dist/staging, native wheel, logs and receipts. Only inactive reproducible
consumer scratch may be removed after hash verification; reinstall it before
rerunning. Follow the [cleanup runbook](../BUILD_TEST_CLEANUP.md).
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "profile", "baseline", "output", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--junit", type=Path, action="append", required=True)
    args = vars(parser.parse_args())
    output, report = args.pop("output"), args.pop("report")
    if output.exists():
        raise ValueError("sealed closure receipt exists; choose a fresh output")
    receipt = build(**args)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    report.write_text(render(receipt))
