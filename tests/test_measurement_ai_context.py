"""Offline AI references retain real measurement limits without certification."""
from cadstudio.models import Design, Part
from cadstudio.electrical_registration import register_part
from cadstudio.measurement_specs import ForceChainSpec, ForceCalibration
from cadstudio.native.cad_electrical_tools import feature_context, force_review_context


def test_measuring_product_context_preserves_ranges_but_omits_free_text():
    original = Design(parts=[Part(id='sensor', name='Force sensor',
        geometry=dict(kind='cylinder', diameter=30, height=20))])
    design = register_part(original, 'sensor', {'catalog_id': 'hbk_u10m_25kn_passive'})
    measure = design.electrical.components[0].measurement
    measure.notes = 'arbitrary untrusted note' * 30
    measure.calibration = ForceCalibration(status='certificate_reference',
        zero_offset_counts=12, scale_n_per_count=.1,
        certificate_reference='private certificate', point_count=2)
    before = design.model_dump()
    data = feature_context(design)[0]
    assert data['measurement_reference']['sensitivity_max_mv_per_v'] == 2.5
    assert data['measurement_reference']['rated_capacity_n'] == 25000
    assert data['measurement_reference']['calibration']['status'] == 'certificate_reference'
    assert 'notes' not in data['measurement_reference']
    assert 'certificate_reference' not in data['measurement_reference']['calibration']
    assert 'board_supply_pins' in data
    assert design.model_dump() == before and original.electrical is None


def test_force_context_keeps_unknown_targets_and_offline_failures():
    design = Design(parts=[])
    from cadstudio.electrical import ElectricalWorkspace
    design.electrical = ElectricalWorkspace(force_chain=ForceChainSpec())
    before = design.model_dump()
    review = force_review_context(design)
    assert review['status'] == 'pending'
    assert review['hardware_verified'] is review['firmware_executed'] is False
    assert 'target_peak_force_n' not in review['settings']
    assert 'target_frequency_hz' not in review['settings']
    assert len(review['findings']) <= 16
    assert all(set(item) == {'code', 'severity', 'component_id'} for item in review['findings'])
    assert design.model_dump() == before
    assert force_review_context(Design()) is None
