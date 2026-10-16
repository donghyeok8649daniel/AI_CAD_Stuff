"""Small offline declarations; no real boards, network, GUI or hardware."""
from copy import deepcopy
import json
import pytest

from cadstudio.pcb import PCBProject, PCBComponent, PCBPin, PCBLibraryMetadata, PCBQuote, PCBTrack, pcb_digest
from cadstudio.pcb_embedded import search_embedded, catalog_product, component_from_catalog, bind_catalog_product, review_embedded, estimate_cost
from cadstudio.native.pcb_ai import cost_advice_request, review_cost
from cadstudio.native.draft_control import DraftControl, DraftCancelled


def footprint(ref='U1',x=10,**kw):
    raw=dict(ref=ref,footprint='explicit-2-pad-test',x_mm=x,y_mm=10,rotation_deg=0,
        body_width_mm=4,body_height_mm=2,pins=[dict(number='1',net='VCC',x_mm=-1,y_mm=0,diameter_mm=1,layers=['F.Cu']),
            dict(number='2',net='GND',x_mm=1,y_mm=0,diameter_mm=1,layers=['F.Cu'])])
    raw.update(kw);return raw


def metadata(**kw):
    raw=dict(geometry_complete_declared=True,coordinate_units='mm',pin1_number='1',mounted_side='F',
        orientation_reference='Physical pin1 mark, user declaration',body_height_mm=2,service_clearance_mm=1,
        pin_specs=[dict(number='1',role='power_in',operating_min_v=4.5,operating_max_v=5.5,
            operating_current_a=.4,ground_reference_net='GND'),dict(number='2',role='ground')])
    raw.update(kw);return raw


def board(components=None,**kw):
    return PCBProject(nets=['GND','VCC'],components=components or [],**kw)


def declared(ref='U1',x=10,**kw):
    return PCBComponent(**footprint(ref,x),library_metadata=metadata(**kw))


def quote(value='0.125',currency='USD',**kw):
    return PCBQuote(status='reference',unit_price=value,currency=currency,as_of='2026-01-01',supplier='Entered supplier',
        source_url='https://example.com/entered-quote',**kw)


def test_legacy_serialization_omits_optional_metadata_and_retains_exact_golden_fields():
    c=PCBComponent(ref='R1',pins=[PCBPin(number='1')])
    assert c.model_dump()==dict(ref='R1',value='',mpn='',footprint='declared-round-pads',footprint_basis='declared',source_url='',
        x_mm=10.,y_mm=10.,rotation_deg=0.,body_width_mm=4.,body_height_mm=2.,
        pins=[dict(number='1',name='',net=None,x_mm=0.,y_mm=0.,diameter_mm=1.,layers=['F.Cu'])],
        model=dict(kind='unsupported',pin_a=None,pin_b=None,resistance_ohm=None,capacitance_f=None,dc_voltage_v=None,ac_voltage_v=None,ac_phase_deg=0.),
        quote=PCBQuote().model_dump(),fitted=True)
    p=board([c]);raw=p.model_dump();assert 'layer_count' not in raw and 'library_metadata' not in raw['components'][0]
    assert pcb_digest(p)==pcb_digest(PCBProject.model_validate(raw))


def test_catalog_has_logical_references_not_xy_or_consumption():
    rows=search_embedded('Raspberry Pi 4');r=next(r for r in rows if r['catalog_id']=='rpi4b')
    assert r['operating_current_a'] is None and r['physical_pin_coordinates_verified'] is False
    assert r['verification_level']=='catalog_reference_only' and r['logical_pins']
    assert set(r['logical_pins'][0])=={'key','label','functions','kind'}
    with pytest.raises(ValueError):catalog_product('not-a-product')


def test_binding_requires_complete_user_geometry_and_preserves_original():
    raw=footprint();original=deepcopy(raw)
    with pytest.raises(ValueError,match='Acknowledge'):component_from_catalog('rpi4b',raw)
    missing=deepcopy(raw);del missing['pins'][0]['x_mm']
    with pytest.raises(ValueError,match='Every physical'):component_from_catalog('rpi4b',missing,library_metadata=metadata())
    bound=component_from_catalog('rpi4b',raw,library_metadata=metadata())
    assert bound.library_metadata.footprint_review_state=='user_declared' and bound.mpn=='4 Model B'
    assert raw==original and bound.pins==PCBComponent(**raw).pins
    p=board([PCBComponent(**raw)]);before=p.model_dump()
    after=bind_catalog_product(p,'U1','rpi4b',footprint=raw,library_metadata=metadata())
    assert after.components[0].library_metadata.catalog_id=='rpi4b' and p.model_dump()==before
    moved=deepcopy(raw);moved['x_mm']=11
    with pytest.raises(ValueError,match='cannot move'):bind_catalog_product(p,'U1','rpi4b',footprint=moved,library_metadata=metadata())


