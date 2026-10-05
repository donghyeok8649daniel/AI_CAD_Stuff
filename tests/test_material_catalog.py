"""Material source conditions, unknowns, legacy history and explicit assignment."""
from copy import deepcopy

import pytest
from pydantic import ValidationError
from cadstudio.models import Design, Material, Part, Project
from cadstudio.material_catalog import (CATALOG, UNITS, MaterialProvenance,
    MaterialProperty, MaterialSource, get_catalog_entry, search_catalog, material_from_catalog)
from cadstudio.material_assignments import (assign_material, remove_material, custom_material,
    part_material, tensile_material_values, tensile_settings_with_material)


def two_parts():
    return Design(parts=[Part(id='frame', name='Frame', geometry=dict(kind='plate', hole_count=0),
                            color='#F2F2F2', role='structure'),
                         Part(id='window', name='Window', geometry=dict(kind='cylinder'),
                            color='#123456', transform=dict(x=150))])


def test_legacy_material_and_history_remain_exact_without_new_defaults():
    old = dict(name='Custom steel', density=7800, youngs_modulus=210000, poisson=.29)
    assert Material.model_validate(old).model_dump() == old
    assert Material().model_dump() == dict(name='사용자 재질', density=2700, youngs_modulus=69000, poisson=.33)
    raw = two_parts().model_dump()
    raw['parts'][0]['material'] = old
    from cadstudio.native.document import Document
    document = Document()
    document.commit(raw, 'Legacy')
    legacy_cursor = document.journal.data['cursor']
    after = assign_material(raw, 'window', catalog_id='pmma_extruded_sheet')
    document.commit(after, 'Window material')
    saved = document.project().model_dump()
    assert Project.model_validate(saved).model_dump() == saved
    assert document.journal.at(legacy_cursor) == raw
    assert saved['design']['parts'][0]['material'] == old
    assert saved['design']['parts'][1]['material']['youngs_modulus'] is None
    assert saved['design']['parts'][1]['material']['yield_strength'] is None


def test_catalog_every_known_property_has_units_source_and_unknowns_survive():
    assert len(CATALOG) >= 9 and len({entry.catalog_id for entry in CATALOG}) == len(CATALOG)
    for entry in CATALOG:
        material = material_from_catalog(entry.catalog_id)
        dumped = material.model_dump()
        assert Material.model_validate(dumped).model_dump() == dumped
        record = MaterialProvenance.model_validate(material.provenance)
        assert record.catalog_id == entry.catalog_id
        for key, fact in record.properties.items():
            assert fact.unit == UNITS.get(key, 'MPa')
            if fact.value is not None or fact.basis == 'range':
                assert fact.source_index is not None and record.sources[fact.source_index].url.startswith('https://')
            if key in UNITS and fact.value is None:
                assert dumped[key] is None
        assert all(source.checked_on == '2026-10-06' for source in record.sources)
        assert material.poisson is None  # No manufacturer value inferred by analogy.


def test_search_exact_grade_unicode_alias_and_empty():
    assert search_catalog('6061')[0].catalog_id == 'al_6061_t6_extruded'
    assert search_catalog('ＳＵＳ３０４')[0].catalog_id == 'stainless_304_cold_sheet'
    assert search_catalog('웨이퍼')[0].behavior == 'anisotropic'
    assert not search_catalog('PLA')
    assert not search_catalog('6061', '씰 / 절연')
    assert get_catalog_entry('not-in-list') is None
    with pytest.raises(ValueError, match='ID'):
        material_from_catalog('not-in-list')


def test_unit_conversions_and_test_conditions_are_kept_with_material():
    pc = material_from_catalog('pc_tecanat_natural')
    assert pc.density == 1190
    assert pc.youngs_modulus == pytest.approx(340000*.006894757293168)
    assert pc.yield_strength == pytest.approx(9300*.006894757293168)
    assert pc.provenance['properties']['youngs_modulus']['temperature_c'] == pytest.approx((73-32)*5/9)
    al = material_from_catalog('al_6061_t6_extruded')
    assert al.thermal_expansion == pytest.approx(13.1e-6*1.8)
    assert al.provenance['properties']['yield_strength']['basis'] == 'minimum'
    pom = material_from_catalog('pom_c_tecaform_ah')
    assert pom.specific_heat == 1400
    assert pom.provenance['properties']['water_absorption']['temperature_c'] == 23
    assert '24 h' in pom.provenance['properties']['water_absorption']['condition']


def test_multi_part_assignment_is_atomic_preserves_geometry_colors_wiring_and_input():
    design = two_parts()
    raw = design.model_dump()
    original = deepcopy(raw)
    after = assign_material(raw, ('frame', 'window'), catalog_id='al_6061_t6_extruded')
    assert raw == original
    clean = after.model_dump()
    for part in clean['parts']:
        part.pop('material')
    assert clean == original
    with pytest.raises(ValueError, match='부품을 찾을'):
        assign_material(raw, ('frame', 'missing'), catalog_id='al_6061_t6_extruded')
    with pytest.raises(ValueError, match='선택'):
        assign_material(raw, [], catalog_id='al_6061_t6_extruded')
    assert raw == original
    detached = part_material(after, 'frame')
    detached.name = 'Local copy'
    assert after.parts[0].material.name != 'Local copy'


