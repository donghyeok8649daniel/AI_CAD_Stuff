"""Independent tiny regressions for declaration/current/BOM edge cases only."""
import pytest
from cadstudio.pcb import PCBProject, PCBComponent, PCBPin, PCBLibraryMetadata, PCBPinSpec, PCBDeviceModel
from cadstudio.pcb_embedded import review_embedded, estimate_cost


def part(ref,x,role='power_in',current=.4,limit=None,**kwargs):
    return PCBComponent(ref=ref,x_mm=x,y_mm=10,pins=[PCBPin(number='1',net='VCC',x_mm=-1),PCBPin(number='2',net='GND',x_mm=1)],
        library_metadata=PCBLibraryMetadata(pin_specs=[PCBPinSpec(number='1',role=role,operating_current_a=current,current_limit_a=limit,
            operating_min_v=4.5,operating_max_v=5.5,ground_reference_net='GND'),PCBPinSpec(number='2',role='ground')]),**kwargs)


def resistor():
    c=part('R1',20,role='passive',current=None)
    c.library_metadata.pin_specs[1].role='passive'
    c.model=PCBDeviceModel(kind='resistor',pin_a='1',pin_b='2',resistance_ohm=2)
    return c


def review(components,**rail):
    p=PCBProject(nets=['GND','VCC'],components=components)
    return review_embedded(p,net_conditions={'VCC':dict(voltage_v=5,source_current_limit_a=1,**rail),'GND':dict(voltage_v=0)})


def test_declared_passive_resistor_is_not_an_invisible_zero_current_load():
    result=review([part('U1',10),resistor()])
    rail=next(r for r in result['checks'] if r['name']=='current_budget' and r['refs']==['VCC'])
    assert rail['status']=='unknown' and rail['inputs']['operating_load_current_a'] is None
    assert not result['physical_safety_qualified']


@pytest.mark.parametrize('total,status',[(.8,'declared_check'),(2.9,'violation')])
def test_explicit_entire_load_declaration_stays_separate_from_unsolved_passive_network(total,status):
    result=review([part('U1',10),resistor()],declared_load_current_a=total)
    rail=next(r for r in result['checks'] if r['name']=='current_budget' and r['refs']==['VCC'])
    assert rail['status']==status and rail['inputs']['operating_load_current_a']==total
    assert not result['physical_safety_qualified']


def test_parallel_outputs_do_not_each_inherit_whole_rail_load_without_sharing():
    p=PCBProject(nets=['GND','VCC'],components=[part('U1',10,current=1.5),part('S1',20,'power_out',None,1),part('S2',30,'power_out',None,1)])
    result=review_embedded(p,net_conditions={'VCC':dict(voltage_v=5,source_current_limit_a=2,declared_load_current_a=1.5),'GND':dict(voltage_v=0)})
    outputs=[r for r in result['checks'] if r['name']=='output_current_limit']
    assert len(outputs)==2 and all(r['status']=='unknown' for r in outputs)
    assert all(r['inputs']['per_output_current_a'] is None and r['inputs']['parallel_output_count']==2 for r in outputs)
    rail=next(r for r in result['checks'] if r['name']=='current_budget' and r['refs']==['VCC'])
    assert rail['status']=='declared_check' and rail['inputs']['operating_load_current_a']==1.5


@pytest.mark.parametrize('limit,status',[(1,'declared_check'),(.1,'violation'),(None,'unknown')])
def test_single_output_complete_declared_load_keeps_limit_comparison(limit,status):
    result=review([part('U1',10),part('S1',30,'power_out',None,limit)])
    output=next(r for r in result['checks'] if r['name']=='output_current_limit')
    assert output['status']==status and output['inputs']['per_output_current_a']==.4
    assert output['inputs']['parallel_output_count']==1


def test_unfitted_internal_and_parent_do_not_create_unknown_zero_purchase():
    parent=part('MODULE',10,fitted=False)
    child=part('INTERNAL',20,fitted=False)
    child.library_metadata.bom_role='internal_model';child.library_metadata.module_parent_ref='MODULE'
    p=PCBProject(nets=['GND','VCC'],components=[parent,child]);before=p.model_dump()
    result=estimate_cost(p)
    assert result['unknown_refs']==result['ownership_unknown_refs']==result['rows']==[]
    assert result['component_prices_complete'] and result['complete_total'] is None
    assert not result['estimated_complete'] and p.model_dump()==before
