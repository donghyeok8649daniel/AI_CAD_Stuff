"""Offline AI tool contracts for explicit, source-backed DC power paths."""

from copy import deepcopy
import json

import pytest

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.models import Design, DraftRequest
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.cad_scope import Scope
from cadstudio.native.cad_tools import context, execute_plan
from cadstudio.native.document import Document, read_project
from cadstudio.power_paths import PowerInputRequired


def values(**changes):
    args = dict(source_voltage_v=5, positive_wire_length_mm=250,
                positive_wire_cross_section_mm2=.5,
                return_wire_length_mm=350, return_wire_cross_section_mm2=.5,
                load_voltage_v=5, load_current_a=.2,
                source_internal_resistance_ohm=.1, load_kind='mcu')
    args.update(changes)
    return args


def plan(*actions):
    return json.dumps(dict(summary='DC 결선 초안', actions=list(actions)))


def action(target='controller_supply', **changes):
    return dict(tool='power_path', target=target, args=values(**changes))


def test_electrical_only_scope_uses_bounded_schema_and_no_part_requirement():
    current = Design(parts=[])
    request = DraftRequest(prompt='배터리 5 V와 MCU 5 V 0.2 A 배선', current=current)
    scope = Scope.parse(json.dumps(dict(intent='edit', tools=['power_path'], shapes=[],
                                       new_parts=[], connections=[])), request)
    assert scope.tools == ('power_path',) and scope.new_parts == ()
    schema = plan_schema(scope.tools, scope.shapes, existing_parts=['existing_body'])
    alternatives = schema['properties']['actions']['items']['anyOf']
    assert len(alternatives) == 1 and alternatives[0]['properties']['tool']['const'] == 'power_path'
    assert 'enum' not in alternatives[0]['properties']['target']  # Descriptive circuit branch, not a CAD part ID.
    required = alternatives[0]['properties']['args']['required']
    assert len(alternatives[0]['properties']['args']['properties']) <= 27
    for field in ('switch_part_id', 'positive_wire_part_id', 'return_wire_part_id'):
        assert field in alternatives[0]['properties']['args']['properties']
    assert set(required) == {'source_voltage_v', 'positive_wire_length_mm',
                             'positive_wire_cross_section_mm2', 'return_wire_length_mm',
                             'return_wire_cross_section_mm2', 'load_voltage_v', 'load_current_a'}
    assert 'power_path:' in scope.plan_messages(request)[0]['content']
    assert 'cylinder:' not in scope.plan_messages(request)[0]['content']


def test_power_path_plan_saves_restores_and_undoes_each_electrical_step(tmp_path):
    request = DraftRequest(prompt='5 V 보드 전원과 실제 길이 양쪽 배선')
    reply = execute_plan(plan(action()), request)
    assert reply.design.parts == []
    assert reply.design.electrical is not None
    assert len(reply.design.electrical.components) == 5
    assert [c.kind for c in reply.design.electrical.components] == [
        'battery', 'switch', 'wire', 'mcu', 'wire']
    assert evaluate_electrical(reply.design.electrical).source_power_w > 0
    assert reply.tool_actions[0]['tool'] == 'power_path'
    assert any(change['path'][0] == 'electrical' for change in reply.journal_steps[0]['changes'])

    doc = Document()
    doc.commit(reply.design, 'AI power path', dict(source='local', provider='offline-test',
        tool_actions=reply.tool_actions, journal_base=reply.journal_base,
        journal_steps=reply.journal_steps))
    assert len(doc.journal.path()) == 2
    base = doc.journal.path()[0]['id']
    after = doc.journal.path()[1]['id']
    assert doc.journal.at(base).get('electrical') is None
    assert len(doc.journal.at(after)['electrical']['components']) == 5
    path = tmp_path / 'power.cad.json'
    doc.write(path)
    restored = read_project(path)
    assert len(restored.design.electrical.components) == 5
    assert restored.history.entries[-1].context['tool_actions'][0]['tool'] == 'power_path'
    doc.commit(doc.journal.at(base), 'undo power path', cursor=base)
    assert doc.design.get('electrical') is None


@pytest.mark.parametrize('bad', [
    {'load_part_id': 'missing_body'}, {'source_voltage_v': 1001},
])
def test_invalid_values_and_nonexistent_cad_links_preserve_original(bad):
    old = Design(electrical=ElectricalWorkspace.model_validate(dict(nodes=['GND', 'OLD'], components=[
        dict(id='old_lead', name='Old lead', kind='wire', a='OLD', b='GND',
             length_mm=100, cross_section_mm2=.5)])))
    snapshot = deepcopy(old.model_dump())
    with pytest.raises(ValueError, match='실패'):
        execute_plan(plan(action(**bad)), DraftRequest(prompt='전원 결선', current=old))
    assert old.model_dump() == snapshot


