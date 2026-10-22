# Shared Alpha Diagnostics Cleanup

## Registered Budget

Owner-authorized local standardization, 2026-10-16 Asia/Saigon. No new environment,
native build, optimizer or long economic worker. Scratch cap 64 MiB, retained
test/report cap 16 MiB and minimum free-space headroom 5 GiB.

The only eligible deletion is the newly created, ignored and inactive
`.tmp/shared-alpha-diagnostics` test root. Pytest fixtures/cache below it are
reproducible synthetic inputs; XMLs and benchmark/source receipts are retained
under `benchmarks/diagnostics`. No broad cache, `.maturin`, Rust target, data,
alpha, historical snapshot, native binary or environment is eligible.

## Verification

The [machine receipt](../../benchmarks/diagnostics/shared_alpha_diagnostics_cleanup.json)
records exact before/after free bytes/inodes, reviewed scratch size, protected
file hashes and any symlinks. All owned exec sessions completed before cleanup;
no unrelated process was signalled. Sandbox process visibility is limited and
is not used to justify deleting anything outside the exact owned root.

Terminal result: 34 protected files, including prior scientific summaries and
the existing native binary, retain identical SHA256. Reviewed scratch file
bytes were 426,998; observed filesystem free-space gain was 2,789,376 bytes
(2.66 MiB), including directory/block and unrelated host effects. Available
bytes after removal were 6,253,907,968, with 5,498,867 free inodes. Retained
benchmark/test files were 255,551 bytes before the cleanup receipt was written,
well below the 16-MiB cap. No evidence/environment/native artifact was deleted.

The native 0.4.3 artifact used in the final fixture qualification remains in
place. The primary environment and its installed 0.4.2 were not overwritten;
qualification used a process-local explicit import path only. Initial scratch
setup/native-pair failures and overlapped timing outputs remain as historical
attempts, not successful release evidence. No environment needs reinstall as
a result of this cleanup. No publication or economic promotion follows.
