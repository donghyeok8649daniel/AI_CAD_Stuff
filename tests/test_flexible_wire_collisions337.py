"""Small real-solid regressions for explicit flexible-wire collision scope."""
from copy import deepcopy

import cadquery as cq
import pytest

from cadstudio.models import Design, Part
from cadstudio.part_product import ProductMetadata, ProductSpec
from cadstudio.collision_policy import (
    FLEXIBLE_WIRE_LABEL, FLEXIBLE_WIRE_VALUE, flexible_wire_part_ids,
    collision_exclusion_stats, collision_caption,
)
from cadstudio.interference import exact_collisions
from cadstudio.kernel import _preview_result
from cadstudio import preview_metadata
from cadstudio.motion_playback import _sample_collision_hits


def fixture_design(tagged=True):
    geometry = dict(kind='plate', length=10, width=10, thickness=10, hole_count=0)
    parts = [Part(id=identifier, name=name, geometry=geometry, role='electrical')
             for identifier, name in [('mount', 'Rigid mounting block'),
                                      ('connector', 'Rigid electrical connector'),
                                      ('sweep', '전선처럼 이름 붙인 강체'),
                                      ('wire', 'Explicit flexible body')]]
    parts[2].geometry = Part(id='s', name='S', geometry=dict(kind='sweep')).geometry
    if tagged:
        parts[-1].product = ProductMetadata(specs=[
            ProductSpec(label=FLEXIBLE_WIRE_LABEL, value=FLEXIBLE_WIRE_VALUE)])
    return Design(parts=parts)


def overlapping_shapes():
    # Supplied exact boxes ensure classification cannot depend on geometry kind.
    return [cq.Workplane('XY').box(10, 10, 10).val() for _ in range(4)]


def pairs(hits):
    return {frozenset((hit['a'], hit['b'])) for hit in hits}


def test_only_exact_saved_spec_exempts_wire_and_preserves_rigid_pairs_callbacks():
    design = fixture_design()
    before = design.model_dump()
    checks, completed = [], []
    hits = exact_collisions(design, overlapping_shapes(),
                            check=lambda: checks.append(1),
                            completed=lambda: completed.append(1))
    assert pairs(hits) == {frozenset(pair) for pair in
                           [('mount', 'connector'), ('mount', 'sweep'), ('connector', 'sweep')]}
    assert all(hit['volume'] == pytest.approx(1000) for hit in hits)
    assert len(checks) == len(completed) == 6
    assert flexible_wire_part_ids(design) == flexible_wire_part_ids(before) == ['wire']
    assert design.model_dump() == before
    # Electrical role, a wire-like name and a sweep do not grant an exemption.
    legacy = fixture_design(False)
    assert len(exact_collisions(legacy, overlapping_shapes())) == 6
    raw = legacy.model_dump()
    raw['part_groups'] = [dict(id='g', name='G', part_ids=['mount', 'connector'])]
    assert len(exact_collisions(Design.model_validate(raw), overlapping_shapes())) == 6


@pytest.mark.parametrize('label,value', [
    ('간섭분류', '유연 전선'), ('간섭 분류', '유연 전선 '),
    ('간섭 분류', 'rigid connector'), ('간섭 분류', None),
])
def test_similar_names_or_values_do_not_exempt_bodies(label, value):
    design = fixture_design(False)
    design.parts[-1].product = ProductMetadata(specs=[ProductSpec(label=label, value=value)])
    assert flexible_wire_part_ids(design) == []
    assert len(exact_collisions(design, overlapping_shapes())) == 6


def test_exact_preview_reports_excluded_ids_and_explicit_zero_rigid_caption():
    design, shapes = fixture_design(), overlapping_shapes()
    meshes = [dict(id=part.id, name=part.name, valid=True, volume=shape.Volume(), triangles=[])
              for part, shape in zip(design.parts, shapes)]
    result = _preview_result(design, shapes, meshes)
    assert collision_exclusion_stats(design) == dict(
        flexible_wire_excluded_ids=['wire'], flexible_wire_excluded_count=1)
    assert result['stats']['flexible_wire_excluded_ids'] == ['wire']
    assert len(result['stats']['collisions']) == 3
    assert collision_caption(result['stats']) == '고정부품 간섭 3건 · 전선 1개 제외'
    assert collision_caption(dict(collisions=[], flexible_wire_excluded_count=18)) == '고정부품 간섭 0건 · 전선 18개 제외'
    assert collision_caption(dict(collisions=[])) == ''
    assert collision_caption(dict(collisions=[{}])) == '간섭 1건'


