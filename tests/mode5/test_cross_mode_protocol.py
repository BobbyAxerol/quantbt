"""Concrete review packets are private proposals, never execution permissions."""

from copy import deepcopy

import pytest

from tools.mode5_research.cross_mode.protocol import review_packet


def cell():
    return dict(cell_id='synthetic', source_refs=['reviewed-manifest'],
        candidate_ids=['candidate-%03d' % i for i in range(128)], reference_ids=['reference-0'],
        baseline={'selector': 'old'}, readiness={'known': 'blocked until separately admitted'},
        mode4_origins=[dict(cutoff='%s-01-01T00:00:00+00:00' % year, windows={'original': 'retained'})
            for year in (2022, 2024, 2026)],
        static_origins=[dict(cutoff=start, forward_start=start, forward_stop_exclusive=stop,
            development_start='2020-01-01T00:00:00+00:00') for start,stop in (
            ('2023-01-01T00:00:00+00:00','2024-01-01T00:00:00+00:00'),
            ('2024-01-01T00:00:00+00:00','2024-12-31T00:00:00+00:00'),
            ('2025-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'))])


def test_packet_counts_private_status_and_leap_calendar_are_explicit():
    item = cell()
    packet = review_packet([item], snapshot_id='a'*64)
    assert packet['private_only'] is True and packet['public_export_allowed'] is False
    assert packet['status'] == 'PROPOSED_FOR_OWNER_REVIEW'
    assert packet['sampler']['proposal_cap'] == 2048
    assert packet['chronology']['prefix_proposal_cap'] == 1536
    assert packet['chronology']['forward_reference_account_cap'] == 96
    assert packet['selection']['optimizer_proposals'] == 0
    assert not packet['automatic_next_phase'] and not packet['production_adoption']
    item['candidate_ids'].clear()
    assert len(packet['cells'][0]['candidate_ids']) == 128


@pytest.mark.parametrize('field,value', [('source_refs', []), ('reference_ids', []),
    ('candidate_ids', ['one']), ('baseline', None), ('readiness', None), ('mode4_origins', None)])
def test_incomplete_protocol_cannot_be_sealed(field, value):
    item = cell()
    item[field] = value
    with pytest.raises(ValueError):
        review_packet([item], snapshot_id='a'*64)


def test_duplicate_or_shortened_horizons_fail_before_any_execution():
    item = cell()
    item['static_origins'][1] = deepcopy(item['static_origins'][0])
    with pytest.raises(ValueError, match='nonoverlapping'):
        review_packet([item], snapshot_id='a'*64)
    item = cell()
    item['static_origins'][0]['forward_stop_exclusive'] = '2023-06-01T00:00:00+00:00'
    with pytest.raises(ValueError):
        review_packet([item], snapshot_id='a'*64)
    with pytest.raises(ValueError, match='snapshot'):
        review_packet([cell()], snapshot_id=None)


def test_unlisted_extra_source_or_outcome_payload_is_not_accepted():
    item = cell()
    item['strategy_source'] = 'private source must never become a public packet field'
    with pytest.raises(ValueError, match='concrete roster'):
        review_packet([item], snapshot_id='a'*64)
