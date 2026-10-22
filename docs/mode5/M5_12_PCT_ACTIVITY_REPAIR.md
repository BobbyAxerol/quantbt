# Accepted Position And Activity Compatibility Repair

## Scope

The owner approved this narrow M5-12 repair after source regression reproduced
prepared/reference `pct_equity` positions and activity disagreement. ACC-01
already made reference positions accepted contract quantities. The Rust public
adapter still exposed requested weights, and its score counter overrode accepted
position changes with requested-signal transitions.

The repair retains accepted quantities publicly and requested weights separately.
The historical report activity count is the initial number of symbol states plus
subsequent accepted quantity changes. It is not fills, closed trades or campaigns.
No fill, fee, equity, margin, funding, Sharpe, sampler or Ridge formula changes.
An activity-dependent objective can change from its previously incorrect value;
unchanged selected candidates are not promised for such a contract.

## Safety

- A native capability marker gates prepared pct scoring, including meta-off.
  An old same-version wheel cannot satisfy this contract by version alone.
- Pct binding/cache and meta activity-contract identities change. Other workload
  identities remain unchanged. Old pct history/models must not be relabeled.
- Independent expected paths cover ignored first-bar requests, rejected entry,
  and liquidation. Full-result and score-only activity share these expectations.
- Existing funding, quantity constraints, non-pyramiding, WFO selection/account
  and worker parity tests remain in the focused suite.

## Local Evidence

The fresh default-feature native wheel was built offline, locked and single-job
on CPython3.12 in68.21seconds. Build-time net filesystem growth was1,503,232bytes
with the5GiB reserve held at exit; this is not a measured peak or speed benchmark.
The primary environment/native installation was not replaced.

Focused source tests using the exact newly built extension pass **61cases**.
The first attempt retained31passes and3test-assertion failures: the cold result
status is `"success"`, while the SoA status is integer0. Correcting that assertion
does not change execution. The second attempt additionally covers fresh artifact
provenance and stale/mismatched native admission negatives.

This receipt is focused source/native qualification, not final installed-core,
sdist, manylinux, remote, economics or public-release certification. Those gates
are recorded separately in the final M5-12 report. Earlier failed suite/artifact
receipts remain historical and immutable.
