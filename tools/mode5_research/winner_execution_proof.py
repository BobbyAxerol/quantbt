"""Registered bounded synthetic proof, with cumulative measured owner calls."""

from dataclasses import replace
import argparse
import json
from pathlib import Path
import resource
import shutil
from time import perf_counter
from unittest.mock import patch

import numpy as np
import optuna

from quantbt import QuantBTEndpoint
from quantbt.diagnostics import WinnerQualificationRequest, WinnerStateView
from quantbt.diagnostics.evidence import FrozenBuffer
from quantbt.mode5.artifacts import write_json


def _resources(directory):
    memory = {line.split(':')[0]: int(line.split()[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines() if line.split()[1].isdigit()}
    if memory['MemAvailable'] < 512 * 1024**2 or shutil.disk_usage(directory).free < 5 * 1024**3:
        raise RuntimeError('registered RAM/disk reserve unavailable; no financial launch')
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 768 * 1024:
        raise RuntimeError('registered owned process RSS cap exceeded')


def prove(workdir, ledger):
    from examples.mode5_cross_mode_qualification import run_demo
    workdir, ledger = Path(workdir), Path(ledger)
    if workdir.exists():
        raise ValueError('new proof directory required; no implicit retry or receipt overwrite')
    history = json.loads(ledger.read_text()) if ledger.exists() else dict(
        schema='quantbt.m51115.actual_owner_work.v1', proposals=0, financial_invocations=0, attempts=[])
    events = ledger.with_suffix('.events')
    events.mkdir(parents=True, exist_ok=True)
    snapshots = sorted(events.glob('*.json'))
    if snapshots:
        history = json.loads(snapshots[-1].read_text())
    sequence = len(snapshots)

    def persist():
        nonlocal sequence
        sequence += 1
        write_json(events / f'{sequence:04d}.json', history)
    attempted = dict(workdir=str(workdir), proposals=0, financial_invocations=0, status='STARTED')
    history['attempts'].append(attempted)
    if not ledger.exists():
        write_json(ledger, history)
    persist()
    original_ask, original_run = optuna.study.Study.ask, QuantBTEndpoint._run_single

    def guarded(kind, ceiling, original):
        def call(*args, **kwargs):
            _resources(ledger.parent)
            if history[kind] >= ceiling:
                raise RuntimeError('registered cumulative work cap exceeded: ' + kind)
            history[kind] += 1
            attempted[kind] += 1
            persist()
            return original(*args, **kwargs)
        return call

    started = perf_counter()
    try:
        with patch.object(optuna.study.Study, 'ask', guarded('proposals', 48, original_ask)), \
                patch.object(QuantBTEndpoint, '_run_single', guarded('financial_invocations', 80, original_run)):
            outcome = run_demo(workdir, donor_folds=(0,))
        # Same owner through all three accessors, including state attribution.
        completed = outcome['completed']['challenger']
        inputs = outcome['challenger']
        context = completed['context']
        base = outcome['completed']['baseline']['context']
        witness = context.pack.record.data['binding']['continuous']['witness']
        from quantbt.diagnostics import AccessWitness
        witness = AccessWitness(**witness)
        access = replace(inputs['access'], purpose='diagnostic')
        daily_count = len(completed['result'].equity.index.normalize().unique())
        view = WinnerStateView('synthetic-cycle-not-economic-regimes',
            FrozenBuffer.from_array('synthetic-state-labels', np.arange(daily_count, dtype=np.int64) % 3 - 1),
            witness, 'registered-public-synthetic-label-design', ((-1, 'unknown'), (0, 'state-a'), (1, 'state-b')))
        request = WinnerQualificationRequest(current=context, baseline=base, state_views=(view,))
        kwargs = dict(access=access, witness=witness, source_ref=context.source_ref)
        result_report = completed['result'].research_report(**kwargs, role=witness.role, qualification=request)
        pack_report = context.pack.winner_report(completed['result'], **kwargs, request=request)
        if pack_report != result_report:
            raise ValueError('same request differs between original result and pack')
        report_data = result_report.record.data
        profile = report_data['account']['profile']
        groups = profile['states']['families'][0]['groups']
        # Existing monetary attribution owner already checks conservation; keep
        # the actual state output rather than rebuilding a financial path.
        if not groups or report_data['baseline']['status'] != 'SOURCE_BOUND_SELECTED_PATHS':
            raise ValueError('nonvacuous state/baseline account evidence required')
        write_json(workdir / 'state-winner-report.json', report_data)
        (workdir / 'state-winner-report.md').write_text(result_report.to_markdown(private=True), encoding='utf-8')
        attempted.update(status='PASS_SOURCE_MECHANICS', summary=outcome['summary'],
            account_hashes_matched=True, state_families=1,
            accessor_report_identity=result_report.identity,
            baseline_activity=report_data['baseline']['baseline_activity']['status'])
    except Exception as error:
        attempted.update(status='FAIL_RETAINED', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        attempted.update(elapsed_seconds=perf_counter() - started,
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        persist()
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workdir', required=True, type=Path)
    parser.add_argument('--ledger', required=True, type=Path)
    args = parser.parse_args()
    result = prove(args.workdir, args.ledger)
    print(result['attempts'][-1]['status'], 'proposals=', result['proposals'],
        'financial_invocations=', result['financial_invocations'])


if __name__ == '__main__':
    main()
