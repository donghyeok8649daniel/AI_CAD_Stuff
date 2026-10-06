"""Offline real registration/binding/pin-wire plans, not descriptive AI replies."""
from copy import deepcopy
import json

import httpx
import pytest

from cadstudio.circuit_connections import add_schematic_wire,update_schematic_wire
from cadstudio.electrical_registration import bind_component_to_part,unbind_component_from_part
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.models import Design,Part,DraftRequest
from cadstudio.native.cad_electrical_tools import TOOLS,circuit_context
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.cad_scope import Scope
from cadstudio.native.cad_tools import execute_plan
from cadstudio.native.document import Document,read_project


def fixture():
    return Design(parts=[Part(id=identifier,name=identifier,color=color,
        geometry=dict(kind='plate',length=20,width=15,thickness=2,hole_count=0),transform=dict(x=index*100))
        for index,(identifier,color) in enumerate((('pi','#113355'),('driver','#446688'),('motor','#778899'),('supply','#AA8855')))],
        electrical=ElectricalWorkspace.model_validate(dict(nodes=['GND','BAT'],components=[
            dict(id='source',name='Declared 5 V bench source',kind='battery',a='BAT',b='GND',voltage_v=5)])))


def action(tool,target,**args):return dict(tool=tool,target=target,args=args)
def plan(actions):return json.dumps(dict(summary='Actual pin wiring preview',actions=actions))


def wiring_actions():
    actions=[action('electrical_bind','supply',component_id='source'),
        action('electrical_register','pi',catalog_id='rpi4b'),
        action('electrical_register','driver',catalog_id='pololu_2130'),
        action('electrical_register','motor',kind='motor',analysis_enabled=False)]
    for source,source_terminal,target,target_terminal in (
        ('supply','a','pi','supply:5V_2'),('supply','b','pi','supply:GND_6'),
        ('supply','a','driver','port:VIN'),('supply','b','driver','port:GND'),
        ('pi','pin:GPIO17','driver','port:AIN1'),
        ('driver','port:AOUT1','motor','a'),('driver','port:AOUT2','motor','b')):
        actions.append(action('electrical_wire_add',source,source_terminal=source_terminal,
            target_id=target,target_terminal=target_terminal,name=source_terminal+' wire',wire_color='#12AB34'))
    return actions


def execute(actions,current=None):
    return execute_plan(plan(actions),DraftRequest(prompt='기존 CAD와 부품을 연결하고 실제 배선도를 그려',current=current or fixture()))


def test_offline_plan_creates_actual_power_signal_and_motor_wire_branches_without_guessing_rates():
    original=fixture();before=original.model_dump();reply=execute(wiring_actions(),original)
    assert original.model_dump()==before
    assert len(reply.design.parts)==4 and len(reply.design.electrical.components)==11
    wires=[item for item in reply.design.electrical.components if item.kind=='wire']
    assert len(wires)==7 and len({wire.id for wire in wires})==7
    assert all(len(wire.wire_endpoints)==2 and wire.a!=wire.b for wire in wires)
    assert all(not wire.analysis_enabled and wire.length_mm==wire.cross_section_mm2==0 for wire in wires)
    for old,new in zip(original.parts,reply.design.parts):
        assert old.geometry==new.geometry and old.transform==new.transform and old.color==new.color
    devices=[item for item in reply.design.electrical.components if item.kind not in ('wire','battery')]
    assert all(not item.analysis_enabled and item.rated_current_a==0 for item in devices)
    assert len(reply.journal_steps)==11 and all(step['validated'] for step in reply.tool_actions)
    actual=circuit_context(reply.design)
    assert len(actual['wires'])==7 and actual['wires'][4]['endpoints'][0]['terminal']=='pin:GPIO17'
    assert actual['hardware_verified'] is actual['firmware_executed'] is False


def test_bind_and_unbind_keep_component_id_pins_nets_existing_wires_and_canvas_position():
    current=execute(wiring_actions()).design
    before=current.model_dump();unlinked=unbind_component_from_part(current,'ereg_001')
    assert unlinked.electrical.components[1].part_id=='' and not unlinked.electrical.components[1].part_registration
    assert current.model_dump()==before
    rebound=bind_component_to_part(unlinked,'ereg_001','pi')
    assert rebound.model_dump()==before
    assert len(rebound.electrical.components)==11


