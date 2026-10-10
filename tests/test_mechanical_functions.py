"""Declared mechanical purpose must survive editing without inventing hardware."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from cadstudio.mechanical_functions import (
    FUNCTIONS, LABELS, ENGLISH_LABELS, assign_mechanical_function,
    function_label, mechanical_function,
)
from cadstudio.models import Design, DraftRequest, Part, Project
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.cad_scope import Scope, SYSTEM as SCOPE_GUIDANCE
from cadstudio.native.cad_tools import context, execute_plan
from cadstudio.native.document import Document, Journal, read_project
from cadstudio.part_product import ProductMetadata
from cadstudio.planner import SYSTEM_PROMPT, ai_design_context


def part(**values):
    return Part(id='body', name='Body', geometry={'kind': 'cylinder'}, **values)


def execute(actions, *, current=None):
    return execute_plan(json.dumps({'summary': 'Explicit function', 'actions': actions}),
                        DraftRequest(prompt='기계 기능 지정', current=current))


@pytest.mark.parametrize('function', FUNCTIONS)
def test_declared_function_schema_serialization_and_labels(function):
    value = part(mechanical_function=function)
    assert mechanical_function(value) == function
    assert mechanical_function(value.model_dump()) == function
    assert Part.model_validate_json(value.model_dump_json()).mechanical_function == function
    assert ('mechanical_function' in value.model_dump()) == (function != 'unspecified')
    assert function_label(function) == LABELS[function]
    assert function_label(function, language='en') == ENGLISH_LABELS[function]


@pytest.mark.parametrize('invalid', ['motor', 'bolt', 'joint', '', None, False, 1, ['actuator']])
def test_invalid_function_rejected_without_mutating_part(invalid):
    raw = part(role='structure', color='#123456').model_dump()
    before = deepcopy(raw)
    with pytest.raises(ValueError):
        assign_mechanical_function(raw, invalid)
    assert raw == before
    with pytest.raises(ValidationError):
        part(mechanical_function=invalid)


def test_legacy_bytes_and_history_are_unchanged_when_function_unspecified(tmp_path):
    original = part(color='#123456').model_dump()
    assert 'mechanical_function' not in original
    explicit_default = {**original, 'mechanical_function': 'unspecified'}
    assert Part.model_validate(explicit_default).model_dump() == original
    assert Part.model_validate(original).model_dump_json() == Part.model_validate(explicit_default).model_dump_json()
    design = Design(parts=[Part.model_validate(original)])
    document = Document()
    document.commit(design, 'Legacy base')
    expected = document.project().model_dump(mode='json')
    first = tmp_path / 'legacy.pcad'
    document.write(first)
    original_bytes = first.read_bytes()
    loaded = read_project(first)
    assert loaded.model_dump(mode='json') == expected
    second = tmp_path / 'legacy-reopened.pcad'
    reopened = Document()
    reopened.load(loaded)
    reopened.write(second)
    assert second.read_bytes() == original_bytes
    assert 'mechanical_function' not in loaded.history.base.parts[0].model_dump()


def test_assign_and_clear_change_only_function_and_retain_custom_style():
    raw = part(role='transmission', color='#abcdef', fixed=True,
               product=ProductMetadata(model='Explicit user product')).model_dump()
    before = deepcopy(raw)
    assign_mechanical_function(raw, 'fastener')
    assert raw == {**before, 'mechanical_function': 'fastener'}
    assign_mechanical_function(raw, 'unspecified')
    assert raw == before


@pytest.mark.parametrize('name', ['M3 bolt', 'retaining pin', 'powered motor', '액추에이터', '회전 관절'])
def test_name_color_role_product_and_movable_joint_do_not_imply_actuator(name):
    design = Design(parts=[
        Part(id='base', name='Base', fixed=True, geometry={'kind': 'cylinder'}),
        Part(id='moving', name=name, role='electrical', color='#FFD400',
             geometry={'kind': 'cylinder'},
             product=ProductMetadata(name='Motor', spec_summary='Coaxial powered motor')),
    ], mates=[{'id': 'rotation', 'kind': 'revolute', 'parent': 'base', 'child': 'moving'}])
    assert [mechanical_function(value) for value in design.parts] == ['unspecified', 'unspecified']
    assert mechanical_function({'name': name, 'role': 'electrical', 'geometry': {'kind': 'cylinder'}}) == 'unspecified'
    assert design.electrical is None


@pytest.mark.parametrize('function', FUNCTIONS[1:])
def test_ai_create_and_appearance_accept_explicit_function_without_operating_ratings(function):
    created = execute([{'tool': 'create', 'target': 'body', 'args': {
        'name': 'Arbitrary body', 'geometry': {'kind': 'cylinder'},
        'color': '#123456', 'mechanical_function': function,
    }}]).design
    assert created.parts[0].mechanical_function == function
    assert created.parts[0].product is None and created.electrical is None
    before = created.model_dump()
    changed = execute([{'tool': 'appearance', 'target': 'body', 'args': {
        'mechanical_function': 'joint_support' if function != 'joint_support' else 'fastener',
    }}], current=created).design
    expected = deepcopy(before)
    expected['parts'][0]['mechanical_function'] = changed.parts[0].mechanical_function
    assert changed.model_dump() == expected
    assert created.model_dump() == before
    cleared = execute([{'tool': 'appearance', 'target': 'body', 'args': {
        'mechanical_function': 'unspecified',
    }}], current=changed).design
    assert 'mechanical_function' not in cleared.parts[0].model_dump()
    assert cleared.parts[0].color == '#123456'


def test_invalid_ai_function_is_atomic_for_existing_design():
    design = Design(parts=[part(mechanical_function='fastener', color='#abcdef')])
    before = design.model_dump()
    with pytest.raises(ValueError):
        execute([
            {'tool': 'appearance', 'target': 'body', 'args': {'color': '#111111'}},
            {'tool': 'appearance', 'target': 'body', 'args': {'mechanical_function': 'motor'}},
        ], current=design)
    assert design.model_dump() == before


def test_real_tool_schemas_and_both_ai_context_paths_expose_declared_function():
    schema = plan_schema(allowed_tools=('create', 'appearance'), allowed_shapes=('cylinder',))
    for action in schema['properties']['actions']['items']['anyOf']:
        fields = action['properties']['args']['properties']
        assert fields['mechanical_function']['enum'] == list(FUNCTIONS)
    design = Design(parts=[part(mechanical_function='fastener')])
    compact = context(design)
    assert compact['parts'][0]['mechanical_function'] == 'fastener'
    assert 'No name/geometry/motion inference' in compact['mechanical_function_scope']
    assert ai_design_context(design)['parts'][0]['mechanical_function'] == 'fastener'
    prompt = Scope(tools=('appearance',), shapes=('cylinder',)).plan_messages(
        DraftRequest(prompt='체결 기능 지정', current=design))[0]['content']
    assert 'mechanical_function' in prompt and 'Never infer a powered actuator' in prompt
    assert 'mechanical_function' in SYSTEM_PROMPT and 'mechanical_function' in SCOPE_GUIDANCE


def test_function_edits_persist_with_independently_restorable_history(tmp_path):
    document = Document()
    design = Design(parts=[part(color='#123456')])
    document.commit(design, 'Original')
    original_cursor = document.journal.data['cursor']
    original = deepcopy(document.design)
    updated = deepcopy(original)
    assign_mechanical_function(updated['parts'][0], 'actuator')
    document.commit(Design.model_validate(updated), 'Declare actuator')
    declared_cursor = document.journal.data['cursor']
    cleared = deepcopy(document.design)
    assign_mechanical_function(cleared['parts'][0], 'unspecified')
    document.commit(Design.model_validate(cleared), 'Clear declaration')
    cleared_cursor = document.journal.data['cursor']
    path = tmp_path / 'mechanical-functions.pcad'
    document.write(path)
    loaded = read_project(path)
    assert loaded.model_dump(mode='json') == document.project().model_dump(mode='json')
    history = Journal(data=loaded.history.model_dump())
    assert history.at(original_cursor) == original
    assert history.at(declared_cursor)['parts'][0]['mechanical_function'] == 'actuator'
    assert history.at(cleared_cursor) == original
    assert loaded.design.electrical is None
    assert Project.model_validate_json(loaded.model_dump_json()).model_dump() == loaded.model_dump()


def test_generated_revolute_hardware_is_explicitly_passive_not_powered():
    from cadstudio.joint_hardware import add_revolute_hardware
    design, identifiers = add_revolute_hardware(prefix='passive-')
    functions = {value.id: value.mechanical_function for value in design.parts}
    assert {functions[key] for key in identifiers} == {'joint_support', 'transmission'}
    assert functions['passive-housing'] == functions['passive-bush-a'] == 'joint_support'
    assert functions['passive-shaft'] == functions['passive-output'] == 'transmission'
    assert all(value.product is None and value.mechanical_function != 'actuator' for value in design.parts)
    assert design.electrical is None
