"""The native chamber preview commits only the complete checked assembly."""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication

from cadstudio.chamber_design import build_chamber
from cadstudio.models import Design, Part
from cadstudio.native.chamber_dialog import ChamberDialog, replacement_candidate


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


@pytest.fixture(scope='module')
def requirements():
    return dict(protected_swept_bounds=dict(minimum_mm=[-30,-44,364.7],maximum_mm=[30,32,529.7]),
        static_rod_seals=[dict(id='upper',rod_diameter_mm=25,position_xy_mm=[0,6])],
        rod_interfaces=[dict(id='lower',face='bottom',rod_diameter_mm=25,position_xy_mm=[0,6],
            bellows_inner_diameter_mm=28,bellows_outer_diameter_mm=44,installed_length_mm=44)])


def checked(dialog):
    dialog.timer.stop()
    # These form/transaction checks intentionally do not create a native WGL
    # surface. Actual asynchronous, visible rendering is exercised separately
    # by the native chamber smoke, after Qt creates its window handle.
    dialog.viewport.window.Render=lambda:None
    result=dialog.checked_compute(dialog.candidate(),dialog.revision)
    dialog.checked,dialog.result,dialog.interference,dialog.travel=result
    dialog.apply_button.setEnabled(True)
    dialog.present();dialog.present_interference()
    return dialog.checked


def test_native_reopens_world_coaxial_interfaces_without_invented_force_and_preserves_source(app,requirements):
    original=Design(parts=[Part(id='specimen',name='Al 시편',geometry=dict(kind='cylinder',diameter=8,height=30),transform=dict(z=430))]).model_dump()
    unchanged=deepcopy(original);dialog=ChamberDialog(None,original,requirements=requirements)
    try:
        candidate=checked(dialog)
        assert dialog.apply_button.isEnabled() and len(candidate.parts)==34
        assert dialog.report['requirements']['rod_interfaces'][0]['position_xy_mm']==[0,6]
        assert dialog.report['parasitic_estimate']['conservative_force_bound_n'] is None
        assert not dialog.report['leak_test_verified'] and original==unchanged
        assert dialog.tabs.count()==3 and '검증 전' in dialog.status.text()
        assert all(widget.text()=='' for widget in dialog.optional_inputs.values())
        assert dialog.inputs['bottom-diameter'].value()==25
    finally:dialog.reject()


def test_native_full_assembly_collision_blocks_apply_while_preserving_the_existing_component(app,requirements):
    # A 12 mm body crosses the right case wall at X=40..46, independently
    # of the selected protected volume. A chamber-only preview would miss it.
    original=Design(parts=[Part(id='obstruction',name='기존 부품',geometry=dict(kind='cylinder',diameter=12,height=20),
        transform=dict(x=42,z=430))]).model_dump()
    dialog=ChamberDialog(None,original,requirements=requirements)
    try:
        candidate=checked(dialog)
        assert candidate.parts[0].id=='obstruction'
        assert dialog.interference['blocked']
        assert not dialog.apply_button.isEnabled()
        assert 'obstruction' in dialog.status.text()
    finally:dialog.reject()


def test_native_motion_envelope_blocks_crosshead_but_accepts_coaxial_pullrod(app,requirements):
    pullrod=Part(id='rod',name='하부 Ø25 풀 로드',geometry=dict(kind='cylinder',diameter=25,height=90),transform=dict(z=279.7))
    original=Design(parts=[pullrod]).model_dump();dialog=ChamberDialog(None,original,requirements=requirements)
    try:
        checked(dialog)
        assert dialog.apply_button.isEnabled()
        assert not any(hit['kind']=='bellows_motion' for hit in dialog.report['installation_obstructions'])
    finally:dialog.reject()
    # This frame lies in the future extension envelope, below the nominal
    # bellows and outside the actual current chamber geometry.
    frame=Part(id='frame',name='벨로즈 운동 방해물',geometry=dict(kind='cylinder',diameter=44,height=2),transform=dict(z=295))
    original=Design(parts=[frame]).model_dump();dialog=ChamberDialog(None,original,requirements=requirements)
    try:
        checked(dialog)
        assert not dialog.interference['blocked']
        assert any(hit['kind']=='bellows_motion' for hit in dialog.report['installation_obstructions'])
        assert not dialog.apply_button.isEnabled()
    finally:dialog.reject()


