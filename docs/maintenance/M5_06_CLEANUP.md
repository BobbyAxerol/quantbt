# M5-06 Cleanup Receipt

## Registered Scope

The exact ignored phase-owned lane was removed after initial qualification and
again after native-binary provenance review:

```text
.maturin/mode5-m506/attempt-01
```

Incremental budget **256 MiB**, at least **5 GiB reserve**, one worker/numeric
thread. Existing qualified tooling was reused. No rebuild, installation,
environment removal, service shutdown or broad cache deletion occurred.

Host `ps -eo pid,args` confirmed inactivity before each removal. Safe removal
unlinked 34 synthetic pytest symlinks per pass without following them into
source/data. All scientific evidence and private inputs remained ineligible.

## Results

| Removal | Scratch File Payload | Observed Filesystem Recovery |
|---|---:|---:|
| Initial source qualification | 4,752,896 bytes | 5,758,976 bytes |
| Binary provenance final review | 4,622,529 bytes | 5,627,904 bytes |

Combined immediate recovery: **11,386,880 bytes / 10.86 MiB**. Final immediate
free space: **26,262,167,552 bytes**, above the registered safety reserve.
These are observed local before/after filesystem changes, not total host disk
movement or the sum of apparent directory sizes.

**1,055 protected original/source/history hashes** and **21 current geometry/
test/harness hashes** verified unchanged at final closure. First cleanup verified
106 retained files; final review verified its 13 retained source/receipt files
plus unchanged protected inputs and byte-identical account/geometry matrices.
All earlier passing/failing and current receipts remain retained.

The native package-initializer witness was corrected to an actual `.so` witness
in a new provenance revision. Prior reports and the pre-correction harness are
preserved, not overwritten. No additional alpha account was executed for that
correction. Original alphas, market CSV, guide, unrelated old specification,
all prior phase evidence and current tooling/artifacts remain intact.

## Handoff

Current closure is in the ignored M5-06 `provenance-review-02` lane. Its hashes
and original closure are sealed in [M5-06 evidence](../mode5/evidence/m5-06.json).
The [phase report](../mode5/M5_06_GEOMETRY_REPORT.md) separates technical
qualification from finite development screening and missing full-space evidence.
Disposable scratch is absent. Rerunning tests recreates scratch and requires a
new append-only receipt and cleanup; historical receipts do not require retaining
pytest/JIT scratch. No private input or helper was staged for Git/package inclusion.