@pytest.mark.parametrize('fault',['missing_body','missing_component','already_linked','unsupported_legacy_model'])
def test_bad_link_mapping_is_atomic_and_never_clears_old_circuit(fault):
    current=fixture();before=current.model_dump()
    if fault=='missing_body':call=lambda:bind_component_to_part(current,'source','missing')
    elif fault=='missing_component':call=lambda:bind_component_to_part(current,'missing','pi')
    elif fault=='already_linked':
        current=execute(wiring_actions()).design;before=current.model_dump()
        call=lambda:bind_component_to_part(current,'source','pi')
    else:
        raw=current.model_dump();raw['electrical']['components'].append(dict(id='legacy',name='Wrong family',kind='mcu',
            a='BAT',b='GND',catalog_id='stm32g4_family',analysis_enabled=False))
        current=Design.model_validate(raw);before=current.model_dump()
        call=lambda:bind_component_to_part(current,'legacy','pi')
    with pytest.raises(ValueError):call()
    assert current.model_dump()==before


def test_wire_edit_preserves_id_order_layout_unrelated_fields_and_reports_new_endpoints():
    current=execute(wiring_actions()).design
    raw=current.electrical.model_dump();raw['schematic_positions']={'WIRE_005':dict(x=123,y=456)}
    original=ElectricalWorkspace.model_validate(raw);before=original.model_dump()
    changed=update_schematic_wire(original,'WIRE_005',source_id='ereg_001',source_terminal='pin:GPIO18',
        length_mm=120,cross_section_mm2=.25,wire_color='#ABCDEF',analysis_enabled=True)
    old=next(item for item in original.components if item.id=='WIRE_005')
    new=next(item for item in changed.components if item.id=='WIRE_005')
    assert new.wire_endpoints[0].terminal=='pin:GPIO18' and new.length_mm==120 and new.analysis_enabled
    assert changed.schematic_positions==original.schematic_positions
    assert [item.id for item in changed.components]==[item.id for item in original.components]
    assert new.name==old.name and new.max_current_a==old.max_current_a
    assert next(item for item in changed.components if item.id=='ereg_001').signal_pins['GPIO17']==old.a
    assert original.model_dump()==before


def test_ai_wire_edit_delete_and_link_unbind_are_distinct_and_undoable(tmp_path):
    original=fixture();created=execute(wiring_actions(),original)
    edited=execute([action('electrical_wire_edit','WIRE_005',source_id='pi',source_terminal='pin:GPIO18',
        name='Edited PWM',closed=False),action('electrical_wire_delete','WIRE_007'),
        action('electrical_unbind','source')],created.design)
    assert len([item for item in edited.design.electrical.components if item.kind=='wire'])==6
    assert next(item for item in edited.design.electrical.components if item.id=='source').part_id==''
    document=Document();document.commit(original,'Initial')
    document.commit(created.design,'Apply wiring preview',dict(journal_steps=created.journal_steps))
    added=document.journal.data['cursor']
    document.commit(edited.design,'Apply edit preview',dict(journal_steps=edited.journal_steps))
    final=document.journal.data['cursor'];path=tmp_path/'ai-wiring.cad.json';document.write(path)
    loaded=read_project(path)
    assert loaded.design==edited.design and len(loaded.history.entries)==15
    document.commit(document.journal.at(added),'Undo',cursor=added)
    assert document.design==created.design.model_dump()
    document.commit(document.journal.at(final),'Redo',cursor=final)
    assert document.design==edited.design.model_dump()


@pytest.mark.parametrize('args',[
    dict(source_terminal='pin:MADE_UP',target_id='driver',target_terminal='port:AIN1'),
    dict(source_terminal='pin:GPIO17',target_id='driver',target_terminal='port:MADE_UP'),
    dict(source_terminal='pin:GPIO17',target_id='missing',target_terminal='a'),
    dict(source_terminal='pin:GPIO17',target_id='pi',target_terminal='pin:GPIO18'),
    dict(source_terminal='pin:GPIO17',target_id='driver',target_terminal='port:AIN1',analysis_enabled=True),
    dict(source_terminal='pin:GPIO17',target_id='driver',target_terminal='port:AIN1',length_mm=-1),
    dict(source_terminal='pin:GPIO17',target_id='driver',target_terminal='port:AIN1',max_current_a=0),
    dict(source_terminal='pin:GPIO17',target_id='driver',target_terminal='port:AIN1',rated_current_a=99)])
