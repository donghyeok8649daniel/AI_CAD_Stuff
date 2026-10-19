"""New integrated quote contracts; synthetic data, no Qt/GUI/provider/user files."""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import ast
import importlib.util
import sys

import pytest
from pydantic import ValidationError
from cadstudio.pcb import PCBComponent,PCBProject,PCBQuote,pcb_digest
from cadstudio.pcb_cost_workflow import (
    adopt_cost_proposal,estimate_saved_cost,read_cost_inputs,with_cost_inputs)

SOURCE=Path(__file__).resolve().parents[1]
WORK=SOURCE.parent.parent

def board(*,priced=False):
    terms=dict(currency='USD',as_of='2026-10-18',supplier='409 synthetic supplier',
        source_url='https://example.invalid/409/base-terms')
    quote=PCBQuote(status='reference',unit_price='10',**terms) if priced else PCBQuote(**terms)
    return PCBProject(name='409 synthetic contract',components=[PCBComponent(
        ref='U409',mpn='SYNTH-409',pins=[dict(number='1')],quote=quote)],
        budget=dict(board_quantity=2,currency='USD'))

def with_tier(project):
    return with_cost_inputs(project,dict(quantity_breaks={'U409':[dict(
        minimum_quantity=1,unit_price='3',currency='USD',status='reference',
        as_of='2026-10-18',supplier='409 synthetic tier supplier',
        source_url='https://example.invalid/409/tier-terms')]}))

def proposal(project,low='4',high='6'):
    actual=estimate_saved_cost(project)['rows'][0]
    return dict(schema_version=1,base_sha256=pcb_digest(project),summary='409 entered synthetic range only',
        status='ai_estimate',rows=[dict(refs=['U409'],mpn='SYNTH-409',
            required_quantity=actual['required_quantity'],purchase_quantity=actual['purchase_quantity'],
            minimum_unit_price=low,maximum_unit_price=high,currency='USD',as_of='2026-10-18',
            source_url='https://example.invalid/409/assumption',basis='Synthetic conditional range, no vendor claim',status='ai_estimate')])

def mutate_quote(project,field,value):
    raw=project.model_dump(mode='json');raw['components'][0]['quote'][field]=value
    return PCBProject.model_validate(raw)

def saved_payload(project):return read_cost_inputs(project).model_dump(mode='json')

@pytest.mark.parametrize('field,value',[
    ('currency','EUR'),('as_of','2026-10-19'),('source_url','https://example.invalid/409/base-revised')])
def test_integrated_tier_base_quote_context_changes_exclude_old_schedule_preserve_input(field,value):
    original=with_tier(board(priced=True));stored=saved_payload(original)
    assert estimate_saved_cost(original)['known_subtotals']=={'USD':'6.00'}
    changed=mutate_quote(original,field,value);report=estimate_saved_cost(changed)
    assert saved_payload(changed)==stored
    assert report['stale_quantity_break_keys']==['U409']
    assert 'context' in report['stale_quantity_breaks']['U409']
    assert report['known_subtotals']=={('EUR' if field=='currency' else 'USD'):'20.00'}
    assert report['range_contributions'][0]['kind']=='entered_quote'
    assert original.components[0].quote.currency=='USD'

@pytest.mark.parametrize('field,value',[
    ('currency','EUR'),('as_of','2026-10-19'),
    ('source_url','https://example.invalid/409/tier-revised'),('unit_price','7.5')])
def test_integrated_tier_edit_does_not_reconfirm_on_ordinary_save(field,value):
    original=with_tier(board());inputs=saved_payload(original);old_context=deepcopy(inputs['quantity_break_contexts'])
    inputs['quantity_breaks']['U409'][0][field]=value
    changed=with_cost_inputs(original,inputs)
    actual=saved_payload(changed)
    assert actual['quantity_break_contexts']==old_context
    assert actual['quantity_breaks']['U409'][0][field]==value
    report=estimate_saved_cost(changed)
    assert report['stale_quantity_break_keys']==['U409'] and report['known_subtotals']=={}
    assert report['conditional_ranges']=={} and report['unpriced_component_refs']==['U409']
    assert saved_payload(original)['quantity_breaks']['U409'][0]['unit_price']=='3'

@pytest.mark.parametrize('field,value',[
    ('currency','EUR'),('as_of','2026-10-19'),('source_url','https://example.invalid/409/base-revised')])
def test_integrated_ai_base_quote_context_stays_saved_but_cannot_price(field,value):
    initial=board();adopted=adopt_cost_proposal(initial,proposal(initial));stored=saved_payload(adopted)
    assert estimate_saved_cost(adopted)['conditional_ranges']=={'USD':{'minimum':'8.00','maximum':'12.00'}}
    changed=mutate_quote(adopted,field,value);report=estimate_saved_cost(changed)
    assert saved_payload(changed)==stored and len(stored['accepted_ai_estimates'])==1
    assert report['used_ai_estimates']==[] and report['conditional_ranges']=={}
    assert report['stale_ai_estimates'][0]['row']==stored['accepted_ai_estimates'][0]
    assert 'context' in report['stale_ai_estimates'][0]['reason']

@pytest.mark.parametrize('field,value',[
    ('maximum_unit_price','9'),('currency','EUR'),('basis','Edited saved assumption, still unconfirmed')])
