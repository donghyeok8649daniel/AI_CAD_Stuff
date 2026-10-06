"""AI gets actionable bounded electrical deficits, not arbitrary review text."""
from cadstudio.models import Design, Part
from cadstudio.electrical_registration import register_part
from cadstudio.native.cad_electrical_tools import readiness_context


def test_context_distinguishes_pending_physical_supply_from_unused_gpio():
    design=Design(parts=[Part(id='board',name='Board',role='electrical',
        geometry=dict(kind='cylinder',diameter=10,height=5))])
    design=register_part(design,'board',dict(catalog_id='rpi4b'))
    before=design.model_dump(mode='json')
    result=readiness_context(design)
    assert result['hardware_execution_supported'] is False
    assert result['firmware_execution_supported'] is False
    assert result['dc_calculation_performed'] is False
    assert result['devices'][0]['model_status']=='exact'
    assert result['devices'][0]['power_status']=='missing'
    assert result['devices'][0]['diagram_available']
    assert all(set(item)=={'code','severity','part_id','component_id','terminal'}
               for item in result['findings'])
    assert design.model_dump(mode='json')==before


def test_missing_registration_context_is_bounded_and_does_not_infer_from_color():
    design=Design(parts=[Part(id=f'body{i}',name='untrusted long body notes',
        role='electrical',geometry=dict(kind='cylinder',diameter=1,height=1))
        for i in range(65)])
    result=readiness_context(design)
    assert len(result['missing_registrations'])==24
    assert result['omitted']['registrations']==41
    assert len(result['findings'])<=40
    assert 'untrusted' not in str(result)
    assert readiness_context(Design(parts=[Part(id='yellow',name='Board',color='#FFD400',
        role='structure',geometry=dict(kind='cylinder',diameter=1,height=1))])) is None


def test_empty_design_context_is_empty():
    assert readiness_context(Design()) is None