def test_wire_plan_failure_has_no_partial_preview_or_original_mutation(args):
    original=fixture();before=original.model_dump()
    with pytest.raises(ValueError):execute(wiring_actions()[:4]+[action('electrical_wire_add','pi',**args)],original)
    assert original.model_dump()==before


def test_duplicate_physical_wire_is_rejected_in_both_directions():
    current=execute(wiring_actions()).design;before=current.model_dump()
    for source,terminal,target,other in [('pi','pin:GPIO17','driver','port:AIN1'),('driver','port:AIN1','pi','pin:GPIO17')]:
        with pytest.raises(ValueError,match='이미'):
            execute([action('electrical_wire_add',source,source_terminal=terminal,target_id=target,target_terminal=other)],current)
    assert current.model_dump()==before


def test_gpio_to_power_is_kept_as_visible_topology_warning_not_normal_signal_approval():
    current=execute(wiring_actions()[:4]).design
    result=execute([action('electrical_wire_add','pi',source_terminal='pin:GPIO17',target_id='supply',target_terminal='a')],current)
    assert len(result.design.electrical.components[-1].wire_endpoints)==2
    assert any('GPIO' in warning and '전원' in warning for warning in result.tool_actions[0]['electrical_warnings'])


def test_schema_scope_and_bounded_circuit_context_include_wire_tools_and_unlinked_devices():
    current=fixture();context=circuit_context(current)
    assert context['devices'][0]['id']=='source' and context['devices'][0]['part_id']==''
    scope=Scope.parse(json.dumps(dict(intent='edit',tools=list(TOOLS),shapes=[],new_parts=[],connections=[])),DraftRequest(prompt='wire',current=current))
    assert set(scope.tools)==set(TOOLS)
    schema=plan_schema(TOOLS,existing_parts=['pi','driver','motor','supply'])
    alternatives={a['properties']['tool']['const']:a for a in schema['properties']['actions']['items']['anyOf']}
    assert set(alternatives)==set(TOOLS)
    assert 'enum' not in alternatives['electrical_wire_delete']['properties']['target']
    assert alternatives['electrical_bind']['properties']['target']['enum']==['pi','driver','motor','supply']
    assert len(json.dumps(plan_schema()))<22000
    messages=scope.plan_messages(DraftRequest(prompt='wire',current=current))
    data=json.loads(messages[1]['content'])
    assert 'electrical_circuit' in data['current_design']
    assert 'electrical_wire_add' in messages[0]['content'] and 'actual' in messages[0]['content'].lower()


def test_local_ai_mock_provider_executes_real_registration_and_wires_without_network_or_paid_calls():
    from cadstudio.native.local_ai import ollama_draft
    from ai_transport import cad_transport
    scope=dict(intent='edit',tools=['electrical_bind','electrical_register','electrical_wire_add'],shapes=[],new_parts=[],connections=[])
    calls=[]
    def handle(request):
        data=json.loads(request.content);calls.append(data)
        answer=scope if len(calls)==1 else json.loads(plan(wiring_actions()))
        return httpx.Response(200,json={'done':True,'message':{'content':json.dumps(answer)}})
    original=fixture();before=original.model_dump()
    result=ollama_draft(DraftRequest(prompt='실제 핀 사이 회로도 전선을 연결해',current=original),'offline',cad_transport(handle),deadline=None)
    actual=Design.model_validate(result['design'])
    assert len(calls)==2 and len([item for item in actual.electrical.components if item.kind=='wire'])==7
    assert original.model_dump()==before and len(result['journal_steps'])==11


def test_new_fanout_wire_preserves_existing_branch_and_target_pin_node():
    current=execute(wiring_actions()).design.electrical
    before=current.model_dump()
    previous=next(item for item in current.components if item.id=='WIRE_005')
    extended=add_schematic_wire(current,'ereg_001','pin:GPIO18','ereg_002','port:AIN1',
        name='Second command',length_mm=0,cross_section_mm2=0,analysis_enabled=False)
    assert next(item for item in extended.components if item.id=='WIRE_005')==previous
    assert next(item for item in extended.components if item.id=='ereg_002').terminal_pins['AIN1']==previous.b
    assert extended.components[-1].b==previous.b and extended.components[-1].a!=previous.a
    assert current.model_dump()==before


