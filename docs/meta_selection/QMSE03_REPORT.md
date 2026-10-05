# QMS-E03 Scalar Sizing And Backend Coverage

## Scope

E03 extends the existing E02 domain adapter, not the financial engine or Ridge
methodology. The approved guide remains authoritative:
[routes](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s3),
[raw mathematics](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[causal labels](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[prepared ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
and [scientific scope](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).
See the [phase plan](../../upgrade/implement.md#qms-e03) and
[scalar execution contract](DOMAIN_ADAPTER_CONTRACT.md#e03-scalar-amendment).

| Target | Financial backend exercised | Interpretation |
|---|---|---|
| `signal_notional` | Native vectorized, native event | Frozen units until signal transition |
| `notional` | Native vectorized, native event | Original constant-quote target rebalance |
| `unit` | Native vectorized, native event | Original window-start unit scaling |
| `pct_equity` | Legacy/Numba | Original equity sizing on transition |
| `dca_ladder` | Legacy/Numba | Original signed structural caps and high/low ladder |

`single_signal` and `%_equity` are canonical aliases when meta is enabled.
Methodology remains **Mode 4 / per_fold_causal / endpoint scoring**. New cells
are `SOFTWARE_VALIDATED_OPT_IN`, not economic promotion or changed defaults.
Native-event support here means signal-to-rebalance orders, not generic Python
callbacks, reactive grid, intrabar intent or package execution.

## Domain And Compatibility

Financial evaluators own accepted units, fees/slippage, margin, funding,
liquidation and account state. Each observation is reduced from its original
execution exactly once, with zero financial replay. Independent fold diagnostic
accounts supply IS/forward raw metrics; one original account processes stitched
OOS targets. Fold equities are not concatenated to manufacture an account.

The versioned scalar contract validates target/backend/timing/sizing. New family
IDs bind the E02 compatibility contract; old qualified family IDs stay exact.
Different ladder policies and event timing cannot share compatible history.
Market preparation remains owned by the existing run context, not a new cache.

Preflight rejects mismatched sizing and legacy overrides that the original
engine would not apply. Legacy `fee` is round-trip compatibility input, so its
canonical one-way fee is `fee / 2`; explicit conflicting one-way overrides
cannot label ignored economics. Prepared-required pct-equity errors retain
`NativePreparedPublicWfoUnsupported`. Ladder needs real high/low and signed
integer caps. Ladder/event rebalance cannot be shifted into a same-close
prepared scorer. Meta omitted/off proxy defaults and endpoint signatures stay.

## Correctness And Packaging

Independent expected-value tests cover fixed/frozen targets, reversals, accepted
trade deltas, fees/slippage, quantity steps/minima, buying power, rejection,
funding and liquidation. Ladder fixtures cover long/short safety fills, TP
priority, same-bar base-entry ordering and carried-position funding.
Off/shadow pools, RNG, params and continuous-account arrays are exact; future
suffix mutations cannot alter earlier decisions. Same-close prepared/notional
and unit paths keep original pools, selection and accounting within documented
floating-point tolerances. Financial/numeric Rust sources are unchanged.

Installed core `1.1.2` / native `0.4.3` wheel and sdist consumers run all eight
cells with compiled meta under `require`. Source inventories, artifact allowlist
and all prior mandatory consumers are checked; native wheel reuse is permitted
only by the unchanged source/artifact hash proof. This local CPython 3.12 Linux
proof is not Ubuntu 22/24 x CPython 3.11-3.13 or public-index certification.
The candidate matrix now includes the installed scalar proof; no push ran.

## Registered Study

Status: execution in progress; no economic PASS or default promotion is claimed.

- Gradient/Delta RSI on immutable research-exposed ETHUSDT 1h, 37,968 bars.
- 28 monthly origins, January 2022 through April 2024; rolling 365D IS.
- 128 attempts/fold, seed 731, one frozen `tpe_legacy` recipe, no early stop,
  warm start or outcome-driven retuning. Every arm has its own history/account.
- Original allocation: pct-equity 0.5; other scalar cells quote 10,000, quantity
  step 0.001. Initial capital 20,000, leverage 1, canonical one-way fee 0.00025,
  slippage 0.0001 and baseline constant funding 0.0001. This is not a claim of
  historical venue-exact funding.
- Ladder uses a simple causal mean-reversion signal on actual OHLC, with signed
  level caps. The owner authorized simulation; it is not a private real DCA alpha.
- At least 12 supported matured origins. Interval: 95% moving-block percentile,
  three monthly origins per block, 4,096 registered draws. No candidate/seed is
  counted as an independent market sample; undefined windows remain explicit.

Raw, original-account diagnostic Sharpe defines:

$$
D_n=I_n-F_n,\qquad D_m=I_m-F_m,\qquad R=D_n-D_m,
$$

$$
Q=F_m-F_n,\qquad R=(I_n-I_m)+Q.
$$

Registered gain needs mean supported $R>0$ and the lower interval bound of
forward $Q\geq0$. Lower IS alone is not forward improvement. Native versus
active must have the same full IS search pool. Final continuous-account Sharpe
is reported separately from these fold diagnostics. A threshold pass still
needs owner review; these data are not a new pristine holdout or live proof.

## Execution Integrity

Initial registration/package v1 stays archived. One completed native run failed
only during receipt export of a pruned infinite Optuna objective; its account
arrays were retained. A subsequent partial native run was stopped when the
full regression exposed the prepared exception compatibility issue. No active
outcome or economic threshold prompted these fixes. Corrected source/package
v2 has a new immutable registration and the same financial protocol.
Pruned nonfinite objectives are now explicit tokens, not fabricated zero labels.
Failed/aborted runs are not counted as successful origins or concealed retries.

Timing uses one fresh process per arm on a shared VPS, not repeated medians or
isolated performance certification. Public execution wall/CPU/RSS are separate
from cold evidence export and the independent final-account check. Fit/select
and observer spans can overlap other spans; they are not an additive partition.
Prepared study parity does not mean the private Python alpha has become Rust.

## Reproduction

Run the self-contained [scalar example](../../examples/wfo_meta_scalar.py)
without private inputs. Full private study requires the owner's immutable
alpha/data registration; neither source nor raw trial params enter artifacts.

```bash
python -m tools.qms_e03_study register --output data/local/qms-real-review/new-study
python -m tools.qms_e03_queue --output data/local/qms-real-review/new-study
```

The study interpreter must load the qualified installed pair, not repo source.
Queue resumes only matching sealed complete arms and never retries failures
automatically. Keep old receipts and use a fresh lane for a changed candidate.
`tools/qms_e03_report.py` verifies source, actual JUnit, artifacts, baseline
parity, all eight pairs and full prepared studies before sealing a public report.

## Remaining Gates

Official economic promotion, true real-DCA-alpha evidence, owner acceptance,
current-source remote matrix and public-index release are separate, pending gates.
C01/C05 activation remains unapproved. E04-E08, carry/multi-symbol/public-meta
batch and cross-domain methodology expansion are not implemented by this phase.
No commit here authorizes push, merge, tag, publishing or another phase.