def test_existing_custom_material_requires_explicit_replacement_and_remove_is_scoped():
    raw = two_parts().model_dump()
    old = Material(name='Measured lot', density=8000, youngs_modulus=190000, poisson=.28).model_dump()
    raw['parts'][0]['material'] = deepcopy(old)
    with pytest.raises(ValueError, match='기존 재질'):
        assign_material(raw, ('frame', 'window'), catalog_id='al_6061_t6_extruded')
    assert raw['parts'][0]['material'] == old and 'material' not in raw['parts'][1]
    after = assign_material(raw, 'frame', catalog_id='al_6061_t6_extruded', replace_existing=True)
    assert 'material' not in after.model_dump()['parts'][1]
    assert remove_material(after, 'frame').model_dump() == two_parts().model_dump()


def test_custom_edit_retains_unchanged_records_and_removes_catalog_authority():
    original = material_from_catalog('al_6061_t6_extruded')
    before = original.model_dump()
    assert custom_material(original, dict(name=original.name)).model_dump() == before
    edited = custom_material(original, dict(poisson=.33, youngs_modulus=69000))
    assert original.model_dump() == before
    assert edited.catalog_id is None and edited.provenance['origin'] == 'user'
    assert edited.provenance['properties']['poisson']['basis'] == 'user'
    assert edited.provenance['properties']['poisson']['source_index'] is None
    assert edited.provenance['properties']['yield_strength'] == before['provenance']['properties']['yield_strength']
    assert custom_material(Material(name='Old', density=1000), {}).model_dump() == Material(name='Old', density=1000).model_dump()
    manual = custom_material(None, dict(density=1200, youngs_modulus=None, poisson=None))
    assert manual.provenance['origin'] == 'user' and not manual.provenance['sources']
    assert manual.provenance['properties']['density']['unit'] == 'kg/m³'
    assert manual.provenance['properties']['density']['basis'] == 'user'
    assert manual.provenance['properties']['poisson']['value'] is None


def test_tensile_values_require_explicit_complete_isotropic_inputs_no_study_mutation():
    al = material_from_catalog('al_6061_t6_extruded')
    with pytest.raises(ValueError, match='poisson'):
        tensile_material_values(al)
    specified = custom_material(al, dict(poisson=.33))
    values = tensile_material_values(specified)
    assert values.young_gpa == 68.3 and values.yield_mpa == 240
    raw = two_parts().model_dump()
    after = assign_material(raw, 'frame', specified)
    settings = dict(part_id='frame', force_n=17, young_gpa=200, poisson=.3, yield_mpa=300, refinement=2)
    before = deepcopy(settings)
    proposed = tensile_settings_with_material(after, 'frame', settings)
    assert settings == before and proposed['force_n'] == 17 and proposed['refinement'] == 2
    assert proposed['young_gpa'] == 68.3 and proposed['poisson'] == .33
    with pytest.raises(ValueError, match='대상이 다릅니다'):
        tensile_settings_with_material(after, 'frame', dict(settings, part_id='window'))
    assert raw == two_parts().model_dump()


@pytest.mark.parametrize('catalog_id', ['silicon_single_crystal', 'ptfe_tecaflon_natural', 'silicone_lr3003_50'])
def test_si_and_nonlinear_seals_cannot_be_silently_mapped_to_tensile(catalog_id):
    material = material_from_catalog(catalog_id)
    supplied = custom_material(material, dict(youngs_modulus=130000, poisson=.28, yield_strength=100))
    with pytest.raises(ValueError, match='이방성 또는 비선형'):
        tensile_material_values(supplied)
    if catalog_id == 'silicon_single_crystal':
        assert material.youngs_modulus is None and material.poisson is None and material.yield_strength is None
        assert material.provenance['properties']['youngs_modulus_110']['direction'] == '[110]'


def test_invalid_unknown_finite_values_units_provenance_and_public_source_links_rejected():
    with pytest.raises(ValidationError):
        MaterialProperty(value=3, unit='MPa')
    with pytest.raises(ValidationError):
        MaterialProperty(value=float('nan'), unit='MPa', basis='user')
    with pytest.raises(ValidationError):
        MaterialSource(title='Private', url='http://127.0.0.1/private')
    original = material_from_catalog('al_6061_t6_extruded').model_dump()
    wrong = deepcopy(original)
    wrong['provenance']['properties']['density']['unit'] = 'g/cm³'
    with pytest.raises(ValidationError):
        Material.model_validate(wrong)
    wrong = deepcopy(original)
    wrong['density'] = 9000
    with pytest.raises(ValidationError, match='출처 기록'):
        Material.model_validate(wrong)
    with pytest.raises(ValidationError):
        Material(density=0)


def test_real_geometry_mass_uses_assigned_density_without_changing_volume():
    from cadstudio.kernel import local_shape, KERNEL_LOCK
    from cadstudio.inspection import mass_properties
    design = two_parts()
    after = assign_material(design, 'frame', catalog_id='stainless_304_cold_sheet')
    with KERNEL_LOCK:
        original_shape = local_shape(design, design.parts[0])
        shape = local_shape(after, after.parts[0])
        assert shape.Volume() == pytest.approx(original_shape.Volume())
        mass = mass_properties(shape, after.parts[0].material.density)
    assert mass['mass_kg'] == pytest.approx(shape.Volume()*7900*1e-9)