def test_shared_node_split_never_detaches_an_older_physical_wire_silently():
    current=execute(wiring_actions()).design.electrical
    raw=current.model_dump()
    target=next(item for item in raw['components'] if item['id']=='ereg_002')
    board=next(item for item in raw['components'] if item['id']=='ereg_001')
    board['signal_pins']['GPIO18']=target['terminal_pins']['AIN1']
    original=ElectricalWorkspace.model_validate(raw);before=original.model_dump()
    with pytest.raises(ValueError,match='공유 노드'):
        add_schematic_wire(original,'ereg_001','pin:GPIO18','ereg_002','port:AIN1',
            name='Unsafe split',length_mm=0,cross_section_mm2=0,analysis_enabled=False)
    assert original.model_dump()==before


@pytest.mark.parametrize('field,value',[('closed','false'),('analysis_enabled','false'),('length_mm',True)])
def test_wire_edit_rejects_coerced_state_and_dimensions_without_mutation(field,value):
    current=execute(wiring_actions()).design.electrical;before=current.model_dump()
    with pytest.raises(ValueError):update_schematic_wire(current,'WIRE_005',**{field:value})
    assert current.model_dump()==before


def test_bind_requires_explicit_boolean_color_permission():
    original=fixture();before=original.model_dump()
    with pytest.raises(ValueError):bind_component_to_part(original,'source','supply',apply_default_color='false')
    assert original.model_dump()==before


def test_bad_legacy_exact_board_pinmap_is_not_adopted_by_cad_binding():
    raw=fixture().model_dump()
    raw['electrical']['components'].append(dict(id='legacy',name='Legacy Pi',kind='mcu',catalog_id='rpi4b',
        a='BAT',b='GND',signal_pins={'UNLISTED_PIN':'BAT'},analysis_enabled=False))
    original=Design.model_validate(raw);before=original.model_dump()
    with pytest.raises(ValueError):bind_component_to_part(original,'legacy','pi')
    assert original.model_dump()==before


def test_legacy_wire_property_edit_preserves_metadata_and_repoint_requires_both_actual_ends():
    raw=fixture().electrical.model_dump()
    raw['components'].append(dict(id='legacy_wire',name='Old cable',kind='wire',a='BAT',b='GND',
        length_mm=100,cross_section_mm2=.25,closed=False))
    original=ElectricalWorkspace.model_validate(raw);before=original.model_dump()
    edited=update_schematic_wire(original,'legacy_wire',wire_color='#123456')
    assert edited.components[-1].closed is False and not edited.components[-1].wire_endpoints
    assert edited.components[-1].a=='BAT' and edited.components[-1].b=='GND'
    with pytest.raises(ValueError,match='시작과 도착'):
        update_schematic_wire(original,'legacy_wire',source_id='source',source_terminal='a')
    assert original.model_dump()==before


@pytest.mark.parametrize('requested',[
    action('electrical_connect','pi',pin='GPIO17',target_part_id='driver',target_terminal='port:AIN2'),
    action('electrical_connect','driver',pin='AIN1',target_part_id='pi',target_terminal='pin:GPIO17'),
    action('electrical_connect','supply',pin='a',target_part_id='pi',target_terminal='supply:GND_6'),
    action('electrical_register','pi',signal_pins=[dict(pin='GPIO17',node='REASSIGNED')]),
    action('electrical_register','motor',a='BAT')])
def test_legacy_ai_node_reassignment_cannot_detach_an_existing_physical_wire(requested):
    current=execute(wiring_actions()).design;before=current.model_dump()
    with pytest.raises(ValueError,match='electrical_wire_edit'):execute([requested],current)
    assert current.model_dump()==before


@pytest.mark.parametrize('editor',['connect','assign','disconnect','registered_signal','registered_supply'])
def test_manual_node_editing_cannot_silently_break_saved_wire_endpoint_identity(editor):
    from cadstudio.circuit_connections import assign_schematic_node,connect_schematic_terminals,disconnect_schematic_terminal
    from cadstudio.electrical_registration import register_terminal_node
    current=execute(wiring_actions()).design;before=current.model_dump()
    callbacks=dict(
        connect=lambda:connect_schematic_terminals(current.electrical,'ereg_001','pin:GPIO17','ereg_002','port:AIN2'),
        assign=lambda:assign_schematic_node(current.electrical,'ereg_001','pin:GPIO17','REASSIGNED'),
        disconnect=lambda:disconnect_schematic_terminal(current.electrical,'ereg_001','pin:GPIO17'),
        registered_signal=lambda:register_terminal_node(current,'pi','GPIO17','REASSIGNED'),
        registered_supply=lambda:register_terminal_node(current,'pi','supply:5V_2','BAT'))
    with pytest.raises(ValueError,match='electrical_wire_edit'):callbacks[editor]()
    assert current.model_dump()==before


