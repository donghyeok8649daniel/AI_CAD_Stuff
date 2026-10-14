from copy import deepcopy
from decimal import Decimal
import json
import math
import pytest
from cadstudio.pcb import (PCBProject,PCBComponent,PCBQuote,PCBPin,PCBTrack,PCBPoint,
    divider_example,new_component,inspect_layout,pcb_digest,bom_report,bom_csv,segment_distance,pad_positions)
from cadstudio.pcb_simulation import simulate_pcb,spice_netlist
from cadstudio.pcb_plugin import execute,electrical_preview,design_digest,with_pcb
from cadstudio.models import Design,Project
from cadstudio.native.document import Document,read_project
from cadstudio.preview_metadata import geometry_key


def test_divider_actual_linear_result_and_layout():
    p=divider_example();before=pcb_digest(p);r=simulate_pcb(p)
    assert r['node_voltages_v']['OUT']['real']==pytest.approx(2.5)
    assert r['branches']['R1']['current_a']['real']==pytest.approx(.0025)
    assert r['branches']['R1']['absorbed_power_w']==pytest.approx(.00625)
    assert r['branches']['V1']['absorbed_power_w']==pytest.approx(-.0125)
    assert r['max_equation_residual']<1e-10 and not r['actual_hardware_verified']
    assert pcb_digest(p)==before and not inspect_layout(p)['findings']


def test_rc_ac_closed_form_dc_cap_open():
    p=divider_example().model_dump(mode='json');p['components'][2]=new_component('capacitor','C1',40,10).model_dump(mode='json');p['components'][2]['pins'][0]['net']='OUT';p['components'][2]['pins'][1]['net']='GND'
    project=PCBProject.model_validate(p);r=simulate_pcb(project,dict(analysis='ac',frequency_hz=1000))
    measured=r['node_voltages_v']['OUT'];expected=1/(1+1j*2*math.pi*1000*1000*1e-6)
    assert complex(measured['real'],measured['imag'])==pytest.approx(expected)
    assert simulate_pcb(project)['node_voltages_v']['OUT']['real']==pytest.approx(5)


@pytest.mark.parametrize('kind',['unsupported'])
def test_unmodeled_ic_blocks(kind):
    p=divider_example().model_dump(mode='json');p['components'].append(new_component(kind,'U1').model_dump(mode='json'))
    with pytest.raises(ValueError,match='Unsupported'):simulate_pcb(p)


def test_unconnected_floating_conflicting_and_backend_blocked():
    p=divider_example().model_dump(mode='json');p['components'][1]['pins'][0]['net']=None
    with pytest.raises(ValueError,match='Unconnected'):simulate_pcb(p)
    p=divider_example().model_dump(mode='json');p['nets'].extend(['FLOAT_A','FLOAT_B']);r=new_component('resistor','R9').model_dump(mode='json');r['pins'][0]['net']='FLOAT_A';r['pins'][1]['net']='FLOAT_B';p['components'].append(r)
    with pytest.raises(ValueError,match='Singular'):simulate_pcb(p)
    p=divider_example().model_dump(mode='json');v=deepcopy(p['components'][0]);v['ref']='V2';v['model']['dc_voltage_v']=7;p['components'].append(v)
    with pytest.raises(ValueError,match='Singular'):simulate_pcb(p)
    with pytest.raises(ValueError,match='no fallback'):simulate_pcb(divider_example(),backend='ngspice')


def test_simulation_cancel():
    count=[0]
    def cancel():
        count[0]+=1
        if count[0]>=3:raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):simulate_pcb(divider_example(),check=cancel)


def test_layout_real_connectivity_and_short_layer_handling():
    p=divider_example().model_dump(mode='json');p['tracks'][1]['points'][-1]['x_mm']=35
    assert 'unrouted_net' in {f['code'] for f in inspect_layout(p)['findings']}
    p=divider_example().model_dump(mode='json');p['tracks'].append(dict(id='CROSS',net='VIN',layer='F.Cu',width_mm=.25,points=[dict(x_mm=30,y_mm=3),dict(x_mm=30,y_mm=22)]))
    assert 'track_clearance' in {f['code'] for f in inspect_layout(p)['findings']}
    p['tracks'][-1]['layer']='B.Cu'
    assert 'track_clearance' not in {f['code'] for f in inspect_layout(p)['findings']}
    assert 'orphan_track' in {f['code'] for f in inspect_layout(p)['findings']}
    assert segment_distance((0,0),(10,0),(5,-2),(5,2))==0
    assert segment_distance((0,0),(2,0),(4,0),(6,0))==2


