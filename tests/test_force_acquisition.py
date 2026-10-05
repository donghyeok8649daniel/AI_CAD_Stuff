from copy import deepcopy
import pytest
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.force_acquisition import assess_force_chain,calibrate_force,force_from_counts
from cadstudio.measurement_catalog import catalog_measurement
from cadstudio.measurement_specs import ForceCalibration,ForceChainSpec


def synthetic_chain(excitation=2.5):
    """Synthetic wiring/settings only, not a product commissioning fixture."""
    load=catalog_measurement('hbk_u10m_25kn_passive').model_dump()
    load.update(excitation_voltage_v=excitation,sensitivity_mv_per_v=2.2)
    adc=catalog_measurement('ti_ads131m04').model_dump()
    adc.update(gain=64,sample_rate_sps=4000,analog_supply_voltage_v=3.3,digital_supply_voltage_v=3.3,clock_frequency_hz=8192000,oversampling_ratio=1024,power_mode='high_resolution')
    ports={'EXC_POS':'EXC','EXC_NEG':'GND','SIG_POS':'SIGP','SIG_NEG':'SIGN'}
    adcports={'AIN0P':'SIGP','AIN0N':'SIGN','AVDD':'AV','AGND':'GND','DVDD':'AV','DGND':'GND','SCLK':'CLK','DOUT':'DATA','DIN':'COMMAND','CS':'SELECT','DRDY':'READY','CLKIN':'OSC'}
    components=[
        dict(id='excitation',name='Synthetic excitation source',kind='battery',a='EXC',b='GND',voltage_v=excitation),
        dict(id='adc_power',name='Synthetic analog rail',kind='battery',a='AV',b='GND',voltage_v=3.3),
        dict(id='loadcell',name='Passive loadcell candidate',kind='load',a='LC_A',b='LC_B',catalog_id='hbk_u10m_25kn_passive',analysis_enabled=False,measurement=load,terminal_pins=ports),
        dict(id='adc',name='Bare IC candidate',kind='load',a='ADC_A',b='ADC_B',catalog_id='ti_ads131m04',analysis_enabled=False,measurement=adc,terminal_pins=adcports),
        dict(id='host',name='Synthetic host pin configuration',kind='mcu',a='HOST_A',b='HOST_B',catalog_id='rpi4b',analysis_enabled=False,
            signal_pins={'GPIO11':'CLK','GPIO9':'DATA','GPIO10':'COMMAND','GPIO8':'SELECT','GPIO17':'READY','GPIO18':'OSC'},board_supply_pins={'GND_6':'GND'},supply_pinout_catalog_id='rpi4b'),
    ]
    nodes=['GND','EXC','AV','SIGP','SIGN','CLK','DATA','COMMAND','SELECT','READY','OSC','LC_A','LC_B','ADC_A','ADC_B','HOST_A','HOST_B']
    spec=ForceChainSpec(source_id='excitation',load_cell_id='loadcell',adc_id='adc',controller_id='host',target_frequency_hz=1,target_peak_force_n=15000,
        controller_terminals={'clock':'pin:GPIO11','data_out':'pin:GPIO9','data_in':'pin:GPIO10','chip_select':'pin:GPIO8','data_ready':'pin:GPIO17','ground':'supply:GND_6'})
    return ElectricalWorkspace.model_validate(dict(nodes=nodes,components=components,force_chain=spec.model_dump()))


def codes(result):return {item.code for item in result.findings}


@pytest.mark.parametrize('voltage',[3.3,5.0])
def test_ads131_high_gain_rejects_bridge_each_input_common_mode(voltage):
    result=assess_force_chain(synthetic_chain(voltage))
    assert result.status=='blocked' and 'adc_common_mode_violation' in codes(result)
    assert result.metrics['adc_input_allowed_max_v']==pytest.approx(1.5)
    assert result.hardware_verified is result.firmware_executed is False


def test_conditional_two_point_five_supply_has_headroom_but_never_fake_success():
    workspace=synthetic_chain();before=workspace.model_dump();result=assess_force_chain(workspace)
    assert workspace.model_dump()==before and result.status=='pending'
    assert 'adc_common_mode_violation' not in codes(result)
    assert result.metrics['requested_bridge_output_mv']==pytest.approx(3.75) # worst case 2.5 mV/V
    assert result.metrics['adc_differential_full_scale_mv']==pytest.approx(18.75)
    assert result.metrics['clock_derived_sample_rate_sps']==4000
    assert result.metrics['samples_per_cycle']==4000
    assert {'force_uncalibrated','fatigue_qualification_unknown','system_bandwidth_unknown','digital_protocol_unverified'}<=codes(result)