def test_native_optional_force_inputs_are_explicit_and_zero_is_not_treated_as_unknown(app,requirements):
    dialog=ChamberDialog(None,Design(parts=[]).model_dump(),requirements=requirements)
    try:
        values=dict(pressure_differential_pa='0',bellows_effective_area_mm2='600',bellows_spring_rate_n_per_mm='.1',
            bellows_deflection_from_free_mm='-3',seal_friction_n='.05',preload_n='0',test_force_n='100')
        for key,value in values.items():dialog.optional_inputs[key].setText(value)
        checked(dialog)
        assert dialog.report['parasitic_estimate']['conservative_force_bound_n']==pytest.approx(.35)
        assert dialog.report['parasitic_estimate']['pressure_force_n']==0
        assert dialog.report['parasitic_estimate']['unknown_inputs']==[]
        dialog.optional_inputs['seal_friction_n'].setText('unknown')
        with pytest.raises(ValueError,match='숫자'):dialog.candidate()
    finally:dialog.reject()


def test_native_replacement_preserves_names_colors_and_external_mates(app,requirements):
    original=build_chamber(requirements).as_design().model_dump()
    original['parts'][0].update(name='사용자 본체 이름',color='#AB1234')
    original['parts'].append(Part(id='bracket',name='외부 부착물',geometry=dict(kind='cylinder',diameter=4,height=10),transform=dict(x=120)).model_dump())
    original['mates']=[dict(id='attachment',parent='chamber-case',child='bracket',kind='rigid',x=120)]
    ids=[p['id'] for p in original['parts'] if p['id'].startswith('chamber-')]
    unchanged=deepcopy(original);dialog=ChamberDialog(None,original,requirements=requirements,replace_ids=ids)
    try:
        dialog.inputs['wall'].setValue(7)
        candidate=checked(dialog)
        assert dialog.apply_button.isEnabled() and len(candidate.parts)==34
        case=next(p for p in candidate.parts if p.id=='chamber-case')
        assert case.name=='사용자 본체 이름' and case.color=='#AB1234'
        assert candidate.mates[0].id=='attachment' and candidate.mates[0].parent=='chamber-case'
        assert original==unchanged
        assert not dialog.prefix.isEnabled()
    finally:dialog.reject()


def test_replacement_refuses_changed_component_set_instead_of_deleting_old_parts(requirements):
    chamber=build_chamber(requirements);source=chamber.as_design()
    raw=chamber.requirements.model_dump();raw['static_ports']=[]
    reduced=build_chamber(raw);unchanged=source.model_dump()
    with pytest.raises(ValueError,match='동일한 ID'):
        replacement_candidate(source,reduced,[p.id for p in source.parts])
    assert source.model_dump()==unchanged


def _externally_mounted_chamber(requirements):
    raw=build_chamber(requirements).as_design().model_dump()
    case=next(part for part in raw['parts'] if part['id']=='chamber-case')
    case['fixed']=False
    raw['parts'].append(Part(id='mount',name='외부 고정 지지대',fixed=True,
        geometry=dict(kind='cylinder',diameter=4,height=10),transform=dict(x=300)).model_dump())
    raw['mates']=[dict(id='case-mount',parent='mount',child='chamber-case',kind='rigid',
        x=-300,y=case['transform']['y'],z=case['transform']['z'])]
    return Design.model_validate(raw)


def test_replacement_refuses_world_bounds_move_overridden_by_existing_external_mate(requirements):
    source=_externally_mounted_chamber(requirements);unchanged=source.model_dump()
    moved=deepcopy(requirements)
    for endpoint in ('minimum_mm','maximum_mm'):moved['protected_swept_bounds'][endpoint][2]+=2
    chamber=build_chamber(moved)
    with pytest.raises(ValueError,match='외부 조립 구속.*위치'):
        replacement_candidate(source,chamber,[part.id for part in chamber.parts])
    assert source.model_dump()==unchanged


def test_replacement_allows_same_center_dimension_change_with_existing_external_mate(requirements):
    source=_externally_mounted_chamber(requirements);unchanged=source.model_dump()
    resized=deepcopy(requirements);resized['wall_thickness_mm']=7
    chamber=build_chamber(resized)
    candidate=replacement_candidate(source,chamber,[part.id for part in chamber.parts])
    case=next(part for part in candidate.parts if part.id=='chamber-case')
    assert case.transform==next(part for part in chamber.parts if part.id==case.id).transform
    assert candidate.mates==source.mates and not case.fixed
    assert candidate.assets[case.geometry.asset_id].sha256!=source.assets[case.geometry.asset_id].sha256
    assert source.model_dump()==unchanged
