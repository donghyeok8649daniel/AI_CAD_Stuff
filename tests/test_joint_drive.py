"""Mechanical drive limits are coordinates; swept clearance is a separate check."""
from copy import deepcopy

import pytest

from cadstudio.assembly_motion import set_joint_motion
from cadstudio.gears import add_gear_pair
from cadstudio.interference import exact_collisions, survey_joint_drive
from cadstudio.kernel import _part_cached, build, local_shape
from cadstudio.models import Design
from test_interference import swing


@pytest.mark.parametrize('teeth_a,teeth_b', [(20, 40), (40, 20), (32, 24)])
def test_gear_pair_drive_range_uses_ratio_instead_of_arbitrary_half_turn(teeth_a, teeth_b):
    design = add_gear_pair(prefix='drive-', teeth_a=teeth_a, teeth_b=teeth_b)
    initial = design.model_dump()
    phase = design.motion_links[0].offset
    ratio = teeth_a / teeth_b
    lo, hi = design.mates[0].limits['rz']
    assert lo == pytest.approx(max(-360, (phase - 360) / ratio))
    assert hi == pytest.approx(min(360, (phase + 360) / ratio))
    if teeth_a == 20 and teeth_b == 40:
        assert [lo, hi] == [-360, 360]
    for angle in (lo, (lo + hi) / 2, hi):
        raw = deepcopy(initial)
        set_joint_motion(raw, 'drive-drive', {'rz': angle})
        pose = Design.model_validate(raw)
        assert pose.mates[1].rz == pytest.approx(phase - ratio * angle)
        assert -360 <= pose.mates[1].rz <= 360
        assert not exact_collisions(pose)
    assert design.model_dump() == initial


def test_survey_reports_clear_samples_and_first_physical_collision():
    design = swing(-90)
    original = design.model_dump()
    result = survey_joint_drive(design, 'hinge', 'rz')
    assert result['unit'] == 'deg' and result['current'] == -90
    assert result['negative']['safe'] == -180
    assert not result['negative']['blocked']
    positive = result['positive']
    assert positive['blocked'] and -90 < positive['safe'] < positive['first_hit'] < 180
    assert positive['first_hit'] - positive['safe'] <= 2.000001
    assert positive['collisions']
    assert result['samples'] > 2
    raw = deepcopy(original)
    set_joint_motion(raw, 'hinge', {'rz': positive['safe']})
    assert not exact_collisions(Design.model_validate(raw))
    set_joint_motion(raw, 'hinge', {'rz': positive['first_hit']})
    assert exact_collisions(Design.model_validate(raw))
    assert design.model_dump() == original


def test_survey_rejects_driven_axis_and_preserves_document_on_cancel():
    design = add_gear_pair(prefix='g-')
    original = design.model_dump()
    with pytest.raises(ValueError, match='구동 관절'):
        survey_joint_drive(design, 'g-driven', 'rz')
    with pytest.raises(RuntimeError, match='cancel'):
        survey_joint_drive(design, 'g-drive', 'rz', check=lambda: (_ for _ in ()).throw(RuntimeError('cancel')))
    assert design.model_dump() == original


def test_survey_includes_linked_output_pose_without_changing_limits():
    design = add_gear_pair(prefix='g-')
    raw = design.model_dump()
    raw['mates'][0]['limits'] = {'rz': [-5, 5]}
    design = Design.model_validate(raw)
    original = design.model_dump()
    result = survey_joint_drive(design, 'g-drive', 'rz')
    assert not result['negative']['blocked'] and not result['positive']['blocked']
    assert result['negative']['safe'] == -5 and result['positive']['safe'] == 5
    assert design.model_dump() == original


def test_local_gear_shape_reused_across_joint_poses():
    design = add_gear_pair(prefix='g-')
    _part_cached.cache_clear()
    first = local_shape(design, design.parts[1])
    raw = design.model_dump()
    set_joint_motion(raw, 'g-drive', {'rz': 45})
    moved = Design.model_validate(raw)
    second = local_shape(moved, moved.parts[1])
    assert second is first
    assert second.Volume() == pytest.approx(first.Volume())
    assert build(moved)[1].Volume() == pytest.approx(build(design)[1].Volume())


def test_boolean_tool_relative_motion_invalidates_local_shape_cache():
    body = dict(id='body', name='body', geometry=dict(kind='cylinder', diameter=12, height=10),
                features=[dict(id='bore', kind='solid', operation='boolean',
                               boolean_mode='cut', tool_part_id='tool')])
    cutter = dict(id='tool', name='tool', geometry=dict(kind='cylinder', diameter=4, height=10))
    design = Design(parts=[body, cutter])
    _part_cached.cache_clear()
    first = local_shape(design, design.parts[0])
    raw = design.model_dump()
    raw['parts'][1]['transform']['x'] = 5
    shifted = Design.model_validate(raw)
    second = local_shape(shifted, shifted.parts[0])
    assert second is not first
    assert second.Volume() > first.Volume()
