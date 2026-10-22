"""One compact readable view of the same immutable qualification record."""

import html
import json


def _cell(value):
    return html.escape(json.dumps(value, ensure_ascii=True)).replace('|', '&#124;')


def _table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
        '| ' + ' | '.join('---' for _ in headers) + ' |',
        *['| ' + ' | '.join(_cell(v) for v in row) + ' |' for row in rows]])


def _detail(value):
    return '<pre>' + html.escape(json.dumps(value, indent=2, ensure_ascii=True)) + '</pre>'


def render(report, *, private=False):
    from quantbt.mode5.decision_report import DecisionReport
    from quantbt.mode5.dossier.records import Record
    data = report.to_dict(private=private)
    original = DecisionReport(Record.of(report.record.data['original_decision']))
    sections = ['# Winner Qualification', original.to_markdown(private=private),
        '## Evidence Coverage', _table(['Section', 'Status', 'Support', 'Limit'],
            [(r['section'], r['status'], r.get('support', 'REDACTED'), r.get('limitation', 'REDACTED'))
             for r in data['coverage']])]
    if not private:
        sections.append('Private source-bound evidence requires explicit private=True disclosure.')
        return '\n\n'.join(sections)
    explanation = data['explanation']
    from .contracts import selected_row
    winner = selected_row(original)
    if winner is not None:
        sections += ['## Winner Whole And Annual Outcomes',
            _table(['View', 'Daily Support', 'Net Return', 'Sharpe', 'DD', 'Daily Loss ES', 'Utility', 'Gate Support/Risk/Quality'],
                [(r.get('environment_id'), r.get('daily_count'), r.get('net_return'), r.get('raw_sharpe'),
                    r.get('max_drawdown'), r.get('daily_loss_es'), r.get('utility'),
                    [r.get('support_pass'), r.get('risk_pass'), r.get('quality_pass')])
                 for r in [*([winner['whole_observation']] if winner.get('whole_observation') else []), *winner['observations']]]),
            '## Calendar Consistency (Not Independent Market Regimes)', _detail(data['annual_summary'])]
    sections += ['## Numeric Decision Comparisons',
        _table(['Comparator', 'Candidate', 'Metric', 'Unit', 'Winner', 'Comparator Value', 'Delta', 'Reason'],
            [(c['name'], c.get('candidate_id'), r['metric'], r['unit'], r['winner'], r['comparator'], r['delta'], r['reason'])
             for c in explanation['comparisons'] for r in c.get('whole', [])]),
        '## Account And State Attribution', _detail(data['account']),
        '## Exact Winner Probe And Stress Evidence',
        _detail(data['checks']), '## Registered Baseline',
        _detail({k: v for k, v in data['baseline'].items() if k != 'baseline_decision'}),
        '## Interpretation Limits', *[html.escape(str(v)) for v in data['limits']]]
    return '\n\n'.join(sections)
