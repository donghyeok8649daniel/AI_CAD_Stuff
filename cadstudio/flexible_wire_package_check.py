"""Bounded source/frozen policy check using tiny owned solids and inert Qt.

No source paths, pytest, user projects, VTK rendering, network or hardware are
needed. The CLI runs this in its own process and writes one exclusive receipt.
"""


def run(report_path):
    from pathlib import Path
    import json
    import os
    import sys
    import time
    import traceback

    output = Path(report_path).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    from . import __version__, __build_id__

    start = time.monotonic()
    checks = []
    report = dict(success=False, version=__version__, build_id=__build_id__,
                  frozen=bool(getattr(sys, 'frozen', False)), checks=checks,
                  scope='four overlapping synthetic boxes, two Boolean bodies, inert offscreen caption only',
                  user_project_reads=0, original_projects_modified=0,
                  native_window_shown=False, VTK_render_calls=0,
                  network_or_paid_API_calls=0, hardware_IO=False,
                  physical_or_electrical_qualification=False)

    def check(name, value, **detail):
        checks.append(dict(name=name, passed=bool(value), **detail))
        if not value:
            raise AssertionError(name)

    def raises(call, exception, message):
        try:
            call()
        except exception as exc:
            return message in str(exc)
        return False

    try:
        import cadquery as cq
        from .models import Design, Part
        from .part_product import ProductMetadata, ProductSpec
        from .collision_policy import (
            FLEXIBLE_WIRE_LABEL, FLEXIBLE_WIRE_VALUE, flexible_wire_part_ids,
            collision_exclusion_stats, collision_caption,
        )
        from .interference import exact_collisions, assess
        from .kernel import _preview_result, KERNEL_LOCK
        from .motion_playback import _sample_collision_hits
        from . import preview_metadata

        geometry = dict(kind='plate', length=10, width=10, thickness=10, hole_count=0)
        base = Design(parts=[Part(id=identifier, name=name, geometry=geometry, role='electrical')
                     for identifier, name in [('mount', 'Rigid mounting block'),
                                              ('connector', 'Rigid electrical connector'),
                                              ('sweep', '전선처럼 이름 붙인 강체'),
                                              ('wire', 'Explicit flexible body')]])
        base.parts[2].geometry = Part(id='s', name='S', geometry=dict(kind='sweep')).geometry
        tagged = base.model_copy(deep=True)
        tagged.parts[-1].product = ProductMetadata(specs=[
            ProductSpec(label=FLEXIBLE_WIRE_LABEL, value=FLEXIBLE_WIRE_VALUE)])
        original = tagged.model_dump()
        check('typed_and_saved_mapping_read_the_same_exact_tag',
              flexible_wire_part_ids(tagged) == flexible_wire_part_ids(original) == ['wire'])
        shapes = [cq.Workplane('XY').box(10, 10, 10).val() for _ in range(4)]
        callbacks, guards = [], []
        hits = exact_collisions(tagged, shapes, check=lambda: guards.append(1),
                                completed=lambda: callbacks.append(1))
        def pairs(rows):
            return {frozenset((row['a'], row['b'])) for row in rows}
        rigid_pairs = {frozenset(pair) for pair in
                       [('mount', 'connector'), ('mount', 'sweep'), ('connector', 'sweep')]}
        check('only_three_tagged_wire_pairs_excluded_three_rigid_pairs_remain',
              pairs(hits) == rigid_pairs and all(abs(h['volume']-1000) < 1e-6 for h in hits),
              rigid_pairs=3, excluded_pairs=3)
        check('every_pair_retains_cancellation_and_completion_checkpoint',
              len(callbacks) == len(guards) == 6 and tagged.model_dump() == original)
        legacy_hits = exact_collisions(base, shapes)
        grouped = base.model_dump()
        grouped['part_groups'] = [dict(id='g', name='G', part_ids=['mount', 'connector'])]
        check('untagged_electrical_sweep_name_and_group_never_exempt_bodies',
              len(legacy_hits) == len(exact_collisions(Design.model_validate(grouped), shapes)) == 6)
        strict = []
        for label, value in [('간섭분류', '유연 전선'), ('간섭 분류', '유연 전선 '),
                             ('간섭 분류', 'rigid connector'), ('간섭 분류', None)]:
            variant = base.model_copy(deep=True)
            variant.parts[-1].product = ProductMetadata(specs=[ProductSpec(label=label, value=value)])
            strict.append(not flexible_wire_part_ids(variant) and len(exact_collisions(variant, shapes)) == 6)
        check('four_similar_or_empty_spec_values_do_not_exempt', all(strict))

        # Build two actual minimal Boolean bodies through the ordinary kernel.
        boolean = Design(parts=[Part(id='a', name='A', geometry=geometry,
                              features=[dict(id='union', kind='solid', operation='boolean',
                                             tool_part_id='b', boolean_mode='union')]),
                                Part(id='b', name='Retained rigid tool', geometry=geometry)])
        references = assess(boolean)
        boolean.parts[0].features[0].suppressed = True
        suppressed = assess(boolean)
        check('real_retained_Boolean_tool_remains_reference_and_suppressed_tool_is_collision',
              len(references['references']) == 1 and not references['blocked']
              and len(suppressed['blocked']) == 1 and suppressed['blocked'][0]['volume'] > 0)

        meshes = [dict(id=p.id, name=p.name, valid=True, volume=s.Volume(), triangles=[])
                  for p, s in zip(tagged.parts, shapes)]
        with KERNEL_LOCK:
            result = _preview_result(tagged, shapes, meshes)
        stats = result['stats']
        check('preview_stats_identify_only_saved_excluded_body',
              stats['flexible_wire_excluded_ids'] == ['wire']
              and stats['flexible_wire_excluded_count'] == 1
              and collision_exclusion_stats(tagged)['flexible_wire_excluded_count'] == 1
              and pairs(stats['collisions']) == rigid_pairs)
        zero_caption = collision_caption(dict(collisions=[], flexible_wire_excluded_count=18))
        check('zero_rigid_caption_declares_exclusions_legacy_caption_preserved',
              zero_caption == '고정부품 간섭 0건 · 전선 18개 제외'
              and collision_caption(stats) == '고정부품 간섭 3건 · 전선 1개 제외'
              and collision_caption(dict(collisions=[])) == ''
              and collision_caption(dict(collisions=[{}])) == '간섭 1건')

        def cached(design):
            return dict(_geometry_key=preview_metadata.geometry_key(design),
                        meshes=[dict(id=p.id, name=p.name, color=p.color) for p in design.parts],
                        stats=dict(collisions=[dict(a='mount', b='wire', volume=1000)]))
        check('add_and_remove_tag_invalidate_typed_and_rawdict_baseline_verdicts',
              preview_metadata.geometry_key(base) != preview_metadata.geometry_key(tagged)
              and preview_metadata.reuse_preview(tagged, base.model_dump(), cached(base)) is None
              and preview_metadata.reuse_preview(base, tagged.model_dump(), cached(tagged)) is None)
        renamed = base.model_copy(deep=True)
        renamed.parts[0].name = 'Metadata-only rename'
        prior = cached(base)
        kept = preview_metadata.reuse_preview(renamed, base.model_dump(), prior)
        check('ordinary_rawdict_metadata_baseline_still_reuses_immutable_geometry',
              kept is not None and kept['meshes'][0]['name'] == 'Metadata-only rename'
              and kept['stats'] is prior['stats'])
        original_inputs = preview_metadata.geometry_inputs
        def without_products(design):
            raw = original_inputs(design)
            for part in raw['parts']:
                part.pop('product', None)
            return raw
        try:
            preview_metadata.geometry_inputs = without_products
            check('explicit_policy_guard_is_independent_of_future_metadata_key_optimization',
                  without_products(base) == without_products(tagged)
                  and preview_metadata.reuse_preview(tagged, base.model_dump(), cached(base)) is None
                  and preview_metadata.reuse_preview(base, tagged.model_dump(), cached(tagged)) is None)
        finally:
            preview_metadata.geometry_inputs = original_inputs

        moved = tagged.model_copy(deep=True)
        moved.parts[-1].transform.x = 1
        moved_shapes = shapes[:-1] + [shapes[-1].translate((1, 0, 0))]
        callbacks, guards = [], []
        sampled, checked, reused = _sample_collision_hits(
            moved, moved_shapes, tagged, hits, lambda: guards.append(1),
            completed=lambda: callbacks.append(1))
        check('optimized_motion_uses_same_wire_scope_and_preserves_checkpoints',
              pairs(sampled) == rigid_pairs and checked == reused == len(callbacks) == len(guards) == 3)
        legacy_moved = base.model_copy(deep=True)
        legacy_moved.parts[-1].transform.x = 1
        untagged, _, _ = _sample_collision_hits(legacy_moved, moved_shapes, base, legacy_hits, lambda: None)
        check('optimized_untagged_motion_keeps_all_six_actual_pairs',
              len(untagged) == 6 and all(abs(h['volume']-(900 if 'wire' in (h['a'], h['b']) else 1000)) < 1e-6 for h in untagged))
        check('optimized_baseline_rejects_a_changed_saved_exclusion_set',
              raises(lambda: _sample_collision_hits(tagged, shapes, base, legacy_hits, lambda: None), ValueError, '간섭 검사 분류'))
        completed = []
        def cancel():
            raise RuntimeError('cancelled owned work')
        check('explicit_exclusions_do_not_disable_cooperative_cancellation',
              raises(lambda: exact_collisions(tagged, shapes, check=cancel,
                                              completed=lambda: completed.append(1)), RuntimeError, 'cancelled owned work')
              and not completed)

        # Only QLabel is instantiated. No Viewport, RenderWindow or native CAD
        # window is created, shown or manipulated by this package check.
        from PySide6.QtWidgets import QApplication
        from shiboken6 import delete
        app = QApplication.instance()
        previous_platform = os.environ.get('QT_QPA_PLATFORM')
        if app is None:
            os.environ['QT_QPA_PLATFORM'] = 'offscreen'
            app = QApplication([])
            if previous_platform is None:
                os.environ.pop('QT_QPA_PLATFORM', None)
            else:
                os.environ['QT_QPA_PLATFORM'] = previous_platform
        check('caption_check_is_inert_offscreen_Qt', app.platformName() == 'offscreen')
        from .native.viewport import ViewportCaption
        caption = ViewportCaption(zero_caption + '   ·   345개 부품')
        try:
            check('native_caption_keeps_zero_scope_visible_in_full_text_and_tooltip',
                  caption.text().startswith(zero_caption)
                  and caption.toolTip() == caption.text()
                  and not caption.isVisible())
        finally:
            delete(caption)

        if getattr(sys, 'frozen', False):
            from .program_drive_provenance import assert_trace_producer
            from . import program_simulation
            proof = assert_trace_producer(program_simulation, program_simulation.simulate_program)
            check('frozen_build_identity_is_bound_to_executed_bundle',
                  proof['mode'] == 'verified_frozen_bundle' and proof['build_id'] == __build_id__)
        report['success'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    report.update(count=len(checks), seconds=time.monotonic()-start)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return 0 if report['success'] else 1