def cached_preview(design):
    return dict(_geometry_key=preview_metadata.geometry_key(design),
                meshes=[dict(id=p.id, name=p.name, color=p.color) for p in design.parts],
                stats=dict(collisions=[dict(a='mount', b='wire', volume=1000)]))


def test_tag_added_removed_invalidates_cache_for_typed_and_raw_baselines():
    before, tagged = fixture_design(False), fixture_design(True)
    assert preview_metadata.geometry_key(before) != preview_metadata.geometry_key(tagged)
    assert preview_metadata.reuse_preview(tagged, before.model_dump(), cached_preview(before)) is None
    assert preview_metadata.reuse_preview(before, tagged.model_dump(), cached_preview(tagged)) is None
    renamed = before.model_copy(deep=True)
    renamed.parts[0].name = 'Metadata-only rename'
    result = cached_preview(before)
    reused = preview_metadata.reuse_preview(renamed, before.model_dump(), result)
    assert reused is not None and reused['meshes'][0]['name'] == 'Metadata-only rename'
    assert reused['stats'] is result['stats']


def test_explicit_policy_guard_survives_future_metadata_key_optimization(monkeypatch):
    original = preview_metadata.geometry_inputs
    def without_products(design):
        raw = original(design)
        for part in raw['parts']:
            part.pop('product', None)
        return raw
    monkeypatch.setattr(preview_metadata, 'geometry_inputs', without_products)
    before, tagged = fixture_design(False), fixture_design(True)
    assert without_products(before) == without_products(tagged)
    assert preview_metadata.reuse_preview(tagged, before.model_dump(), cached_preview(before)) is None
    assert preview_metadata.reuse_preview(before, tagged.model_dump(), cached_preview(tagged)) is None


def test_optimized_moving_pairs_use_identical_wire_scope_and_keep_callbacks():
    base, shapes = fixture_design(), overlapping_shapes()
    baseline_hits = exact_collisions(base, shapes)
    current = base.model_copy(deep=True)
    current.parts[-1].transform.x = 1
    moved_shapes = shapes[:-1] + [shapes[-1].translate((1, 0, 0))]
    checks, completed = [], []
    hits, checked, reused = _sample_collision_hits(
        current, moved_shapes, base, baseline_hits, lambda: checks.append(1),
        completed=lambda: completed.append(1))
    assert pairs(hits) == pairs(baseline_hits)
    assert checked == reused == len(checks) == len(completed) == 3
    # The same actual movement still detects every pair when no tag was saved.
    legacy = fixture_design(False)
    legacy_current = legacy.model_copy(deep=True)
    legacy_current.parts[-1].transform.x = 1
    legacy_hits, _, _ = _sample_collision_hits(
        legacy_current, moved_shapes, legacy, exact_collisions(legacy, shapes), lambda: None)
    assert len(legacy_hits) == 6
    assert all(hit['volume'] == pytest.approx(900 if 'wire' in (hit['a'], hit['b']) else 1000)
               for hit in legacy_hits)


def test_optimized_baseline_cannot_reuse_different_wire_policy():
    base, shapes = fixture_design(False), overlapping_shapes()
    changed = fixture_design(True)
    with pytest.raises(ValueError, match='간섭 검사 분류'):
        _sample_collision_hits(changed, shapes, base, exact_collisions(base, shapes), lambda: None)


def test_excluded_pairs_remain_cooperatively_cancellable():
    design = fixture_design()
    completed = []
    def cancel():
        raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        exact_collisions(design, overlapping_shapes(), check=cancel,
                         completed=lambda: completed.append(1))
    assert not completed
