from copy import deepcopy
from datetime import date
import pytest
from cadstudio.electrical import ElectricalComponent,ElectricalWorkspace
from cadstudio.electrical_catalog import component_prefill,get_catalog_entry,catalog_functions
from cadstudio.electrical_registration import register_part,registration_for_part
from cadstudio.measurement_catalog import catalog_measurement
from cadstudio.measurement_specs import AdcMeasurement,LoadCellMeasurement,EnvironmentalMeasurement,ForceCalibration,ForceChainSpec
from cadstudio.product_diagrams import product_diagram
from cadstudio.models import Design,Project


IDS=('hbk_u10m_25kn_passive','ti_ads131m04','ti_ads1232','avia_hx711','sensirion_sht31_dis_b','sensirion_sht45_ad1b')

@pytest.mark.parametrize('identifier',IDS)
def test_source_backed_profiles_and_exact_terminal_functions_are_passive(identifier):
    entry=get_catalog_entry(identifier);reference=catalog_measurement(identifier);diagram=product_diagram(identifier)
    assert entry.reference_only and component_prefill(entry)=={}
    assert reference.source_url==entry.source_url==diagram.source_url
    assert reference.provenance=='manufacturer_reference'
    assert reference.role in catalog_functions(identifier)
    assert all(terminal.removeprefix('port:') in {item.key for item in diagram.terminals} for terminal in reference.terminal_roles.values())
    assert reference is not catalog_measurement(identifier)
    if isinstance(reference,AdcMeasurement):
        assert reference.gain is None and reference.sample_rate_sps is None and reference.usable_bandwidth_hz is None
    if isinstance(reference,LoadCellMeasurement):
        assert reference.sensitivity_mv_per_v is None and reference.calibration.status=='uncalibrated'
        assert reference.dynamic_bandwidth_hz is None and reference.fatigue_cycles is None
    design=Design.model_validate(dict(name='Reference test',parts=[dict(id='body',name='Keep CAD',geometry=dict(kind='cylinder',diameter=20,height=12),color='#112233')]))
    before=design.model_dump();registered=register_part(design,'body',dict(catalog_id=identifier))
    component=registration_for_part(registered,'body')
    assert component.measurement==reference and component.analysis_enabled is False and component.rated_current_a==0
    assert design.model_dump()==before and registered.parts[0].geometry==design.parts[0].geometry
    again=register_part(registered,'body',dict(name='Rename only'))
    assert registration_for_part(again,'body').measurement==reference
    assert Project.model_validate_json(Project(design=again).model_dump_json()).design==again


def test_unknown_measurement_fields_are_omitted_in_old_exact_snapshots():
    old=ElectricalComponent.model_validate(dict(id='old',name='Legacy load',kind='load',a='A',b='GND',rated_voltage_v=5,rated_current_a=.1))
    raw=old.model_dump();assert 'measurement' not in raw
    workspace=ElectricalWorkspace(nodes=['GND','A'],components=[old]);serialized=workspace.model_dump()
    assert 'force_chain' not in serialized and 'measurement' not in serialized['components'][0]
    assert ElectricalWorkspace.model_validate(deepcopy(serialized)).model_dump()==serialized
    workspace.force_chain=ForceChainSpec();assert 'force_chain' in workspace.model_dump()
    modern=ElectricalComponent.model_validate({**raw,'measurement':None});assert 'measurement' in modern.model_dump()


@pytest.mark.parametrize('data',[
    dict(role='adc',gain=float('nan')),dict(role='adc',analog_supply_min_v=4,analog_supply_max_v=3),
    dict(role='adc',source_url='https://person:secret@example.com/spec'),
    dict(role='adc',terminal_roles={'clock':'pin:한글'}),dict(role='adc',unknown_rated_current=2),
])
def test_invalid_or_fabricated_measurement_inputs_are_rejected(data):
    with pytest.raises(ValueError):AdcMeasurement.model_validate(data)


def test_known_loadcell_reference_does_not_promote_natural_frequency_to_bandwidth():
    load=catalog_measurement('hbk_u10m_25kn_passive')
    assert load.rated_capacity_n==25000 and load.sensitivity_nominal_mv_per_v==2
    assert load.sensitivity_max_mv_per_v==2.5 and load.bridge_resistance_ohm is None
    assert load.bridge_resistance_min_ohm==345 and load.dynamic_bandwidth_hz is None
    assert load.excitation_voltage_v is None and load.fatigue_cycles is None
    assert catalog_measurement('nonsense') is None


def test_reference_motor_and_daq_board_keep_ratings_unmodeled():
    entry=get_catalog_entry('maxon_ec_i52_667065')
    assert entry.reference_only and component_prefill(entry)=={} and entry.rated_current_a is None
    assert 'NRND' in entry.model and '18.3' in entry.spec_summary
    diagram=product_diagram(entry.catalog_id);ports={item.key:item for item in diagram.terminals}
    assert {'MOTOR_U','MOTOR_V','MOTOR_W','HALL_VCC','HALL_GND','HALL_H1','HALL_H2','HALL_H3'}==set(ports)
    assert 'pending' in ports['HALL_VCC'].label
    from cadstudio.board_pins import board_pinout
    board=board_pinout('st_nucleo_g474re');pins={item.key:item for item in board.pins}
    assert 'CN5.6' in pins['PA5'].label and 'SPI1_SCK' in pins['PA5'].functions
    assert 'CN5.5' in pins['PA6'].label and 'SPI1_MISO' in pins['PA6'].functions
    assert pins['GND_CN5_7'].kind=='ground' and pins['3V3_CN6_4'].kind=='power'
    assert 'SB6' in board.note and 'CLKIN' in board.note_en


@pytest.mark.parametrize('stamp',[None,date(2026,10,6)])
def test_measurement_dates_are_json_scalars_in_native_python_mode_history(stamp):
    expected=stamp.isoformat() if stamp else None
    calibration=ForceCalibration(calibrated_at=stamp)
    reference=LoadCellMeasurement(source_checked_at=stamp,calibration=calibration)
    saved=reference.model_dump()
    assert saved['source_checked_at']==expected and saved['calibration']['calibrated_at']==expected
    reopened=LoadCellMeasurement.model_validate(saved)
    assert reopened.source_checked_at==stamp and reopened.calibration.calibrated_at==stamp
