"""Tiny persisted/fake-transport costs only; no GUI, API, OS or real projects."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import sys

import pytest

from cadstudio.pcb import PCBProject,PCBComponent,PCBQuote,pcb_digest
from cadstudio.pcb_cost_models import PCBCostInputs,CostAIProposal
from cadstudio.pcb_cost_workflow import (read_cost_inputs,with_cost_inputs,estimate_saved_cost,
    validate_cost_proposal,adopt_cost_proposal)
from cadstudio.native.pcb_ai import cost_advice_request,cost_proposal_request,propose_cost
from cadstudio.native.draft_control import DraftControl,DraftCancelled


def quote(value='10',**kw):
    return PCBQuote(status='reference',unit_price=value,currency='USD',as_of='2026-01-01',
        supplier='Entered supplier',source_url='https://example.com/dated-quote',**kw)


def board(known=False):
    return PCBProject(components=[PCBComponent(ref='U1',mpn='Known',pins=[dict(number='1')],quote=quote() if known else PCBQuote()),
        PCBComponent(ref='U2',mpn='Unknown',pins=[dict(number='1')],x_mm=20)])


def row(p,ref='U2',**kw):
    c=next(c for c in p.components if c.ref==ref)
    actual=next(r for r in estimate_saved_cost(p)['rows'] if r['refs']==[ref])
    value=dict(refs=[ref],mpn=c.mpn,required_quantity=actual['required_quantity'],purchase_quantity=actual['purchase_quantity'],
        minimum_unit_price='1',maximum_unit_price='2',currency='USD',as_of=None,source_url='',
        basis='Conditional range from the explicitly stated example assumption.',status='ai_estimate')
    value.update(kw);return value


def proposal(p,rows=None):
    return dict(schema_version=1,base_sha256=pcb_digest(p),rows=rows or [row(p)],summary='Conditional fixture estimate',status='ai_estimate')


@pytest.mark.parametrize('layers',[2,4])
def test_old_two_and_four_layer_default_snapshots_and_digest_exact(layers):
    expected=dict(schema_version=1,name='PCB 설계',width_mm=60.,height_mm=40.,thickness_mm=1.6,
        clearance_mm=.2,edge_clearance_mm=.5,nets=['GND'],components=[],tracks=[],
        simulation=dict(analysis='dc',frequency_hz=1000.),budget=dict(board_quantity=1,currency='KRW',limit=None))
    if layers==4:expected['layer_count']=4
    p=PCBProject.model_validate(expected)
    assert p.model_dump()==p.model_dump(mode='json')==expected
    golden=hashlib.sha256(json.dumps(expected,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    assert pcb_digest(p)==golden and read_cost_inputs(p).model_dump()==dict(quantity_breaks={},additional_costs={},accepted_ai_estimates=[])
    assert with_cost_inputs(p,None).model_dump()==expected


def test_persisted_tier_uses_MOQ_pack_and_exact_decimal_without_overwriting_actual_quotes():
    p=PCBProject(components=[PCBComponent(ref='R1',mpn='Shared',pins=[dict(number='1')],quote=quote('2',minimum_quantity=10,pack_quantity=4)),
        PCBComponent(ref='R2',mpn='Shared',pins=[dict(number='1')],quote=quote('2',minimum_quantity=10,pack_quantity=4))],budget=dict(board_quantity=3))
    before=p.model_dump();inputs=dict(quantity_breaks={'Shared':[dict(minimum_quantity=10,unit_price='1.250000',currency='USD',
        status='reference',as_of='2026-01-01',supplier='Entered tier supplier',source_url='https://example.com/tier')]})
    saved=with_cost_inputs(p,inputs);report=estimate_saved_cost(saved)
    assert p.model_dump()==before and saved.components[0].quote.unit_price==Decimal('2')
    assert report['rows'][0]['required_quantity']==6 and report['rows'][0]['purchase_quantity']==12
    assert report['known_subtotals']=={'USD':'15.00'} and report['conditional_ranges']=={'USD':{'minimum':'15.00','maximum':'15.00'}}
    encoded=json.dumps(saved.model_dump(),ensure_ascii=False)
    reopened=PCBProject.model_validate_json(encoded)
    assert reopened.model_dump()==saved.model_dump() and pcb_digest(reopened)==pcb_digest(saved)
    assert reopened.budget.cost_inputs.quantity_breaks['Shared'][0].unit_price==Decimal('1.250000')


def test_additional_ranges_keep_currencies_explicit_zero_and_missing_values_distinct():
    p=with_cost_inputs(PCBProject(),dict(additional_costs={
        'shipping':dict(minimum='0',maximum='0',currency='USD',basis='Explicit free shipping fixture'),
        'tax_import':dict(minimum='100.01',maximum='150.01',currency='KRW',basis='User conditional tax assumption')}))
    result=estimate_saved_cost(p)
    assert result['conditional_ranges']=={'KRW':{'minimum':'100.01','maximum':'150.01'},'USD':{'minimum':'0','maximum':'0'}}
    assert result['unknown_additional_costs']==['pcb_fabrication','assembly_consumables']
    assert result['complete_total'] is None and not result['estimated_complete'] and not result['conditional_inputs_complete']
    assert estimate_saved_cost(board())['conditional_ranges']=={}


def test_adopted_AI_fills_only_unknown_rows_known_quote_wins_and_undo_draft_is_detached():
    p=board(known=True);before=p.model_dump()
    proposed=proposal(p,[row(p,'U1',minimum_unit_price='100',maximum_unit_price='200'),row(p)])
    checked=validate_cost_proposal(p,proposed);adopted=adopt_cost_proposal(p,checked)
    assert p.model_dump()==before and adopted.components[0].quote==p.components[0].quote
    raw=read_cost_inputs(adopted).model_dump();raw['additional_costs']['shipping']=dict(minimum='5',maximum='7',currency='USD',basis='Entered shipping assumption')
    adopted=with_cost_inputs(adopted,raw);result=estimate_saved_cost(adopted)
    assert result['conditional_ranges']=={'USD':{'minimum':'16.00','maximum':'19.00'}}
    assert [r['refs'] for r in result['used_ai_estimates']]==[['U2']]
    assert result['ignored_ai_estimates'][0]['row']['refs']==['U1']
    assert result['unpriced_component_refs']==[] and result['unknown_additional_costs']
    restored=PCBProject.model_validate(before)
    assert restored.model_dump()==p.model_dump() and restored.budget.cost_inputs is None


@pytest.mark.parametrize('change',['mpn','ref','quantity','pack'])
def test_saved_AI_rows_remain_stored_but_are_stale_after_BOM_changes(change):
    p=adopt_cost_proposal(board(),proposal(board()))
    raw=p.model_dump()
    if change=='mpn':raw['components'][1]['mpn']='New SKU'
    elif change=='ref':raw['components'][1]['ref']='U3'
    elif change=='quantity':raw['budget']['board_quantity']=2
    else:raw['components'][1]['quote']['pack_quantity']=4
    changed=PCBProject.model_validate(raw);report=estimate_saved_cost(changed)
    assert len(changed.budget.cost_inputs.accepted_ai_estimates)==1
    assert len(report['stale_ai_estimates'])==1 and report['used_ai_estimates']==[]
    assert report['conditional_ranges']=={} and report['unpriced_component_refs']


@pytest.mark.parametrize('mutation',['stale','refs','mpn','quantity','negative','reversed','nan','currency','status','extra','source','date','basis','duplicate_ref','duplicate_row'])
def test_strict_proposal_validation_rejects_fabricated_or_stale_row_contract(mutation):
    p=board();value=proposal(p);r=value['rows'][0]
    if mutation=='stale':value['base_sha256']='0'*64
    elif mutation=='refs':r['refs']=['U99']
    elif mutation=='mpn':r['mpn']='Invented SKU'
    elif mutation=='quantity':r['purchase_quantity']=2
    elif mutation=='negative':r['minimum_unit_price']='-1'
    elif mutation=='reversed':r['minimum_unit_price']='3'
    elif mutation=='nan':r['minimum_unit_price']='NaN'
    elif mutation=='currency':r['currency']='usd'
    elif mutation=='status':r['status']='quoted'
    elif mutation=='extra':r['price_is_current_offer']=True
    elif mutation=='source':r['source_url']='file:///private'
    elif mutation=='date':r['as_of']='2300-01-01'
    elif mutation=='basis':r['basis']=' '
    elif mutation=='duplicate_ref':r['refs']*=2
    else:value['rows']*=2
    with pytest.raises(ValueError):validate_cost_proposal(p,value)


def test_saved_tier_stale_key_is_reported_not_a_file_loading_failure():
    p=with_cost_inputs(board(),dict(quantity_breaks={'Removed SKU':[dict(minimum_quantity=1,unit_price='0',currency='USD',
        as_of='2026-01-01',supplier='Entered supplier',source_url='https://example.com/tier')]}))
    assert estimate_saved_cost(p)['stale_quantity_break_keys']==['Removed SKU']
    assert PCBProject.model_validate_json(p.model_dump_json()).budget.cost_inputs is not None


def test_compact_proposal_transport_preserves_model_control_timeout_and_never_adopts():
    p=board();before=p.model_dump();control=DraftControl();seen=[]
    def answer(request,provider,model,**kw):
        seen.append((request,provider,model,kw));return json.dumps(proposal(p))
    packet=propose_cost(p,'입력 견적 조건만 검토','gpt-6.1-sol',effort='ultra',control=control,deadline=17,answer_fn=answer)
    assert packet['proposal']['rows'][0]['status']=='ai_estimate' and not packet['auto_applied'] and not packet['prices_verified']
    assert p.model_dump()==before and p.budget.cost_inputs is None
    assert seen[0][1:3]==('codex','gpt-6.1-sol') and seen[0][3]['control'] is control
    assert seen[0][3]['deadline']==17 and seen[0][3]['effort']=='ultra'
    text=''.join(ref.text for ref in seen[0][0].references)
    assert 'conditional_ranges' in text and 'accepted_ai_estimates' in text and '"nets"' not in text and '"pins"' not in text


@pytest.mark.parametrize('event',['cancel_before','cancel_after','change_during'])
def test_proposal_cancellation_and_stale_transport_never_return_an_adoptable_packet(event):
    p=board();control=DraftControl();called=[]
    if event=='cancel_before':control.cancel()
    def answer(*args,**kw):
        called.append(True);value=proposal(p)
        if event=='cancel_after':control.cancel()
        if event=='change_during':p.components[0].mpn='changed'
        return json.dumps(value)
    with pytest.raises(DraftCancelled if event.startswith('cancel') else ValueError):
        propose_cost(p,'Review','fixture-model',control=control,answer_fn=answer)
    assert bool(called)==(event!='cancel_before') and p.budget.cost_inputs is None


@pytest.mark.parametrize('text',['not JSON','{"rows":[],"rows":[]}','{"minimum":NaN}'])
def test_structured_transport_rejects_nonJSON_duplicates_and_nonfinite_numbers(text):
    p=board()
    with pytest.raises(ValueError):propose_cost(p,'Review','fixture',answer_fn=lambda *a,**kw:text)


def test_question_boundary_and_no_heavy_UI_or_kernel_imports():
    assert cost_proposal_request(board(),'x'*2500).current is None
    assert cost_advice_request(board(),'Review').current is None
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))


def ref_tier(p,key='U2'):
    return with_cost_inputs(p,dict(quantity_breaks={key:[dict(minimum_quantity=1,unit_price='3',currency='USD',
        as_of='2026-01-01',supplier='Entered supplier',source_url='https://example.com/tier')]}))


def test_ref_tier_identity_change_is_stale_until_explicit_rebind_without_quote_changes():
    p=ref_tier(board());assert estimate_saved_cost(p)['known_subtotals']=={'USD':'3.00'}
    raw=p.model_dump();raw['components'][1]['mpn']='Replacement SKU'
    changed=PCBProject.model_validate(raw);before=changed.components[1].quote.model_dump()
    result=estimate_saved_cost(changed)
    assert result['stale_quantity_break_keys']==['U2'] and result['known_subtotals']=={}
    assert PCBProject.model_validate_json(changed.model_dump_json()).budget.cost_inputs.quantity_breaks
    unconfirmed=with_cost_inputs(changed,read_cost_inputs(changed))
    assert estimate_saved_cost(unconfirmed)['stale_quantity_break_keys']==['U2']
    rebound=with_cost_inputs(changed,read_cost_inputs(changed),rebind_quantity_breaks=True)
    assert estimate_saved_cost(rebound)['known_subtotals']=={'USD':'3.00'}
    assert rebound.components[1].quote.model_dump()==before
    assert rebound.budget.cost_inputs.quantity_break_bindings['U2'].ref=='U2'


@pytest.mark.parametrize('field',['value','model','source_url','footprint'])
def test_empty_MPN_ref_identity_catches_value_model_source_and_package_changes(field):
    raw=board().model_dump();raw['components'][1]['mpn']=''
    p=ref_tier(PCBProject.model_validate(raw));raw=p.model_dump()
    if field=='model':raw['components'][1]['model']['kind']='none'
    else:raw['components'][1][field]={'value':'New value','source_url':'https://example.com/new-sku','footprint':'New package'}[field]
    result=estimate_saved_cost(PCBProject.model_validate(raw))
    assert result['stale_quantity_break_keys']==['U2'] and result['known_subtotals']=={}


def test_MPN_key_remains_applicable_as_quantities_change_and_pose_net_edits_do_not_stale_ref():
    p=ref_tier(board(),'Unknown');raw=p.model_dump();raw['budget']['board_quantity']=2
    assert estimate_saved_cost(PCBProject.model_validate(raw))['known_subtotals']=={'USD':'6.00'}
    p=ref_tier(board());raw=p.model_dump();raw['components'][1].update(x_mm=27,rotation_deg=90)
    raw['components'][1]['pins'][0]['net']='GND'
    assert estimate_saved_cost(PCBProject.model_validate(raw))['stale_quantity_break_keys']==[]


def test_unbound_ref_tier_requires_explicit_rebind_and_removed_schedule_drops_its_binding():
    p=ref_tier(board());raw=p.model_dump();raw['budget']['cost_inputs'].pop('quantity_break_bindings')
    unbound=PCBProject.model_validate(raw)
    assert estimate_saved_cost(unbound)['stale_quantity_break_keys']==['U2']
    assert estimate_saved_cost(with_cost_inputs(unbound,read_cost_inputs(unbound),rebind_quantity_breaks=True))['known_subtotals']=={'USD':'3.00'}
    values=read_cost_inputs(p).model_dump();values['quantity_breaks']={}
    cleared=with_cost_inputs(p,values)
    assert 'quantity_break_bindings' not in cleared.budget.cost_inputs.model_dump()


@pytest.mark.parametrize('field',['value','footprint'])
def test_empty_MPN_adopted_AI_estimate_identity_is_not_reused_after_product_change(field):
    raw=board().model_dump();raw['components'][1].update(mpn='',value='100 ohm',footprint='0805')
    p=PCBProject.model_validate(raw);saved=adopt_cost_proposal(p,proposal(p))
    assert estimate_saved_cost(saved)['used_ai_estimates']
    raw=saved.model_dump();raw['components'][1][field]='10 kohm' if field=='value' else '0402'
    changed=PCBProject.model_validate(raw);result=estimate_saved_cost(changed)
    assert result['stale_ai_estimates'] and result['used_ai_estimates']==[]
    assert result['conditional_ranges']=={} and changed.budget.cost_inputs.accepted_ai_estimates
    # Ordinary saving or the tier-only checkbox cannot silently heal AI ownership.
    checked=with_cost_inputs(changed,read_cost_inputs(changed),rebind_quantity_breaks=True)
    assert estimate_saved_cost(checked)['stale_ai_estimates']


def test_AI_estimate_pose_net_edits_remain_eligible_but_missing_local_binding_is_stale():
    p=board();p=adopt_cost_proposal(p,proposal(p));raw=p.model_dump()
    raw['components'][1].update(x_mm=27,rotation_deg=90);raw['components'][1]['pins'][0]['net']='GND'
    changed=PCBProject.model_validate(raw)
    assert estimate_saved_cost(changed)['used_ai_estimates'] and estimate_saved_cost(changed)['stale_ai_estimates']==[]
    raw['budget']['cost_inputs'].pop('accepted_ai_bindings')
    unbound=PCBProject.model_validate(raw)
    assert estimate_saved_cost(unbound)['stale_ai_estimates'] and estimate_saved_cost(unbound)['used_ai_estimates']==[]


def test_deeply_nested_cost_JSON_is_a_controlled_validation_error(monkeypatch):
    p=board();text='['*1500+'0'+']'*1500
    with pytest.raises(ValueError):
        propose_cost(p,'Review','fixture',answer_fn=lambda *a,**kw:text)
    from cadstudio.native import pcb_ai
    def recursion(*args,**kwargs):raise RecursionError('Owned decoder depth fixture')
    monkeypatch.setattr(pcb_ai.json,'loads',recursion)
    with pytest.raises(ValueError,match='strict JSON'):
        propose_cost(p,'Review','fixture',answer_fn=lambda *a,**kw:'{}')


def test_proposal_schema_version_requires_explicit_integer_not_bool_or_missing():
    p=board();value=proposal(p);value['schema_version']=True
    with pytest.raises(ValueError,match='explicit integer'):validate_cost_proposal(p,value)
    del value['schema_version']
    with pytest.raises(ValueError,match='explicit integer'):validate_cost_proposal(p,value)


def test_empty_unknown_price_response_is_reviewable_but_never_adoptable():
    p=board();before=p.model_dump();value=proposal(p);value['rows']=[];value['summary']='No supplied pricing basis; supplier and quantity terms remain unknown.'
    packet=propose_cost(p,'Review','fixture',answer_fn=lambda *a,**kw:json.dumps(value))
    assert packet['proposal']['rows']==[] and packet['proposal']['summary'] and not packet['auto_applied']
    assert validate_cost_proposal(p,packet['proposal']).rows==[]
    with pytest.raises(ValueError,match='No estimate rows'):adopt_cost_proposal(p,packet['proposal'])
    assert p.model_dump()==before and p.budget.cost_inputs is None
