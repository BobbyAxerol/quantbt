# M5-11.1 Native Runner Output Closure

Status: **LOCAL OUTPUT/ACCOUNTING GATE PASS; RESEARCH IN PROGRESS**.
Authority: [ordered goal closure](../../upgrade/implement.md#mode5-m5-11-goal-closure)
and guide [cache identities](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#72-computationoutput-plan-và-cache)
and [resource planning](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#73-resource-plan-và-tốc-độ-không-làm-hỏng-methodology).
This is not a completed five-alpha panel, economic improvement, public artifact,
remote qualification or release certificate.

## Corrections

- OCO cancellation identifies the canceled sibling; the winning fill remains
  FILLED. A causal target reference is not an accepted cancel of the winner.
- Audit exports authoritative final command-slot state from the existing Rust
  owner. Active/waiting/retired slots, amended working values, remaining quantity
  and trigger state have explicit availability. No account replay.
- Cancellation diagnostics count actual canceled order-slot transitions.
  Separate event and order counters retain their distinct units; the historical
  scalar counter remains unchanged.
- Fill liquidity preserves the frozen Python reporting convention: MARKET is
  taker, other order types are maker, including STOP_MARKET. Native matched
  order-type provenance is explicit. This is **not venue liquidity proof** and
  does not change matching or fees.
- Cold fill summaries sum retained quantities/fees and use quantity-weighted
  prices. Multiple partial fills do not overwrite one another or imply that
  an unfinished/canceled order became fully filled.
- Native wire identity does not carry original compiler indices. The cold
  identity join is labeled explicitly, not advertised as Rust-owned identity.

## Matched Controls

Final qualification replays three original sealed command tapes twice in Rust
and once with the Python oracle, on each original 26,280-bar continuous
development account. It does not repeat historical feedback convergence.

| Control | Actual Fills | Live Terminal Orders | Canceled Order Slots |
| --- | ---: | ---: | ---: |
| HMA | 645 | 2 | 395 |
| HASH | 758 | 3 | 579 |
| VWAP original empty-book control | 0 | 0 | 0 |

Raw equity, returns, positions, fees, funding, margin, turnover, fills and
native event columns match the retained native controls. Full available
terminal reports, cancellation paths and liquidity labels match the Python
oracle at the frozen absolute tolerance of 1e-8 and zero relative tolerance.
The next full feedback compilation yields the identical sealed command tape;
market and original alpha/source identities remain unchanged.

Final checks: **72 Rust scoped tests**, **39 Python output/clock tests**, and
the separately qualified **34 custody tests**. These suites have different
responsibilities and are not a count of financial research configurations.
Final matched replay bills **9 actual account passes / 236,520 account-bars**.
Including the earlier retained success and harness-schema failure, completed
retained replay work is at least 21 passes / 551,880 bars. In-flight work is
not invented. Original failure logs and source revisions remain retained.

## Runtime And Custody

Fixed-tape native calls took about 0.08-0.30 seconds; a single alpha
recompilation took about 0.84-1.67 seconds. These are controls, **not full-panel
candidate runtimes or a compiler speedup**. Full HMA/HASH execution still
converges through hundreds/thousands of actual-fill-feedback account passes.
No signal approximation, guessed fills or unsupported mid-compiler resume.

The research supervisor verifies source/data/request/artifact pins, journals
returned account work, limits shared independent workers, and records
interrupt/fault custody. It never automatically retries on a stale heartbeat.
Completed candidates can be reused; censored candidates need a fresh attempt.
SIGKILL/power loss cannot promise a synchronous final receipt; retained journals
and verified live process sessions govern explicit recovery.

Exact local CPython 3.12 extension, source pins, old/new artifacts, logs and
append-only receipts remain private and ignored. Existing alpha/data/parameter
source and historical failed/PASS receipts were not edited. No CI/push/merge/
tag/publication ran. Reviewed build/extraction/JIT scratch remains because
upcoming registered jobs need it; no shared cache/evidence was deleted. Disk
reserve exceeds 5 GiB. The next execution is only missing RSI/SC selector
evidence, followed by remaining native panels and required diagnostics.

## Retained HASH Index1 Adoption

After the bounded RSI/SC compound closure, the second retained HASH control
passed a fresh source-bound adoption check. It reused its completed commands;
the historical 846 feedback passes were **not repeated or rebilled**. Two Rust
runs plus one Python reference billed **3 passes / 78,840 account-bars**.
Worker elapsed time was **34.42 seconds**, peak process-group RSS **608.02 MiB**;
the whole supervision lane took 45.07 seconds including custody overhead.
These are replay-control costs, not full-candidate or sampler benchmarks.

The control has 1,138 fills, 421 cancellation events and 968 canceled order-slot
transitions. Raw retained accounting and repeat Rust execution pass; available
terminal/cancellation/liquidity fields match the Python oracle. Rust remains
the authoritative terminal-state owner. `remaining_qty`, `qty_semantics`,
`processed`, working-state availability and terminal/command coordinates have
no corresponding Python terminal fields, so full cross-owner remaining-quantity
parity is explicitly unavailable, not claimed. Existing focused native tests
certify those native outputs separately. The next full build yields identical
commands and the market witness remains unchanged.

All owned children were reaped, cleanup verification has no errors, and all
control outputs/failures/artifacts remain retained. This step changes no alpha,
matching, fees, accounting, RNG or scientific policy. The fresh three-cell
native tranche still requires exact runtime/wrapper custody review; this receipt
does not complete HMA/HASH/VWAP's 128-configuration panels or release gates.
