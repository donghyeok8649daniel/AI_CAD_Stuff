from copy import deepcopy

import pytest

from cadstudio import kernel
from cadstudio.models import Design, Part, Material


def parts(count=40):
    return Design(parts=[Part(id=f'p{i}', name=f'Part {i}',
        geometry=dict(kind='cylinder', diameter=10+i/10, height=5),
        transform=dict(x=i*20)) for i in range(count)])


def test_large_assembly_reuses_geometry_between_poses_and_releases_session():
    design = parts()
    kernel._part_cached.cache_clear()
    with kernel.local_shape_session():
        shapes = [kernel.local_shape(design, p) for p in design.parts]
        misses = kernel._part_cached.cache_info().misses
        moved = design.model_copy(deep=True)
        for p in moved.parts:
            p.transform.z += 8
        again = [kernel.local_shape(moved, p) for p in moved.parts]
        assert all(a is b for a, b in zip(shapes, again))
        assert kernel._part_cached.cache_info().misses == misses == 40
        cache = kernel._local_shape_session.get()
        assert len(cache) == 40
    assert cache == {} and kernel._local_shape_session.get() is None
    assert kernel._part_cached.cache_info().currsize <= 32


def test_material_and_identity_metadata_share_brep_without_changing_parts():
    design = parts(1)
    original = design.model_dump()
    kernel._part_cached.cache_clear()
    a = kernel.local_shape(design, design.parts[0])
    other = design.model_copy(deep=True)
    other.parts[0].id = 'renamed'
    other.parts[0].fixed = True
    other.parts[0].material = Material(name='Declared density', density=1000)
    b = kernel.local_shape(other, other.parts[0])
    assert a is b
    assert kernel._part_cached.cache_info().misses == 1
    assert design.model_dump() == original
    other.parts[0].geometry.height += 1
    assert kernel.local_shape(other, other.parts[0]).Volume() > a.Volume()


def test_nested_cancel_releases_owned_shapes_and_preserves_outer_session():
    with pytest.raises(RuntimeError):
        with kernel.local_shape_session():
            cache = kernel._local_shape_session.get()
            with kernel.local_shape_session():
                assert kernel._local_shape_session.get() is cache
                design = parts(1)
                kernel.local_shape(design, design.parts[0])
            assert cache
            raise RuntimeError('cancel')
    assert not cache and kernel._local_shape_session.get() is None


def test_boolean_relative_motion_still_invalidates_local_shape():
    design = Design(parts=[
        Part(id='body', name='Body', geometry=dict(kind='cylinder', diameter=20, height=10),
             features=[dict(id='cut', kind='solid', operation='boolean',
                            boolean_mode='cut', tool_part_id='tool')]),
        Part(id='tool', name='Tool', geometry=dict(kind='cylinder', diameter=4, height=10))])
    with kernel.local_shape_session():
        original = kernel.local_shape(design, design.parts[0])
        moved = design.model_copy(deep=True)
        moved.parts[1].transform.x = 9
        changed = kernel.local_shape(moved, moved.parts[0])
        assert changed is not original and changed.Volume() > original.Volume()
        moved.parts[1].transform.x = 20
        with pytest.raises(ValueError):
            kernel.local_shape(moved, moved.parts[0])
        both = design.model_copy(deep=True)
        both.parts[0].transform.x = both.parts[1].transform.x = 10
        assert kernel.local_shape(both, both.parts[0]).Volume() == pytest.approx(original.Volume())


def test_joint_travel_reuses_more_than_32_parts():
    from cadstudio.interference import check_joint_travel
    design = parts(40)
    raw = design.model_dump()
    raw['parts'][0]['fixed'] = True
    raw['mates'] = [dict(id='slide', parent='p0', child='p1', kind='slider', x=20, z=0)]
    before = Design.model_validate(raw)
    after = deepcopy(raw)
    after['mates'][0]['z'] = 2
    kernel._part_cached.cache_clear()
    kernel._build_cached.cache_clear()
    report = check_joint_travel(before, Design.model_validate(after))
    assert not report['blocked'] and report['samples'] == 5
    assert kernel._part_cached.cache_info().misses == 40
    assert kernel._local_shape_session.get() is None
    # The two attached cylinders initially overlap. Reuse must not skip it.
    raw['mates'][0]['x'] = 0
    after['mates'][0]['x'] = 0
    before = Design.model_validate(raw)
    report = check_joint_travel(before, Design.model_validate(after))
    assert report['blocked'] and report['fraction'] == 0
    assert kernel._local_shape_session.get() is None