@pytest.mark.parametrize('change,code',[(('gain',128),'adc_common_mode_violation'),(('gain',3),'adc_gain_unsupported'),(('sample_rate_sps',64000),'adc_clock_rate_mismatch')])
def test_selected_adc_settings_are_not_catalogue_maxima(change,code):
    workspace=synthetic_chain(3.3 if change[0]=='gain' and change[1]==128 else 2.5)
    setattr(workspace.components[3].measurement,*change)
    assert code in codes(assess_force_chain(workspace))


def test_real_wire_open_cannot_be_replaced_by_matching_adc_role_text():
    workspace=synthetic_chain();load=workspace.components[2];load.terminal_pins['SIG_POS']='LC_A'
    assert 'signal_positive_open' in codes(assess_force_chain(workspace))
    raw=workspace.model_dump();raw['components'].append(dict(id='signal_wire',name='Real wire',kind='wire',a='LC_A',b='SIGP',length_mm=100,cross_section_mm2=.2))
    connected=ElectricalWorkspace.model_validate(raw);assert 'signal_positive_open' not in codes(assess_force_chain(connected))
    connected.components[-1].closed=False;assert 'signal_positive_open' in codes(assess_force_chain(connected))


def test_sampling_frequency_and_force_rating_have_separate_checks():
    workspace=synthetic_chain();workspace.force_chain.target_frequency_hz=2100;workspace.force_chain.target_peak_force_n=26000
    result=assess_force_chain(workspace)
    assert {'sampling_aliasing','capacity_exceeded','fatigue_load_exceeded'}<=codes(result)
    assert result.status=='blocked'


def test_adc_inputs_short_and_supply_rating_edits_cannot_waive_known_limits():
    workspace=synthetic_chain();workspace.components[3].terminal_pins['AIN0N']='SIGP'
    assert 'signal_short' in codes(assess_force_chain(workspace))
    workspace=synthetic_chain();workspace.components[1].voltage_v=5
    workspace.components[3].measurement.analog_supply_max_v=12;workspace.components[3].measurement.digital_supply_max_v=12
    assert 'adc_analog_datasheet_supply' in codes(assess_force_chain(workspace))


def test_missing_chain_and_removed_ids_are_pending_instead_of_crashing_or_simulating():
    result=assess_force_chain(ElectricalWorkspace())
    assert result.status=='pending' and len(result.findings)==4 and result.metrics=={}
    workspace=synthetic_chain();workspace.components=[item for item in workspace.components if item.id!='adc']
    assert 'adc_missing' in codes(assess_force_chain(workspace))


def test_sht45_five_volt_miswiring_is_blocked_even_if_user_range_edited():
    workspace=synthetic_chain();raw=workspace.model_dump();raw['nodes'].append('FIVE')
    sensor=catalog_measurement('sensirion_sht45_ad1b').model_dump();sensor['supply_max_v']=12
    raw['components'] += [dict(id='five',name='Five volt rail',kind='battery',a='FIVE',b='GND',voltage_v=5),dict(id='humidity',name='SHT45',kind='load',catalog_id='sensirion_sht45_ad1b',a='ADC_A',b='ADC_B',analysis_enabled=False,measurement=sensor,terminal_pins={'VDD':'FIVE','VSS':'GND'})]
    raw['force_chain']['environment_ids']=['humidity'];result=assess_force_chain(raw)
    assert 'environment_datasheet_supply' in codes(result) and result.status=='blocked'


def test_calibration_is_finite_explicit_measured_affine_newton_mapping():
    calibration=calibrate_force([(1000,0),(21000,100),(41000,200)])
    assert calibration.scale_n_per_count==pytest.approx(.005) and calibration.zero_offset_counts==pytest.approx(1000)
    assert calibration.point_count==3 and calibration.rms_residual_n==pytest.approx(0)
    assert force_from_counts(-19000,calibration)==pytest.approx(-100)
    with pytest.raises(ValueError):force_from_counts(1000,ForceCalibration())
    with pytest.raises(ValueError):calibrate_force([(1,0),(1,100)])
    with pytest.raises(ValueError):calibrate_force([(1,0),(2,float('nan'))])
    with pytest.raises(ValueError):force_from_counts(float('inf'),calibration)
    with pytest.raises(ValueError):calibrate_force([(1e200,0),(2e200,100)])


def test_controller_dc_and_power_pads_cannot_be_used_as_gpio_or_physical_ground():
    workspace=synthetic_chain();workspace.force_chain.controller_terminals.update(clock='a',ground='b')
    assert {'host_signal_not_gpio','host_ground_not_physical'}<=codes(assess_force_chain(workspace))