def test_no_wire_legacy_connect_still_assigns_nodes_and_preserves_old_labels():
    current=execute(wiring_actions()[:4]).design;before=current.model_dump()
    linked=execute([action('electrical_connect','pi',pin='GPIO17',target_part_id='driver',target_terminal='port:AIN1')],current).design
    pi=next(c for c in linked.electrical.components if c.part_id=='pi')
    driver=next(c for c in linked.electrical.components if c.part_id=='driver')
    assert pi.signal_pins['GPIO17']==driver.terminal_pins['AIN1']
    assert not any(c.kind=='wire' for c in linked.electrical.components)
    assert set(current.electrical.nodes)<=set(linked.electrical.nodes)
    assert current.model_dump()==before


def test_alias_reassignment_detects_the_same_gpio_wired_through_another_physical_label():
    from cadstudio.circuit_connections import connect_schematic_terminals
    original=ElectricalWorkspace.model_validate(dict(nodes=['GND','SIG_A','SIG_B'],components=[
        dict(id='uno',name='UNO',kind='mcu',catalog_id='arduino_uno_r3',pinout_catalog_id='arduino_uno_r3',
            a='SIG_B',b='GND',signal_pins={'A4':'SIG_A','SDA':'SIG_A'},analysis_enabled=False),
        dict(id='sensor',name='Custom sensor',kind='load',a='SIG_B',b='GND',analysis_enabled=False,
            terminal_pins={'OUT':'SIG_A','ALT':'SIG_B'})]))
    wired=add_schematic_wire(original,'uno','pin:A4','sensor','port:OUT',name='SDA cable',
        length_mm=0,cross_section_mm2=0,analysis_enabled=False)
    before=wired.model_dump()
    with pytest.raises(ValueError,match='electrical_wire_edit'):
        connect_schematic_terminals(wired,'uno','pin:SDA','sensor','port:ALT')
    assert wired.model_dump()==before


def test_passive_fanout_to_an_existing_wire_pad_keeps_every_old_cable_consistent():
    from cadstudio.mcu_connections import connection_endpoints
    current=execute(wiring_actions()).design
    linked=execute([action('electrical_connect','pi',pin='GPIO18',target_part_id='driver',target_terminal='port:AIN1')],current).design
    old=[c for c in current.electrical.components if c.kind=='wire']
    assert [c for c in linked.electrical.components if c.kind=='wire']==old
    endpoints={(e.component_id,e.terminal):e.node for e in connection_endpoints(linked.electrical)}
    for cable in old:
        assert [endpoints[(ref.component_id,ref.terminal)] for ref in cable.wire_endpoints]==[cable.a,cable.b]


@pytest.mark.parametrize('editor',['assign','connect','disconnect'])
def test_direct_mcu_dialog_backends_reject_wire_detachment_and_allow_explicit_wire_edit(editor):
    from cadstudio.mcu_connections import assign_pin,assign_pin_node,disconnect_pin,connection_endpoints
    current=execute(wiring_actions()).design.electrical;before=current.model_dump()
    callbacks=dict(
        assign=lambda:assign_pin_node(current,'ereg_001','GPIO17','REASSIGNED'),
        connect=lambda:assign_pin(current,'ereg_001','GPIO17','ereg_002','port:AIN2'),
        disconnect=lambda:disconnect_pin(current,'ereg_001','GPIO17'))
    with pytest.raises(ValueError,match='electrical_wire_edit'):callbacks[editor]()
    assert current.model_dump()==before
    edited=update_schematic_wire(current,'WIRE_005',source_id='ereg_001',source_terminal='pin:GPIO18')
    nodes={(e.component_id,e.terminal):e.node for e in connection_endpoints(edited)}
    for cable in edited.components:
        if cable.kind=='wire':
            assert [nodes[(ref.component_id,ref.terminal)] for ref in cable.wire_endpoints]==[cable.a,cable.b]
    assert edited.components[8].id=='WIRE_005' and current.model_dump()==before
