# ACC-01 Terminal Cleanup

2026-10-22, Asia/Saigon. [Machine receipt](../portfolio_review/evidence/acc01-cleanup.json).
This is an operational receipt, not package, economic or release certification.

All introduced financial/test/build sessions were reaped by the central
controller. Code/documentation agents completed and were closed. The cleanup
also checked cwd/FD/maps visible in its sandbox PID namespace; that scan does
not claim visibility into every host process. No active reference to the owned
scratch root was found. No service, notebook, environment or external queue
was stopped.

The single registered ignored disposable root was removed:
`upgrade/private/acc01/attempt-01/scratch`. It contained882regular files,
882unique inodes,27,604,496apparent bytes and29,962,240allocated bytes. These
were baseline Git-source extraction/archive, old/new native extraction,
pytest fixtures and lane-owned Numba cache. All are reproducible from retained
commits/artifacts; no broad `.maturin`, Cargo target, dependency-cache or
environment removal occurred.

Actual available bytes rose5,599,481,856 ->5,631,303,680:
**31,821,824bytes (30.35MiB) observed improvement**. This filesystem delta is
not inferred from `du` and may include host activity. The5GiB reserve remained.
Available inodes and exact inventory are recorded in the machine receipt.

106retained file hashes were checked unchanged across removal, including
every lane receipt/script/log/XML, the exact new wheel, the previous wheel,
owner's unrelated spec and primary native extension. Exact current source
qualification was rerun for464files, preserving historical receipts and all
registered unchanged inputs. No failed attempt became PASS because its
scratch was cleaned.

For another native consumer run, restore the exact retained wheel extraction
and verify its extension hash before execution. The removed consumers are not
reusable installations. Core wheel/sdist clean-install, other platforms and
public proof remain the separately approved M5-12/release work.