@pytest.mark.parametrize('ratio,blocked',[(.5,True),(1/3,False)])
def test_excitation_monitor_is_a_distinct_channel_with_own_adc_range(ratio,blocked):
    workspace=synthetic_chain();workspace.components[3].measurement.excitation_sense_divider_ratio=ratio;workspace.components[3].measurement.excitation_sense_gain=1
    result=assess_force_chain(workspace)
    assert ('excitation_sense_clipping' in codes(result)) is blocked
    assert 'excitation_monitor_calibration' in codes(result) and result.status in ('blocked','pending')


def test_known_adc_function_roles_cannot_turn_power_pin_into_analog_signal():
    workspace=synthetic_chain();workspace.components[3].measurement.terminal_roles['signal_positive']='port:AVDD'
    assert 'catalog_terminal_role_mismatch' in codes(assess_force_chain(workspace))


def test_ads131_recommended_clock_range_is_distinct_from_nominal_and_turbo_osr():
    workspace=synthetic_chain();adc=workspace.components[3].measurement
    adc.clock_frequency_hz=8400000;adc.oversampling_ratio=64;adc.sample_rate_sps=65625;adc.turbo_mode=True
    result=assess_force_chain(workspace)
    assert not {'adc_clock_settings_range','adc_clock_rate_mismatch','sample_rate_exceeded','adc_turbo_mode_mismatch'} & codes(result)
    assert 'sample_rate_above_nominal' in codes(result)
    adc.turbo_mode=False;assert 'adc_turbo_mode_mismatch' in codes(assess_force_chain(workspace))
    adc.turbo_mode=None;assert 'adc_turbo_mode_unknown' in codes(assess_force_chain(workspace))
    adc.clock_frequency_hz=8400001;assert 'adc_clock_settings_range' in codes(assess_force_chain(workspace))
    adc.clock_frequency_hz=299999;assert 'adc_clock_settings_range' in codes(assess_force_chain(workspace))


def test_known_sensor_role_and_adc_digital_level_are_not_waived_by_user_text():
    workspace=synthetic_chain();raw=workspace.model_dump()
    sensor=catalog_measurement('sensirion_sht45_ad1b').model_dump();sensor['terminal_roles']['data']='port:VDD'
    raw['components'].append(dict(id='humidity',name='SHT45',kind='load',catalog_id='sensirion_sht45_ad1b',a='ADC_A',b='ADC_B',analysis_enabled=False,measurement=sensor,terminal_pins={'VDD':'AV','VSS':'GND'}))
    raw['force_chain']['environment_ids']=['humidity']
    assert 'catalog_terminal_role_mismatch' in codes(assess_force_chain(raw))
    workspace.components[1].voltage_v=5
    assert 'host_digital_level_mismatch' in codes(assess_force_chain(workspace))


def test_known_loadcell_reference_range_edits_cannot_reduce_documented_headroom_check():
    workspace=synthetic_chain();lc=workspace.components[2].measurement
    lc.calibration=calibrate_force([(1000,0),(21000,100)])
    saved_calibration=lc.calibration.model_dump()
    lc.sensitivity_max_mv_per_v=.1;lc.sensitivity_min_mv_per_v=.05
    result=assess_force_chain(workspace)
    assert result.status=='blocked' and 'catalog_sensitivity_reference_mismatch' in codes(result)
    assert result.metrics['rated_bridge_output_mv']==pytest.approx(6.25)
    assert result.metrics['requested_bridge_output_mv']==pytest.approx(3.75)
    assert lc.calibration.model_dump()==saved_calibration and lc.sensitivity_mv_per_v==2.2


def test_manual_loadcell_range_is_user_reference_and_remains_editable():
    workspace=synthetic_chain();component=workspace.components[2];component.catalog_id=''
    lc=component.measurement;lc.sensitivity_mv_per_v=.1;lc.sensitivity_min_mv_per_v=.05;lc.sensitivity_max_mv_per_v=.2
    result=assess_force_chain(workspace)
    assert 'catalog_sensitivity_reference_mismatch' not in codes(result)
    assert result.metrics['rated_bridge_output_mv']==pytest.approx(.5)
    assert any('사용자가 선언' in item.message for item in result.findings if item.code=='sensitivity_worst_case')


def test_known_loadcell_missing_reference_and_serial_measurement_are_kept_separate():
    workspace=synthetic_chain();lc=workspace.components[2].measurement
    lc.sensitivity_max_mv_per_v=None;lc.sensitivity_mv_per_v=1.9
    result=assess_force_chain(workspace)
    assert {'catalog_sensitivity_reference_mismatch','serial_sensitivity_outside_reference'}<=codes(result)
    assert result.metrics['rated_bridge_output_mv']==pytest.approx(6.25)
    assert workspace.components[2].measurement.sensitivity_mv_per_v==1.9