@pytest.mark.parametrize('field', [
    'source_voltage_v', 'load_current_a', 'positive_wire_length_mm',
    'return_wire_cross_section_mm2',
])
def test_missing_or_zero_operating_values_preserve_original_and_request_input(field):
    old = Design()
    before = old.model_dump()
    args = values()
    if field == 'source_voltage_v':
        del args[field]  # Missing from a provider's generated JSON.
    else:
        args[field] = 0  # A schema-valid placeholder must not be retried as geometry.
    with pytest.raises(PowerInputRequired) as captured:
        execute_plan(plan(dict(tool='power_path', target='controller_supply', args=args)),
                     DraftRequest(prompt='전원 결선', current=old))
    assert captured.value.missing_fields == (field,)
    assert old.model_dump() == before


def test_ai_path_appends_without_replacing_existing_circuit_and_catalog_wire_has_provenance():
    current = Design(electrical=ElectricalWorkspace.model_validate(dict(nodes=['GND', 'A'], components=[
        dict(id='old_wire', name='Old wire', kind='wire', a='A', b='GND',
             length_mm=100, cross_section_mm2=.5)])))
    reply = execute_plan(plan(action(positive_wire_catalog_id='belden_9918')),
                         DraftRequest(prompt='Belden 9918 공급선', current=current))
    assert current.electrical.components[0].id == 'old_wire'
    assert reply.design.electrical.components[0].id == 'old_wire'
    wire = next(c for c in reply.design.electrical.components if c.catalog_id == 'belden_9918')
    assert wire.source_url.startswith('https://www.belden.com/')
    assert wire.max_current_a is None  # A free-air figure is not harness ampacity.
    summary = context(reply.design)['electrical']
    assert summary['components_count'] == 6
    assert any(item['id'] == 'old_wire' for item in summary['components'])


def test_mocked_local_ai_can_select_and_generate_an_electrical_only_draft_without_network():
    import httpx
    from ai_transport import is_scope
    from cadstudio.native.local_ai import ollama_draft

    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        if is_scope(request):
            selected = dict(intent='edit', tools=['power_path'], shapes=[],
                            new_parts=[], connections=[])
            return httpx.Response(200, json=dict(done=True, message=dict(content=json.dumps(selected))))
        alternatives = body['format']['properties']['actions']['items']['anyOf']
        assert len(alternatives) == 1
        assert alternatives[0]['properties']['tool']['const'] == 'power_path'
        assert 'source_voltage_v' in alternatives[0]['properties']['args']['required']
        return httpx.Response(200, json=dict(done=True, message=dict(content=plan(action()))))

    result = ollama_draft(DraftRequest(prompt='실측 5 V 전원, 5 V 0.2 A 보드, 공급선 250 mm 0.5 mm2, '
                                              '리턴선 350 mm 0.5 mm2'),
                          'mock-model', httpx.MockTransport(handle), deadline=5)
    assert len(calls) == 2
    assert result['design']['parts'] == []
    assert len(result['design']['electrical']['components']) == 5
    assert result['planning']['tools'] == ('power_path',)


def test_mixed_cad_body_and_power_path_link_only_to_a_real_created_part():
    board = dict(tool='create', target='board', args=dict(name='Controller envelope',
        role='electrical', geometry=dict(kind='plate', length=60, width=40, thickness=2)))
    result = execute_plan(plan(board, action(load_part_id='board')),
                          DraftRequest(prompt='보드 형상과 별도의 전원 결선'))
    assert len(result.design.parts) == 1
    assert result.design.parts[0].id == 'board'
    assert len(result.design.electrical.components) == 5
    assert next(c for c in result.design.electrical.components if c.kind == 'mcu').part_id == 'board'
    assert [step['action']['tool'] for step in result.journal_steps] == ['create', 'power_path']


def test_all_five_circuit_elements_can_link_to_existing_physical_parts():
    from cadstudio.models import Part

    body_ids = ('battery', 'switch', 'feed', 'load', 'return')
    bodies = [Part(id=item, name=item,
                   geometry=dict(kind='cylinder', diameter=10, height=10))
              for item in body_ids]
    current = Design(parts=bodies)
    reply = execute_plan(plan(action(source_part_id='battery', switch_part_id='switch',
                                     positive_wire_part_id='feed', load_part_id='load',
                                     return_wire_part_id='return')),
                         DraftRequest(prompt='기존 CAD 부품에 회로 요소 연결', current=current))
    actual = {item.kind: item.part_id for item in reply.design.electrical.components
              if item.kind not in ('wire',)}
    assert actual == {'battery': 'battery', 'switch': 'switch', 'mcu': 'load'}
    wires = [item.part_id for item in reply.design.electrical.components if item.kind == 'wire']
    assert wires == ['feed', 'return']
