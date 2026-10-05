from copy import deepcopy
import pytest
from cadstudio.electrical import ElectricalWorkspace,evaluate_electrical
from cadstudio.circuit_connections import add_schematic_wire,delete_schematic_wire
from cadstudio.models import Design
from cadstudio.native.document import Document,read_project


def circuit():
    return ElectricalWorkspace.model_validate(dict(nodes=['GND','BAT','LOAD'],components=[
        dict(id='source',name='Battery',kind='battery',a='BAT',b='GND',voltage_v=5),
        dict(id='load',name='Load',kind='load',a='LOAD',b='GND',rated_voltage_v=5,rated_current_a=.1),
        dict(id='peer',name='Peer resistor',kind='resistor',a='BAT',b='GND',resistance_ohm=1000)]))


def add(workspace,**values):
    return add_schematic_wire(workspace,'source','a','load','a',name='Power lead',length_mm=500,cross_section_mm2=.5,**values)


def test_wire_is_a_real_saved_conductive_branch_and_delete_removes_only_that_branch():
    original=circuit();before=original.model_dump();wired=add(original,max_current_a=.2)
    wire=wired.components[-1]
    assert wire.kind=='wire' and (wire.a,wire.b)==('BAT','LOAD')
    branch=next(item for item in evaluate_electrical(wired).components if item.id==wire.id)
    assert branch.current_a==pytest.approx(5/(50+.01724))
    assert original.model_dump()==before
    raw=wired.model_dump();raw['schematic_positions']={wire.id:dict(x=123,y=456)}
    removed=delete_schematic_wire(raw,wire.id)
    assert removed.nodes==wired.nodes and removed.components==original.components
    assert wire.id not in removed.schematic_positions
    assert next(item for item in evaluate_electrical(removed).components if item.id=='load').current_a==0


def test_insert_into_shared_net_changes_only_selected_target_not_other_peers():
    raw=circuit().model_dump();raw['components'][1]['a']='BAT';original=ElectricalWorkspace.model_validate(raw)
    wired=add(original)
    assert wired.components[1].a!='BAT' and wired.components[2]==original.components[2]
    assert wired.components[0]==original.components[0] and 'BAT' in wired.nodes
    assert wired.components[-1].b==wired.components[1].a
    removed=delete_schematic_wire(wired,wired.components[-1].id)
    assert removed.components[1].a==wired.components[1].a
    assert removed.nodes==wired.nodes


def test_physical_board_and_product_pins_get_distinct_saved_wire_nets_and_keep_catalog():
    raw=circuit().model_dump();raw['components'].extend([
        dict(id='board',name='Pi',kind='mcu',catalog_id='rpi4b',a='BAT',b='GND',analysis_enabled=False),
        dict(id='driver',name='Driver',kind='load',catalog_id='pololu_2130',a='BAT',b='GND',analysis_enabled=False)])
    original=ElectricalWorkspace.model_validate(raw)
    wired=add_schematic_wire(original,'board','pin:GPIO17','driver','port:AIN1',name='Command',length_mm=100,cross_section_mm2=.2)
    board=next(item for item in wired.components if item.id=='board')
    driver=next(item for item in wired.components if item.id=='driver')
    wire=wired.components[-1]
    assert board.signal_pins['GPIO17']==wire.a and driver.terminal_pins['AIN1']==wire.b and wire.a!=wire.b
    assert board.catalog_id=='rpi4b' and driver.catalog_id=='pololu_2130'
    deleted=delete_schematic_wire(wired,wire.id)
    assert next(item for item in deleted.components if item.id=='board').signal_pins==board.signal_pins
    assert next(item for item in deleted.components if item.id=='driver').terminal_pins==driver.terminal_pins


@pytest.mark.parametrize('length,area',[(0,.5),(100,0),(-1,.5),(100,float('nan'))])
def test_invalid_dimensions_are_transactional(length,area):
    original=circuit();before=original.model_dump()
    with pytest.raises(ValueError):
        add_schematic_wire(original,'source','a','load','a',name='Lead',length_mm=length,cross_section_mm2=area)
    assert original.model_dump()==before


def test_unknown_same_device_endpoints_and_nonwire_deletion_are_rejected():
    original=circuit();before=original.model_dump()
    for source,sourcepin,target,targetpin in [('source','a','source','b'),('source','bad','load','a'),('missing','a','load','a')]:
        with pytest.raises(ValueError):add_schematic_wire(original,source,sourcepin,target,targetpin,name='Lead',length_mm=100,cross_section_mm2=.5)
    for identifier in ['load','missing']:
        with pytest.raises(ValueError):delete_schematic_wire(original,identifier)
    assert original.model_dump()==before


def test_wire_add_delete_save_reopen_and_undo_preserve_every_pin_and_history(tmp_path):
    original=Design(electrical=circuit()).model_dump();wired=deepcopy(original);wired['electrical']=add(circuit()).model_dump()
    wire_id=wired['electrical']['components'][-1]['id']
    deleted=deepcopy(wired);deleted['electrical']=delete_schematic_wire(wired['electrical'],wire_id).model_dump()
    doc=Document();doc.commit(original,'Original');doc.commit(wired,'Add lead');added=doc.journal.data['cursor']
    doc.commit(deleted,'Delete lead');removed=doc.journal.data['cursor']
    doc.write(tmp_path/'wire.cad.json');checked=read_project(tmp_path/'wire.cad.json')
    assert checked.design.model_dump()==deleted and len(checked.history.entries)==3
    doc.commit(doc.journal.at(added),'Undo',cursor=added);assert doc.design==wired
    doc.commit(doc.journal.at(removed),'Redo',cursor=removed);assert doc.design==deleted


def test_saved_wire_color_and_endpoint_identity_roundtrip_without_legacy_default_injection():
    wired=add(circuit(),wire_color='#Ab1234');wire=wired.components[-1]
    assert wire.wire_color=='#Ab1234'
    assert [(ref.component_id,ref.terminal) for ref in wire.wire_endpoints]==[('source','a'),('load','a')]
    assert ElectricalWorkspace.model_validate_json(wired.model_dump_json())==wired
    for old in circuit().model_dump()['components']:
        assert 'wire_color' not in old and 'wire_endpoints' not in old
    raw=circuit().components[0].model_dump();raw.update(wire_color=None,wire_endpoints=[])
    explicit=ElectricalWorkspace.model_validate(dict(nodes=circuit().nodes,components=[raw])).model_dump()['components'][0]
    assert explicit['wire_color'] is None and explicit['wire_endpoints']==[]


@pytest.mark.parametrize('color',['red','#GG0000','#12345678'])
def test_unsafe_or_invalid_wire_color_is_rejected_transactionally(color):
    original=circuit();before=original.model_dump()
    with pytest.raises(ValueError):add(original,wire_color=color)
    assert original.model_dump()==before
