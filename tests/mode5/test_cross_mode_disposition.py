"""Cold handoff checks never replace an unperformed market experiment."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import random
import subprocess
import sys

import pytest

from tools.mode5_research.cross_mode.disposition import (
    GATE_IDS, GateDisposition, MethodDisposition, no_finance_handoff, restore_no_finance_handoff,
)
from tools.mode5_research.cross_mode.inventory import FilePin, identity


def pin():
    return FilePin("synthetic/receipt.json", 17, "a" * 64)


def gate(number):
    whole = number < 37
    return GateDisposition(f"XMR-{number:03d}", "NEW_WHOLE_PROCEDURE" if whole else "COLD_DISPOSITION",
        "DEFERRED_APPROVED" if whole else "VERIFIED_COLD", "explicit approved scope", (pin(),))


def method(**changes):
    return replace(MethodDisposition("synthetic", "sampler-initialization-v1", "KEEP_BASELINE",
                                    "DESCRIPTIVE", "same objective not improved", (pin(),)), **changes)


def packet(**changes):
    kwargs=dict(snapshot_id="b"*64, approval=pin(), gates=tuple(gate(n) for n in range(31,41)),
                methods=(method(),), upstream_blockers=("uncompleted earlier empirical coverage",))
    kwargs.update(changes)
    return no_finance_handoff(**kwargs)


def test_full_gate_roster_cannot_be_confused_with_full_empirical_pass():
    result=packet()
    assert {g['gate_id'] for g in result['gates']}==set(GATE_IDS)
    assert result['whole_procedure_qualification']=='NOT_EVALUATED'
    assert result['current_work']==dict(optimizer_proposals=0,financial_invocations=0,model_fits=0,
                                       new_forward_days=0,new_qualified_origins=0)
    assert not result['economic_superiority_certified'] and not result['independent_validation']
    assert result['private_only'] and not result['public_export_allowed']


@pytest.mark.parametrize('status',['VERIFIED_COLD','VERIFIED_EXISTING','BLOCKED_UPSTREAM','PASS'])
def test_whole_procedure_may_not_be_upgraded_by_cold_evidence(status):
    with pytest.raises(ValueError):
        replace(gate(31),status=status)


@pytest.mark.parametrize('change',[{'scope':'ARCHIVED_SUBSCOPE'},{'scope':'NEW_WHOLE_PROCEDURE'},
                                   {'gate_id':'XMR-999'},{'reason':''},{'evidence':()}])
def test_unknown_or_misattributed_verified_gate_rejected(change):
    with pytest.raises(ValueError):
        replace(gate(40),**change)


def test_existing_evidence_remains_a_subscope_not_new_validation():
    row=GateDisposition('XMR-032','ARCHIVED_SUBSCOPE','VERIFIED_EXISTING',
                        'old actual prefix boundary proof only',(pin(),))
    result=packet(gates=(row,)+tuple(gate(n) for n in range(31,41) if n!=32))
    assert result['whole_procedure_qualification']=='NOT_EVALUATED'
    with pytest.raises(ValueError):
        replace(row,scope='NEW_WHOLE_PROCEDURE')


@pytest.mark.parametrize('missing',[31,35,40])
def test_missing_or_duplicated_gate_is_not_hidden_by_count(missing):
    rows=tuple(gate(n) for n in range(31,41) if n!=missing)
    with pytest.raises(ValueError):
        packet(gates=rows)
    with pytest.raises(ValueError):
        packet(gates=rows+(gate(32 if missing!=32 else 33),))


@pytest.mark.parametrize('decision',['PROMOTE','SUPPORTED_IN_REGISTERED_SCOPE','AUTO_ROUTE'])
def test_no_finance_scope_cannot_activate_a_method(decision):
    with pytest.raises(ValueError):
        method(decision=decision)


def test_method_support_and_duplicate_policy_are_explicit():
    with pytest.raises(ValueError):
        method(support='INDEPENDENT_VALIDATION')
    with pytest.raises(ValueError):
        packet(methods=(method(),method()))
    result=packet(upstream_blockers=())
    assert not result['package_entry_authorized'] and not result['parent_research_accepted']


@pytest.mark.parametrize('field,value',[
    ('whole_procedure_qualification','PASS'),('economic_superiority_certified',True),
    ('independent_validation',True),('parent_research_accepted',True),
    ('package_entry_authorized',True),('remote_or_release_authorized',True),
    ('public_defaults_changed',True),('public_export_allowed',True)])
def test_hash_recomputed_after_tampering_still_cannot_grant_authority(field,value):
    result=packet()
    result[field]=value
    result['disposition_id']=identity({k:v for k,v in result.items() if k!='disposition_id'})
    with pytest.raises(ValueError):
        restore_no_finance_handoff(result)


def test_roundtrip_is_deterministic_isolated_and_preserves_rng():
    state=random.getstate()
    result=packet()
    assert restore_no_finance_handoff(json.loads(json.dumps(result)))==result
    mutated=deepcopy(result)
    mutated['current_work']['financial_invocations']=1
    with pytest.raises(ValueError):
        restore_no_finance_handoff(mutated)
    assert packet()==result and random.getstate()==state
    with pytest.raises(FrozenInstanceError):
        method().decision='PROMOTE'


@pytest.mark.parametrize('bad',[None,FilePin('../escape',1,'a'*64),FilePin('/absolute',1,'a'*64),
                              FilePin('valid',True,'a'*64),FilePin('valid',1,'not-a-hash')])
def test_missing_or_malformed_authority_pin_is_rejected(bad):
    with pytest.raises((ValueError,TypeError)):
        packet(approval=bad)


def test_receipt_reference_duplicates_and_unknown_payload_fields_fail():
    with pytest.raises(ValueError):
        replace(gate(40),evidence=(pin(),pin()))
    result=packet()
    result['private_alpha_source']='must not be accepted'
    with pytest.raises(ValueError):
        restore_no_finance_handoff(result)
    with pytest.raises(ValueError):
        packet(upstream_blockers=('same','same'))


@pytest.mark.parametrize('field,value', [('financial_invocations',False),('model_fits',0.0)])
def test_json_scalar_types_cannot_silently_change_work_counts(field,value):
    result=packet()
    result['current_work'][field]=value
    result['disposition_id']=identity({k:v for k,v in result.items() if k!='disposition_id'})
    with pytest.raises(ValueError):
        restore_no_finance_handoff(result)


def test_module_runs_without_importing_a_financial_or_optimizer_stack():
    code='''
import importlib.abc,sys
class DenyFinance(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'quantbt','optuna','numpy','pandas','_quantbt_native'}:
   raise AssertionError('cold reducer imported financial/numeric stack: '+fullname)
sys.meta_path.insert(0,DenyFinance())
from tools.mode5_research.cross_mode.disposition import no_finance_handoff
assert callable(no_finance_handoff)
'''
    subprocess.run([sys.executable,'-c',code],check=True,capture_output=True,text=True)
