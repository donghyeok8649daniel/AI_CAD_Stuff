from copy import deepcopy
import pytest
from cadstudio.models import Design, Part, SavedSketch, Extrusion
from cadstudio.kernel import preview, local_shape, _part_cached
from cadstudio.preview_metadata import reuse_preview


def sample():
    return Design(parts=[Part(id='body', name='Before', geometry=dict(kind='cylinder',
                         diameter=20, height=10))])


def test_verified_geometry_reused_without_mutating_old_metadata():
    old = sample()
    result = preview(old)
    data = old.model_dump()
    data.update(name='New document', electrical=dict(nodes=['GND'], components=[]))
    data['parts'][0].update(name='New name', color='#FFD400', role='electrical')
    changed = Design.model_validate(data)
    reused = reuse_preview(changed, old.model_dump(), result)
    assert reused['meshes'][0]['name'] == 'New name'
    assert reused['meshes'][0]['color'] == '#FFD400'
    assert reused['meshes'][0]['vertices'] is result['meshes'][0]['vertices']
    assert reused['stats'] is result['stats']
    assert result['meshes'][0]['name'] == 'Before'
    assert result['meshes'][0]['color'] != '#FFD400'


@pytest.mark.parametrize('change', ['dimension', 'pose', 'fixed', 'parameter', 'sketch', 'groups'])
def test_non_metadata_change_never_reuses_preview(change):
    old = sample()
    result = preview(old)
    raw = old.model_dump()
    if change == 'dimension':raw['parts'][0]['geometry']['height'] = 15
    elif change == 'pose':raw['parts'][0]['transform']['x'] = 5
    elif change == 'fixed':raw['parts'][0]['fixed'] = True
    elif change == 'parameter':raw['parameters'] = {'h': '10'}
    elif change == 'sketch':raw['sketches'] = [SavedSketch(id='s',name='S',geometry=Extrusion()).model_dump()]
    else:
        raw['parts'].append(Part(id='b', name='b', geometry=dict(kind='cylinder'), transform=dict(x=50)).model_dump())
        raw['part_groups'] = [dict(id='g', name='g', part_ids=['body','b'])]
    assert reuse_preview(Design.model_validate(raw), old.model_dump(), result) is None


def test_local_brep_cache_ignores_display_metadata_but_not_dimensions():
    old = sample()
    _part_cached.cache_clear()
    local_shape(old, old.parts[0])
    before = _part_cached.cache_info()
    changed = old.model_copy(deep=True)
    changed.parts[0].name = 'Renamed'
    changed.parts[0].color = '#FFD400'
    changed.parts[0].role = 'electrical'
    local_shape(changed, changed.parts[0])
    assert _part_cached.cache_info().hits == before.hits+1
    changed.parts[0].geometry.height += 1
    local_shape(changed, changed.parts[0])
    assert _part_cached.cache_info().misses == before.misses+1


def test_result_for_other_geometry_with_same_ids_is_never_reused():
    old=sample()
    other=old.model_copy(deep=True);other.parts[0].geometry.height=25
    different=preview(other)
    renamed=old.model_copy(deep=True);renamed.parts[0].name='Renamed'
    assert reuse_preview(renamed,old.model_dump(),different) is None
    untagged=preview(old);untagged.pop('_geometry_key')
    assert reuse_preview(renamed,old.model_dump(),untagged) is None
