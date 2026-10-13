# M5-11.4 Storage Review And Cleanup

Date: 2026-10-13 UTC. Status: **PASS_CLEANUP_ONLY**, not a completed diagnostic
phase, financial qualification or economic promotion.

## Review Before Launch

The owner requested cleanup and a review of evidence growth before another
lane. The approved 10-GiB prospective ceiling is not current usage or a target.
The stopped January-start attempt occupies **2.335 GiB** of logical payload:

| Payload | MiB |
|---|---:|
| Per-bar decision JSON | 1,331.36 |
| Cold report revisions | 413.42 |
| Source copies | 247.44 |
| Compressed account arrays | 167.54 |
| Other retained records | 231.17 |

One closed decision journal compresses from 34,070,729 to 2,866,928 bytes with
gzip level 3, with exact decompression equality (11.88x). This was an in-memory
measurement only. No original journal was removed, recomputed or replaced.
Repeated historical source snapshots also have substantial identical-content
redundancy. These are storage opportunities, not measured disk recovery:
compression/deduplication needs verified pin, reader, replay and immutable-
ownership compatibility before use. Do not solve duplication by truncating
audit evidence or shortening the approved scientific calendar.

## Removed Exact Paths

Three inactive, superseded installed consumers:

- `.maturin/qms08/e03-package-v2/consumer`
- `.maturin/qms08/c04-package-v1/consumer`
- `.maturin/qms08/e05-package-v3/consumer`

Seven completed test-fixture directories under
`.maturin/mode5-m5114/attempt-01/`:

- `assembler-tests`
- `archive-tests`
- `report-budget-tests`
- `public-tests-02`
- `plot-tests`
- `plot-tests-02`
- `storage-review-tests`

No whole parent, evidence tree, source, Git state, artifact, log, dependency
cache or primary environment was deleted. Historical consumers require a
fresh isolated installation from the retained exact artifacts before rerun;
their original receipts are not relabeled as currently installed environments.

## Verified Preservation

The focused helper passed **23 synthetic tests**, including sandbox refusal,
active-reference blocking, symlink/traversal refusal, candidate allowlisting,
changed protected inputs, inventory tampering and evidence retention. Ruff
passed. Original and updated test XML, exact helper snapshots and two failed
preflight summaries are retained privately. The wrong system interpreter and
an overbroad scan of an old synthetic symlink fixture both failed before any
deletion; neither failure was changed to PASS.

Actual removal used the host PID namespace. Ten host audits inspected
164--166 processes through command lines, working directories, executables,
open descriptors and mappings; no candidate was active. FD-relative,
symlink-safe removal used only the reviewed ignored roots.

Before and after removal, **8,779 protected files** were hash-checked, including
all current accounts, failed/partial supervision, guardian records, private
source snapshots, test XML, public core and financial-source inputs. **Nine
artifact references** still match their receipt hashes. No extra finance or
search was performed by the cleanup helper.

Keep the project environment, `release-regression-v1`, the still-referenced G01
consumer, qualified historical runtimes, the exact qualified native binary,
Numba/Matplotlib caches and offline dependencies. No unrelated service was
stopped and no additional financial lane was launched.

## Filesystem Result

| Measure | Result |
|---|---:|
| Available before cleanup | 12.758 GiB |
| Available after cleanup | 14.419 GiB |
| Observed available-space increase | 1,700.887 MiB / 1.661 GiB |
| Reviewed paths' apparent allocated size | 1,701.039 MiB |
| Minimum required reserve | 5 GiB |

The shared filesystem can change through other host activity. Report the
observed delta separately from apparent allocation; do not claim exact causal
attribution for the small difference.

Private immutable records:
`upgrade/private/mode5_upgrade_v1/m5-11-4/attempt-01/storage-review01/`.
Inventory SHA-256:
`c2d3e3ccfcb92b8e4272453ddaedb3cda8e0c5656e9760039dbba12cf488d4a9`.
Cleanup receipt SHA-256:
`0d5bdb3286e43053ced839b0bcabbd19c01fcb47b3e7c78978e048e648eba294`.

## Operational Stop And Remaining Work

The agent mistakenly edited pinned `AGENTS.md` during this review. The
supervisor correctly stopped the lane; its original bytes were restored
exactly. The partial/failed parent receipt stays unchanged. Cold readback
admits 168 clean terminal-group records out of 172 returned passing financial
records; four remain unqualified. Both guardians verify the thirteen earlier
reused records. See [the progress report](../mode5/M5_11_4_FULL_DEVELOPMENT_PROGRESS.md#storage-review-and-stopped-lane).

M5-11.4 remains incomplete. Full registered coverage, source-compatible future
storage/scheduling and the final five-alpha dossier are not implied by this
cleanup receipt. No push, CI, release or subsequent research phase occurred.