def test_edge_and_wrong_net_pad_check_rotation():
    p=divider_example().model_dump(mode='json');p['components'][0]['x_mm']=1
    assert 'pad_edge' in {f['code'] for f in inspect_layout(p)['findings']}
    p=divider_example().model_dump(mode='json');p['tracks'].append(dict(id='PAD',net='VIN',points=[dict(x_mm=42,y_mm=10),dict(x_mm=50,y_mm=10)]))
    assert 'track_pad_clearance' in {f['code'] for f in inspect_layout(p)['findings']}
    c=new_component('resistor');c.rotation_deg=90;p=PCBProject(components=[c]);pads=pad_positions(p)
    assert pads[0]['x']==pytest.approx(10) and pads[0]['y']==pytest.approx(8)


@pytest.mark.parametrize('mutate',[
    lambda p:p.update(width_mm=float('nan')),
    lambda p:p['nets'].append('GND'),
    lambda p:p['components'].append(deepcopy(p['components'][0])),
    lambda p:p['components'][0]['pins'][0].update(net='MISSING'),
    lambda p:p['components'][0]['pins'].append(deepcopy(p['components'][0]['pins'][0])),
    lambda p:p['components'][0]['model'].update(pin_a='MISSING'),
    lambda p:p.update(code='os.system'),
    lambda p:p['tracks'][0].update(layer='In1.Cu'),
])
def test_schema_rejects_bad_declarations(mutate):
    p=divider_example().model_dump(mode='json');mutate(p)
    with pytest.raises(ValueError):PCBProject.model_validate(p)


def test_quote_requires_source_and_unknown_is_not_zero():
    with pytest.raises(ValueError):PCBQuote(status='quoted',unit_price='2.1')
    with pytest.raises(ValueError):PCBQuote(status='unknown',unit_price='0')
    with pytest.raises(ValueError):PCBQuote(status='reference',unit_price='2',source_url='http://x',supplier='x',as_of='2026-10-14')
    p=divider_example();report=bom_report(p)
    assert report['budget_status']=='incomplete' and report['unknown_refs']==['V1','R1','R2'] and not report['known_subtotals']


def test_common_numeric_supply_net_and_numeric_pin_ids():
    raw=divider_example().model_dump(mode='json');raw['nets']=[n.replace('VIN','3V3_A') for n in raw['nets']]
    for c in raw['components']:
        for p in c['pins']:
            if p['net']=='VIN':p['net']='3V3_A'
    for t in raw['tracks']:
        if t['net']=='VIN':t['net']='3V3_A'
    assert '3V3_A' in PCBProject.model_validate(raw).nets
    assert simulate_pcb(raw)['node_voltages_v']['OUT']['real']==2.5


def test_bom_decimal_grouping_moq_currency_no_conversion_csv_escape():
    raw=divider_example().model_dump(mode='json');raw['budget']=dict(board_quantity=3,currency='KRW',limit='1')
    for c in raw['components']:
        c['quote']=dict(status='reference',unit_price='0.1',currency='KRW',as_of='2026-10-14',supplier='Test fixture only',source_url='https://example.com/quote',minimum_quantity=10,pack_quantity=4)
    report=bom_report(raw)
    assert report['known_subtotals']['KRW']=='2.4' and report['budget_status']=='over'
    # R1+R2 group together; MOQ rounded to twelve per group, no float rounding.
    assert len(report['rows'])==2 and all(row['purchase_quantity']==12 for row in report['rows'])
    raw['components'][0]['quote']['currency']='USD';raw['components'][0]['value']='=HYPERLINK("bad")'
    report=bom_report(raw);assert report['budget_status']=='incomplete' and set(report['known_subtotals'])=={'USD','KRW'}
    assert "'=HYPERLINK" in bom_csv(raw)


def test_legacy_design_history_save_reopen_undo_redo(tmp_path):
    old=Design(name='Keep CAD',parts=[]).model_dump(mode='json');assert 'pcb' not in old
    doc=Document();doc.commit(old,'base');base=doc.journal.data['cursor'];p=divider_example()
    checked=with_pcb(old,p,expected_digest=design_digest(old));doc.commit(checked,'PCB explicit',{'tool':'pcb-workspace'});latest=doc.journal.data['cursor']
    path=tmp_path/'board.pcad';doc.write(path);loaded=read_project(path);assert loaded.design.pcb.name==p.name
    assert doc.journal.at(base)==old and doc.journal.at(latest)['pcb']==p.model_dump(mode='json')
    assert geometry_key(old)==geometry_key(checked)
    stale=deepcopy(old);stale['name']='other'
    with pytest.raises(ValueError,match='Stale'):with_pcb(stale,p,expected_digest=design_digest(old))


