# Portfolio Target Contract

Portfolio execution is a target-to-accepted-position transformation:

```text
signal/target -> requested units -> quantity constraints -> margin gate
              -> accepted units -> delta trades -> accounting
```

The policy distinguishes non-tradable, stale, invalid, minimum-quantity,
minimum-notional, and post-cost-margin rejections. A rebalance does not happen
merely because a bar arrived; it happens when the configured policy requests a
new target. Unchanged symbols are skipped after the target comparison.

The current Rust surface exposes target and package *preflight* primitives.
They are useful for conformance and preparation, but they are not a promoted
generic multi-symbol execution backend. Python remains the public portfolio
oracle and default route until full installed-wheel parity is certified.
