# W3 Transport And Account Review

## Approved Boundary

C02 extends **transport**, not the QMS mathematics or financial engine.
See the [C02 plan](../../upgrade/implement.md#qms-c02---w3-process-batch-deadline-carry-and-multi-symbol-contracts)
and detailed guide [section 8.4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8).
The owner approved transport plus carry/multi-symbol spec/tests on 2026-10-05.
New account semantics below are **proposals**, not activated capabilities.

| Dimension | C02 implementation | Permission |
|---|---|---|
| Mode 4 / per_fold_causal, reset-flat, single symbol | Original native result witnesses | Supported |
| Sequential inprocess | Same original-result reducer | Supported |
| Sequential Linux fork/COW process | Detached original-pass witness | Supported with single-thread preflight |
| Native deadline / cancel | Existing completed-account-bar safe points | Supported, cooperative |
| Fixed/adaptive R3B witness | Existing shared-market batch primitive | Qualified primitive, no public meta activation |
| Public meta R3B/global | Reject before strategy/account work | Not activated; C03 prerequisite |
| Cross-fold account/order/strategy carry | Contract review below | Runtime unsupported |
| Multi-symbol/shared-margin meta W3 | Contract review below | Runtime unsupported |

Mode 2/global and other additional meta modes remain outside this extension.
No new scientific cohort or economic benefit is implied by transport parity.

## Original-Pass Witness Protocol

`ReactiveWitnessBindingV1` binds the complete typed task (run, candidate,
fold, stage, absolute window, history bounds, train/forward timestamps and
task seed), effective params, market signature, exact UTC calendar, economics,
metric contract and optional observer seed. It is versioned independently of
the native ABI. Transport mode does **not** change the meta compatibility family.

`DetachedReactiveWitnessV1` carries seven unchanged native scalar objective
fields and one authoritative `MetricObservation`. It carries **no** market
arrays, financial paths, strategy, model, history or account objects. The witness
is reduced from the original native result, not reconstructed from Sharpe,
turnover, trade counts or a second financial execution. Raw Sharpe, sample std,
support/status, first mark, output hash and original-result provenance retain
their prior meanings. Infinite profit factor is encoded as a float hex token;
it is not replaced with a finite objective.

The parent checks version, shape, seal, exact binding/calendar/economics/metric
and initial account before capture. The existing worker checks exact request ID
and generation; missing, duplicate, stale or out-of-order replies abort.
The SHA seal detects accidental corruption, **not** hostile-worker authenticity.
Trusted inherited local workers remain inside the process trust boundary.
Portable public decision/history artifacts retain their existing validated
codecs; this private transport does not add an untrusted pickle import API.

The market and prepared strategy features are inherited through Linux fork/COW,
with zero market serialization per task. Requests contain the small task/params
binding. One worker and one in-flight request preserve ask/evaluate/tell order.
Arbitrary callbacks are still Python-authoritative. Forking a threaded notebook
or service is rejected; launch a dedicated constrained process or use inprocess.
Forward observer RNG isolation is applied **inside the worker** as well as in
the parent. Post-seal diagnostic work cannot consume the next search RNG stream.
User strategies must still implement the existing task-local `reset(seed, task)`
contract for deterministic own RNG. CPython automatically reseeds its global
`random` stream after fork; transport does not promise to make an unseeded
arbitrary callback reproducible. Witness code does not invoke a user state
fingerprint twice or send arbitrary fingerprint objects over IPC.

The original-result path temporarily retains account arrays for the requested
window. They are released after reduction and never sent over IPC. This is not
a scalar-only memory claim. Native market ownership remains prepared/run-local;
mutable account, orders and strategy are fresh for every candidate window.

## Deadline, Failure And Publication

A deadline is set on the same original native runner before execution.
Cancellation reaches its existing native token. Checks occur at completed
account-bar boundaries (interval 64, plus existing terminal checks). There is
no partial accepted witness, valid label or partial history revision after
cancel/deadline. The observer propagates these aborts rather than relabelling
them `OUTCOME_FAILED` and publishing an incomplete panel.

Native deadlines are **cooperative**. A Python callback that blocks indefinitely
cannot be hard-preempted by a native check. Process cancellation can discard the
child; it does not promise rollback of arbitrary external callback side effects.
Worker death, bad response or poisoned callbacks discard the child and response
channels; a later explicit retry starts a new generation. Close is idempotent.
Completed prior history revisions remain intact. Label publication includes
actual elapsed diagnostic time and reporting lag, never a backdated deadline.

R3B witness retention is opt-in at the private prepared primitive: account
buffers only, streaming scores preserved, no fill/event/command/callback audit
tapes. Native per-candidate error codes exclude the failed candidate from
witnesses while independent peers can complete. A whole-batch error clears
all detached witnesses from that call, including earlier chunks. Each native
chunk remains bounded to 1..64 candidates. No global-to-causal relabelling or
sequential-TPE equivalence is claimed.
R3B cancellation uses independent atomic tokens obtained before the active
PyO3 borrow. This fixes the observed `Already mutably borrowed` failure without
changing financial cores. The C02 private witness primitive fails explicitly
with an old extension missing this additive token getter. Scalar meta-off
retention remains unchanged. The C02 local wheel is fresh, not reused from an
older native receipt; version identity alone cannot certify these new bytes.

## Proposed Carry Contract V1

Identifier: **qms-w3-continuous-carry-v1-proposed**. Activation: **false**.

Carry must preserve one financial authority across each chronological transition:

| State | Required ownership / identity |
|---|---|
| Cash, realized/unrealized PnL, units, cost basis | Same native account generation |
| Pending command/order/trigger queues, OCO links | Native IDs, phase and activation time preserved |
| Reserved cash/margin and contingent exposure | Same native margin ledger; no duplicate reservation |
| Funding clock / event mask / charged events | No omitted or double-charged boundary event |
| Dynamic DCA/grid campaign state | Explicit strategy/campaign version and reset permission |
| Strategy causal features / RNG | Versioned snapshot frontier; no future-derived cache |
| Params transition | Frozen previous units; new params affect future decisions only |
| Cancel / restart / partial transition | Fail atomic, no silent reset or replay of committed charges |

Default proposed transition: **preserve_positions_and_orders**. A parameter
change does not emit an order, realize PnL, resize units or charge a fee by itself.
If the strategy cannot carry its state under new parameters, it must choose an
explicit wait-flat or cancel/flatten transition and record its actual costs.
The transition must be sealed before the first economic action under the new
params. Gaps require explicit valuation/entry/funding/calendar policy; they are
not bridged by multiplying fresh-account diagnostic equities.

Independent accounting example (not an engine): capital 20,000, long one unit
at 100, one-way fee 0.0004, funding debit 0.0001 at 100. At a boundary mark of
120 the carried equity is **20,019.95**, initial margin at leverage 3 is **40**,
available equity is **19,979.95**. Unchanged units imply zero turnover and zero
transition fee. At mark 80 equity becomes **19,979.95**, not a reset to 20,000.
No new funding debit is implied solely by the parameter transition.

Required future gate: full ledger/fills/funding/fees/margin/strategy-order-state
parity with a single uninterrupted native run, including same-boundary close,
reverse, OCO cancellation, funding, liquidation and retry cases. A deterministic
snapshot codec and explicit param-transition semantics require separate approval.

## Proposed Shared Multi-Symbol Contract V1

Identifier: **qms-w3-shared-account-multisymbol-v1-proposed**. Activation: **false**.

One shared native account must own symbols/instruments, quantity/price filters,
contract size, currency conversion, available equity and aggregate margin.
Calendar alignment must preserve venue timestamps and distinguish observed,
stale, closed-session and non-tradable marks. No future price fill, implicit
backfill or independent-symbol account compounding is permitted. Stale marks
may be retained only under a declared valuation policy; they are not tradable
quotes. Simultaneous commands need deterministic ordering and a declared
all-or-none versus partial-acceptance policy.

Independent shared-account example: capital 1,000; A long two at 100, B short
one at 200; fee 0.0004 per fill; marks A=110/B=190. Aggregate opening fee is
0.16; aggregate mark PnL is 30. Positive funding 0.0001 charges A=0.022 and
credits B=0.019, net debit 0.003. Equity is **1,029.837**, gross exposure **410**,
net exposure **30**, initial margin at leverage 3 is **136.6666666667**. Available
equity is **893.1703333333**. Summing two separately initialized accounts would
double capital and is forbidden. A B order cannot execute on stale B data just
because A has a fresh event.

Cross-margin must compare aggregate post-cost equity and current accepted
exposure; portfolio liquidation ordering, fee convention, funding event phases,
hedge/netting and venue rules need their own versioned economic contract.
Do not call this generic linear-margin proposal Binance portfolio margin.
Required future gate: asynchronous calendars, simultaneous budget contention,
shared-margin rejection/liquidation, all-or-none packages and per-symbol
attribution reconciling exactly to the single account.

## Compatibility Families And Next Decisions

Current process/inprocess witnesses share the same reset-flat family and hashes.
Carry and multi-symbol proposals must declare **different** account/calendar/
strategy-state families. Existing reset-flat outcomes cannot silently train a
continuous/shared-account learner. C01 activation, C03 scheduler/recipe
qualification, checkpoint RNG continuation and Sobol/centroid extensions remain
separate decisions. Remote/public certification must use the new source/artifact;
historical QMS receipts are not C02 publication evidence.