def test_source_review_requires_record_and_unknown_geometry_survives_edit():
    with pytest.raises(ValueError):PCBLibraryMetadata(**metadata(footprint_review_state='source_reviewed'))
    meta=PCBLibraryMetadata(**metadata(geometry_complete_declared=False))
    assert not meta.geometry_complete_declared and meta.footprint_review_state=='user_declared'
    good=metadata(footprint_review_state='source_reviewed',source_url='https://example.com/drawing',revision='R1',reviewed_by='Reviewer',reviewed_date='2026-10-16',review_note='Exact revision reviewed')
    assert PCBLibraryMetadata(**good).footprint_review_state=='source_reviewed'


def test_rebinding_resets_previous_purchase_identity_quote():
    raw=footprint(mpn='different module',quote=quote().model_dump())
    bound=component_from_catalog('rpi4b',raw,library_metadata=metadata())
    assert bound.quote.status=='unknown' and bound.quote.unit_price is None


def test_declared_voltage_differential_current_limits_and_unfitted_load():
    c=declared();p=board([c]);conditions={'VCC':dict(voltage_v=6,source_current_limit_a=.3),'GND':dict(voltage_v=0)}
    result=review_embedded(p,net_conditions=conditions)
    assert any(c['name']=='pin_voltage' and c['status']=='violation' for c in result['checks'])
    assert any(c['name']=='current_budget' and c['status']=='violation' for c in result['checks'])
    assert not result['physical_safety_qualified'] and result['unknowns']>0
    # Equal net and return potential gives zero differential, not a false 5V pass.
    equal=review_embedded(p,net_conditions={'VCC':dict(voltage_v=5),'GND':dict(voltage_v=5)})
    assert any(c['name']=='pin_voltage' and c['status']=='violation' for c in equal['checks'])
    p.components[0].fitted=False
    unpopulated=review_embedded(p,net_conditions=conditions)
    assert not any(c['name']=='current_budget' and c['status']=='violation' for c in unpopulated['checks'])


def test_unmodeled_loads_and_output_pin_limit_never_disappear():
    consumer=declared();unknown=PCBComponent(**footprint('U2',20))
    p=board([consumer,unknown]);conditions={'VCC':dict(voltage_v=5,source_current_limit_a=2),'GND':dict(voltage_v=0)}
    result=review_embedded(p,net_conditions=conditions)
    assert any(c['name']=='current_budget' and c['refs']==['VCC'] and c['status']=='unknown' for c in result['checks'])
    source=declared('U3',30);source.library_metadata.pin_specs[0].role='power_out';source.library_metadata.pin_specs[0].current_limit_a=.01
    result=review_embedded(board([consumer,source]),net_conditions=conditions)
    assert any(c['name']=='output_current_limit' and c['status']=='violation' for c in result['checks'])
    missing=review_embedded(board([consumer]),net_conditions={'VCC':dict(voltage_v=5)})
    assert any(c['name']=='pin_voltage' and c['status']=='unknown' for c in missing['checks'])


def test_source_psu_advice_is_not_parsed_and_conditions_are_bounded():
    c=declared();c.library_metadata.pin_specs[0].operating_current_a=None
    c.library_metadata.review_note='Recommended PSU 3A, absolute maximum 8V'
    result=review_embedded(board([c]),net_conditions={'VCC':dict(voltage_v=5,source_current_limit_a=3),'GND':dict(voltage_v=0)})
    assert any(c['name']=='current_budget' and c['refs']==['VCC'] and c['status']=='unknown' for c in result['checks'])
    with pytest.raises(ValueError):review_embedded(board(),net_conditions={'VCC':dict(source_url='file:///private')})
    with pytest.raises(ValueError):review_embedded(board(),net_conditions={'VCC':dict(condition={})})


def test_large_layout_does_not_run_unbounded_drc(monkeypatch):
    import cadstudio.pcb_embedded as module
    p=board();p.tracks=[PCBTrack(id='T'+str(i),net='GND',points=[dict(x_mm=1,y_mm=1),dict(x_mm=2,y_mm=1)]) for i in range(513)]
    monkeypatch.setattr(module,'inspect_layout',lambda _:pytest.fail('unbounded DRC entered'))
    result=review_embedded(p)
    assert result['layout']['status']=='not_run_resource_limit'
    assert any(c['name']=='copper_geometry' and c['status']=='unknown' for c in result['checks'])


