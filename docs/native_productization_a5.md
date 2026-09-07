# Native Productization And A5 Review

QuantBT promotes Rust by exact workload and contract, never by a generic
backend label. `contracts/native_event_product_registry.json` is the source of
truth for routing, protocol versions, wheel targets, and performance/RSS
evidence. `tools/generate_product_contracts.py --check` rejects generated
Python, Rust, documentation, or corpus drift.

## Wheel Matrix

Linux x86_64 CPython 3.11-3.13 remains `published-certified`. Linux aarch64,
macOS arm64/x86_64, and Windows x86_64 CPython 3.11-3.13 are CI certification
targets. `.github/workflows/native-platform-matrix.yml` builds each target,
installs the wheel outside the source tree, and negotiates API, result ABI, and
capabilities. A target is not described as published until its clean-wheel
evidence and release artifact exist.

## Auto Routing

`backend="auto"` requires all of the following for the exact workload:

1. compatible core/native protocol and capability fingerprint;
2. the required execution contract and result ABI;
3. parity status for that route;
4. end-to-end speed evidence against its intended Python comparator;
5. an RSS plateau result.

Failure keeps the route on Python with an explicit reason. `backend="rust"`
never silently falls back.

## A5 Deletion Gate

`contracts/native_event_a5_review.json` records stable release cycles, shadow
mismatches, measured fallback use, rollback, approval, and blocking reasons by
route. `tools/check_native_a5_review.py` reconciles it with the deletion
manifest.

No Phase 71 route currently qualifies for source deletion. Static command tape
and Native Strategy IR are A4; prepared WFO, bounded portfolio/package, and
intrabar routes are A3 or held by route-specific evidence. The root mirror and
Python/Numba production routes therefore remain. This is an enforced safety
decision, not an undocumented implementation gap.

The Python public facade, strategy protocol, independent oracle, reports,
adapters, and Nautilus validator are permanent retained surfaces even after a
future route reaches A5.
