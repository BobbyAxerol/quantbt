"""Cold verification/benchmark of an explicitly named retained DecisionReport.

No nested receipt, market, private alpha or optimizer imports. Missing financial
paths remain missing rather than getting reconstructed by execution.
"""

from dataclasses import asdict
from pathlib import Path
from time import perf_counter
import argparse
import resource
import statistics

from quantbt.diagnostics import (
    AccessPolicy, AccessWitness, WinnerQualificationReport, WinnerQualificationRequest,
)
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.decision_report import DecisionReport


def certify(path, output, *, repeats=5):
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError('one to ten registered cold report repeats required')
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('bounded regular original DecisionReport required')
    before = file_identity(path)
    decision = DecisionReport.from_json(path.read_text(encoding='utf-8'))
    scope = decision.record.data['runtime']['account_scope']
    # Current retrospective reporting permission, not historical selection rights.
    ready = path.stat().st_mtime_ns
    witness = AccessWitness('retained-winner-current-source', 'diagnostic_development',
        scope['scored_start_ns'], scope['scored_stop_ns'], max(ready, scope['scored_stop_ns']))
    access = AccessPolicy('retrospective-winner-readback', (witness.role,),
        (witness.manifest_id,), witness.ready_ns + 1, 'diagnostic')
    inputs = dict(access=access, witness=witness, source_ref=before['sha256'],
        request=WinnerQualificationRequest(include_account=False))
    timings = []
    identities = set()
    for _ in range(repeats):
        started = perf_counter()
        report = WinnerQualificationReport.build(decision, **inputs)
        payload = report.to_json(private=True)
        WinnerQualificationReport.from_json(payload, expected_identity=report.identity)
        report.to_markdown(private=True)
        timings.append(perf_counter() - started)
        identities.add(report.identity)
    if len(identities) != 1 or before != file_identity(path):
        raise ValueError('retained source or deterministic report identity changed')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_json(output / 'winner-private.json', report.to_dict(private=True))
    write_json(output / 'winner-public.json', report.to_dict())
    (output / 'winner-private.md').write_text(report.to_markdown(private=True), encoding='utf-8')
    receipt = dict(schema='quantbt.m51115.retained_winner_proof.v1', status='PASS_COLD_SOURCE_READBACK',
        source=before, witness=asdict(witness), report_identity=report.identity,
        report_bytes=len(payload.encode()), financial_invocations=0, optimizer_proposals=0,
        model_fits=0, repeats=repeats, cold_assembly_reload_render_seconds=timings,
        median_seconds=statistics.median(timings), process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        coverage=report.record.data['coverage'], independent_oos=False,
        limitation='No current raw account/state/probe sources supplied; missing checks remain explicit')
    write_json(output / 'receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decision', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    receipt = certify(args.decision, args.output)
    print(receipt['status'], 'median_seconds=', receipt['median_seconds'],
        'report_bytes=', receipt['report_bytes'])


if __name__ == '__main__':
    main()