def test_priced_pcb_python_snapshot_hash_history_and_reopen(tmp_path):
    p=divider_example().model_dump(mode='json');p['budget']['limit']='100.01'
    p['components'][1]['quote']=dict(status='reference',unit_price='0.123456',currency='USD',as_of='2026-10-14',supplier='Arithmetic fixture',source_url='https://example.com/quote')
    design=Design(pcb=PCBProject.model_validate(p),parts=[]);dump=design.model_dump()
    assert dump['pcb']['components'][1]['quote']['unit_price']=='0.123456'
    assert dump['pcb']['components'][1]['quote']['as_of']=='2026-10-14' and dump['pcb']['budget']['limit']=='100.01'
    assert len(design_digest(dump))==64;json.dumps(dump,allow_nan=False)
    doc=Document();doc.commit(Design(parts=[]),'base');doc.commit(design,'priced PCB')
    path=tmp_path/'priced.pcad';doc.write(path);loaded=read_project(path)
    assert loaded.design.pcb.components[1].quote.unit_price==Decimal('0.123456')
    assert loaded.design.pcb.budget.limit==Decimal('100.01') and len(design_digest(loaded.design.model_dump()))==64


def test_electrical_append_preserves_existing_and_conflict():
    from cadstudio.electrical import ElectricalWorkspace,evaluate_electrical
    original=ElectricalWorkspace(nodes=['GND','OLD'],components=[dict(id='old',name='Old resistor',kind='resistor',a='OLD',b='GND',resistance_ohm=100)]).model_dump(mode='json')
    before=deepcopy(original);result=electrical_preview(divider_example(),original)
    assert original==before and result['components'][0]==before['components'][0]
    assert set(result['nodes'])=={'GND','OLD','pcb_VIN','pcb_OUT'}
    with pytest.raises(ValueError,match='conflict'):electrical_preview(divider_example(),result)
    raw=divider_example().model_dump(mode='json');raw['components'].append(new_component('unsupported','U1').model_dump(mode='json'))
    preview=electrical_preview(raw);assert not preview['components'][-1]['analysis_enabled']
    assert all(c['id'].startswith('pcb_') for c in preview['components'])


def test_actual_small_cad_solid_preview_reused_for_pcb_only():
    from cadstudio.kernel import preview
    from cadstudio.preview_metadata import reuse_preview
    # Match MainWindow/Document's validated, serialized current CAD snapshot.
    design=Design.model_validate(Design(name='Small CAD proof',parts=[dict(id='plate',name='Plate',geometry=dict(kind='plate',length=10,width=8,thickness=2,hole_count=0))]).model_dump(mode='json'))
    result=preview(design);candidate=with_pcb(design.model_dump(mode='json'),divider_example(),expected_digest=design_digest(design.model_dump(mode='json')))
    cached=reuse_preview(candidate,design.model_dump(mode='json'),result)
    assert cached is not None and cached['meshes'][0]['vertices']==result['meshes'][0]['vertices']
    assert candidate.parts==design.parts and candidate.mates==design.mates


def test_explicit_dispatch_spice_bounded_and_advice_transport():
    from cadstudio.native.pcb_ai import review_pcb,advice_request
    from cadstudio.native.draft_control import DraftControl,DraftCancelled
    p=divider_example()
    with pytest.raises(ValueError,match='Unknown'):execute('auto_run',p)
    assert execute('validate',p)['status']=='valid' and '.op' in spice_netlist(p)
    calls=[]
    def fake(request,provider,model,**kw):
        calls.append((request,provider,model,kw));return 'AI proposal only'
    result=review_pcb(p,'검토',model='fixture-model',answer_fn=fake)
    assert result['advisory_only'] and calls[0][1]=='codex' and calls[0][3]['deadline']==180
    assert calls[0][0].current is None and calls[0][0].references
    assert len(advice_request(p,'검토').prompt)<=4000
    control=DraftControl();control.cancel()
    with pytest.raises(DraftCancelled):review_pcb(p,'검토','fixture-model',control=control,answer_fn=fake)