def test_exact_cost_pack_rounding_unknown_currency_and_parent_projection():
    a=declared('A',10);a.mpn='module';a.quote=quote('0.125',minimum_quantity=3,pack_quantity=2)
    b=declared('B',20,bom_role='internal_model',module_parent_ref='A');b.quote=quote('999')
    p=board([a,b]);original=p.model_dump()
    cost=estimate_cost(p)
    assert cost['excluded_internal_models']==[dict(ref='B',purchased_parent='A')]
    assert len(cost['rows'])==1 and cost['rows'][0]['purchase_quantity']==4
    assert cost['known_subtotals']=={'USD':'0.50'} and cost['complete_total'] is None
    assert not cost['estimated_complete'] and p.model_dump()==original
    p.components[0].fitted=False
    orphan=estimate_cost(p);assert orphan['ownership_unknown_refs']==['B'] and not orphan['component_prices_complete']
    p.components[0].fitted=True;p.components[1].library_metadata=PCBLibraryMetadata(**metadata());p.components[1].quote=quote('0.125','EUR')
    split=estimate_cost(p);assert split['known_subtotals']=={'EUR':'0.13','USD':'0.50'} and split['single_currency_component_total'] is None
    p.components[1].quote=PCBQuote();assert estimate_cost(p)['unknown_refs']==['B']


def test_module_references_and_cycles_rejected():
    a=declared('A',10,bom_role='internal_model',module_parent_ref='B')
    with pytest.raises(ValueError):board([a])
    b=declared('B',20,bom_role='internal_model',module_parent_ref='A')
    with pytest.raises(ValueError):board([a,b])
    with pytest.raises(ValueError):PCBLibraryMetadata(**metadata(module_parent_ref='A'))


def test_quantity_tiers_provenance_and_package_changes():
    a=declared();a.mpn='P';a.quote=quote('1',minimum_quantity=3,pack_quantity=2)
    p=board([a]);tier=dict(minimum_quantity=4,unit_price='0.125')
    result=estimate_cost(p,quantity_breaks={'P':[tier]})
    assert result['known_subtotals']=={'USD':'0.50'} and result['rows'][0]['quote']['as_of']=='2026-01-01'
    for bad in ([dict(tier,pack_quantity=100)],[None]):
        with pytest.raises(ValueError):estimate_cost(p,quantity_breaks={'P':bad})
    with pytest.raises(ValueError):estimate_cost(p,rounding='1e-100000')
    with pytest.raises(ValueError):estimate_cost(p,quantity_breaks={'P':[tier], 'U1':[]})


def test_cost_request_is_compact_no_full_pcb_or_local_paths():
    a=declared();a.library_metadata.catalog_id='rpi4b';a.quote=quote(note='C:\\Users\\someone\\private.txt')
    p=board([a]);req=cost_advice_request(p,'Quote C:/Users/someone/private.txt')
    payload=''.join(r.text for r in req.references);context=json.loads(payload)
    assert req.current is None and 'private.txt' not in payload+req.prompt
    assert not {'pcb','components','tracks','pins','zones','nets'} & context.keys()
    assert context['catalog_references'][0]['catalog_id']=='rpi4b' and context['additional_costs']['shipping'] is None
    assert all('logical_pins' not in row for row in context['catalog_references'])


def test_cost_subscription_transport_advisory_cancel_and_stale_snapshot():
    p=board([declared()]);seen=[]
    def answer(req,provider,model,**kw):seen.append((provider,model,kw));return 'Stored quotes only'
    result=review_cost(p,'Review cost','test-model',answer_fn=answer)
    assert seen[0][0]=='codex' and result['advisory_only'] and not result['prices_verified']
    control=DraftControl();control.cancel()
    with pytest.raises(DraftCancelled):review_cost(p,'Review cost','test-model',control=control,answer_fn=answer)
    def cancels(*args,**kwargs):kwargs['control'].cancel();return 'ignored'
    with pytest.raises(DraftCancelled):review_cost(p,'Review cost','test-model',answer_fn=cancels)
    def edits(*args,**kwargs):p.name='new board';return 'stale'
    with pytest.raises(ValueError,match='changed'):review_cost(p,'Review cost','test-model',answer_fn=edits)


@pytest.mark.parametrize('field,value',[('pins','not-pads'),('pins',[None])])
def test_malformed_footprints_fail_as_bounded_validation_errors(field,value):
    raw=footprint();raw[field]=value
    with pytest.raises(ValueError):component_from_catalog('rpi4b',raw,library_metadata=metadata())


def test_malformed_metadata_and_rounding_are_validation_errors():
    with pytest.raises(ValueError):component_from_catalog('rpi4b',footprint(),library_metadata=['bad'])
    with pytest.raises(ValueError):component_from_catalog('rpi4b',footprint(),library_metadata=metadata(pin_specs=[None]))
    with pytest.raises(ValueError):estimate_cost(board(),rounding='not-decimal')