def test_integrated_saved_ai_payload_edit_cannot_reuse_old_confirmation(field,value):
    initial=board();adopted=adopt_cost_proposal(initial,proposal(initial));inputs=saved_payload(adopted)
    contexts=deepcopy(inputs['accepted_ai_quote_contexts']);inputs['accepted_ai_estimates'][0][field]=value
    changed=with_cost_inputs(adopted,inputs);report=estimate_saved_cost(changed)
    assert saved_payload(changed)['accepted_ai_quote_contexts']==contexts
    assert saved_payload(changed)['accepted_ai_estimates'][0][field]==value
    assert report['conditional_ranges']=={} and report['used_ai_estimates']==[]
    assert len(report['stale_ai_estimates'])==1

def test_integrated_explicit_tier_rebind_restores_schedule_without_healing_ai():
    initial=with_tier(board());adopted=adopt_cost_proposal(initial,proposal(initial))
    changed=mutate_quote(adopted,'source_url','https://example.invalid/409/base-revised')
    before=saved_payload(changed);report=estimate_saved_cost(changed)
    assert report['stale_quantity_break_keys']==['U409'] and len(report['stale_ai_estimates'])==1
    rebound=with_cost_inputs(changed,before,rebind_quantity_breaks=True);after=saved_payload(rebound)
    report=estimate_saved_cost(rebound)
    assert report['stale_quantity_break_keys']==[] and report['known_subtotals']=={'USD':'6.00'}
    assert after['quantity_break_contexts']!=before['quantity_break_contexts']
    assert after['accepted_ai_quote_contexts']==before['accepted_ai_quote_contexts']
    assert after['accepted_ai_estimates']==before['accepted_ai_estimates']
    assert len(report['stale_ai_estimates'])==1 and report['used_ai_estimates']==[]

def test_integrated_stale_ai_requires_fresh_current_proposal_adoption():
    initial=board();old_proposal=proposal(initial);adopted=adopt_cost_proposal(initial,old_proposal)
    changed=mutate_quote(adopted,'source_url','https://example.invalid/409/base-revised')
    ordinary=with_cost_inputs(changed,saved_payload(changed),rebind_quantity_breaks=True)
    assert estimate_saved_cost(ordinary)['conditional_ranges']=={}
    with pytest.raises(ValueError,match='fresh cost proposal'):
        adopt_cost_proposal(ordinary,old_proposal)
    before=saved_payload(ordinary)
    fresh=adopt_cost_proposal(ordinary,proposal(ordinary,'1.25','1.75'));report=estimate_saved_cost(fresh)
    assert saved_payload(ordinary)==before
    assert report['stale_ai_estimates']==[] and len(report['used_ai_estimates'])==1
    assert report['conditional_ranges']=={'USD':{'minimum':'2.50','maximum':'3.50'}}
    assert saved_payload(fresh)['accepted_ai_quote_contexts']!=before['accepted_ai_quote_contexts']

def test_integrated_legacy_mapless_read_preserves_records_and_explicit_old_reader_boundary():
    initial=with_tier(board());current=adopt_cost_proposal(initial,proposal(initial))
    modern=saved_payload(current);legacy=deepcopy(modern)
    legacy.pop('quantity_break_contexts');legacy.pop('accepted_ai_quote_contexts')
    raw=current.model_dump(mode='json');raw['budget']['cost_inputs']=legacy
    loaded=PCBProject.model_validate(raw);ordinary=with_cost_inputs(loaded,legacy)
    assert saved_payload(ordinary)==legacy
    report=estimate_saved_cost(ordinary)
    assert report['stale_quantity_break_keys']==['U409'] and len(report['stale_ai_estimates'])==1
    assert report['conditional_ranges']=={} and report['known_subtotals']=={}
    assert len(saved_payload(loaded)['accepted_ai_estimates'])==1 and saved_payload(loaded)['quantity_breaks']
    old_path=WORK/'release341/source/cadstudio/pcb_cost_models.py'
    assert sha256(old_path.read_bytes()).hexdigest()=='47adb63509c268dd5fecebc37c66e6e9be6ad1f123a2b12e6cbb80cd8703726e'
    name='_cost_schema341_readonly_409';spec=importlib.util.spec_from_file_location(name,old_path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    try:
        spec.loader.exec_module(module)
        assert module.PCBCostInputs.model_validate(legacy).model_dump(mode='json')==legacy
        with pytest.raises(ValidationError) as error:module.PCBCostInputs.model_validate(modern)
        rejected={entry['loc'][0] for entry in error.value.errors() if entry['type']=='extra_forbidden'}
        assert {'quantity_break_contexts','accepted_ai_quote_contexts'}<=rejected
    finally:sys.modules.pop(name,None)

def test_integrated_native_report_labels_and_manifest_are_data_only():
    tree=ast.parse((SOURCE/'cadstudio/native/pcb_workbench.py').read_text(encoding='utf-8'))
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='PCBWorkbench')
    method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='cost_estimate')
    strings=[node.value for node in ast.walk(method) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
    assert 'stale_quantity_breaks' in strings and 'stale_ai_estimates' in strings
    assert any('재연결' in value for value in strings) and any('새로 생성' in value and '채택' in value for value in strings)
    plugin=ast.parse((SOURCE/'cadstudio/pcb_plugin.py').read_text(encoding='utf-8'))
    manifest=next(node.value for node in plugin.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='MANIFEST' for target in node.targets))
    fields={item.arg:item.value for item in manifest.keywords}
    geometry={item.arg:item.value for item in fields['geometry'].keywords}
    assert ast.literal_eval(geometry['copper_layers'])==[2,4,6,8]
    assert {item.arg:ast.literal_eval(item.value) for item in fields['permissions'].keywords}==dict(automatic_execution=False,network=False,filesystem=False,hardware=False)
    assert not any(name.startswith(('PySide6','vtkmodules','OCP','cadquery')) for name in sys.modules)
