"""Exact multiple print plates, conservative selection and atomic exports."""
from copy import deepcopy
import hashlib
import json
import math
import struct
from threading import Event
from zipfile import ZipFile

import pytest

from cadstudio.models import Design, Part
from cadstudio.kernel import build, exact_bounds
import cadstudio.printing as printing


def blocks(count=4, size=(12, 10, 3)):
    return Design(parts=[Part(id=f'p{i}', name=f'Body {i}',
        geometry=dict(kind='plate', length=size[0], width=size[1], thickness=size[2], hole_count=0),
        transform=dict(x=i * 30, y=20, z=45, rz=90)) for i in range(count)])


def stl_bounds(data):
    count = struct.unpack_from('<I', data, 80)[0]
    assert count and len(data) == 84 + count * 50
    vertices = []
    for index in range(count):
        values = struct.unpack_from('<12fH', data, 84 + index * 50)
        vertices.extend(values[3:12])
    return [min(vertices[i::3]) for i in range(3)] + [max(vertices[i::3]) for i in range(3)]


def test_exact_multi_plate_all_instances_floor_gap_and_source_unchanged():
    design = blocks(); before = design.model_dump()
    plates, results, warnings = printing.prepare_print_plates(design, [p.id for p in design.parts], bed=(26, 10, 20), gap=2)
    assert not warnings and len(plates) == 2
    assert design.model_dump() == before
    assert {p.id for plate in plates for p in plate.parts} == {'p0', 'p1', 'p2', 'p3'}
    assert all(not p.mates and p.electrical is None for p in plates)
    assert [r['print_plate_index'] for r in results] == [0, 1]
    assert results[0]['print_plate_assignments'] == results[1]['print_plate_assignments']
    for plate, result in zip(plates, results):
        a, b = map(exact_bounds, build(plate))
        assert a.zmin == pytest.approx(0) and b.zmin == pytest.approx(0)
        assert b.xmin - a.xmax == pytest.approx(2)
        assert result['stats']['volume'] == pytest.approx(720)
        assert not result['stats']['collisions']


def test_selected_boolean_body_preserves_unselected_tool_geometry_and_raw_ownership():
    design = Design(parts=[
        Part(id='body', name='Body', geometry=dict(kind='plate', length=20, width=20, thickness=10, hole_count=0),
             features=[dict(id='cut', kind='solid', operation='boolean', boolean_mode='cut', tool_part_id='tool')]),
        Part(id='tool', name='Cutter', geometry=dict(kind='cylinder', diameter=4, height=20), transform=dict(x=3, z=-5))])
    raw = design.model_dump(); before = deepcopy(raw)
    plates, results, warnings = printing.prepare_print_plates(raw, ['body'])
    assert raw == before and not warnings and len(plates[0].parts) == 1
    assert build(plates[0])[0].Volume() == pytest.approx(4000 - math.pi * 4 * 10)
    assert results[0]['print_instances'][0]['source_part_id'] == 'body'
    # Validation resolves this child's mate; it must not mutate caller-owned
    # nested dictionaries even when their saved pose initially needs solving.
    raw = blocks(2).model_dump()
    raw['mates'] = [dict(id='fixed', kind='rigid', parent='p0', child='p1', x=20)]
    before = deepcopy(raw)
    printing.prepare_print_plates(raw, ['p1'])
    assert raw == before
    printing.prepare_print(raw, ['p1'])
    assert raw == before


def test_manual_reservations_orientation_plate_assignment_and_stable_repreview():
    raw = blocks(3)
    poses = {'p0': dict(x=0, y=0, rx=90, ry=0, rz=0), 'p2': dict(x=5, y=-5, rx=0, ry=0, rz=90)}
    plates, results, warnings = printing.prepare_print_plates(raw, ['p0', 'p1', 'p2'], bed=(30, 30, 30),
        gap=2, placements=poses, plate_assignments={'p2': 1})
    assert not warnings and len(plates) == 2
    assert results[0]['print_placements']['p0'] == poses['p0']
    assert results[1]['print_placements']['p2'] == poses['p2']
    shape = next(s for p, s in zip(plates[0].parts, build(plates[0])) if p.id == 'p0')
    assert exact_bounds(shape).zlen == pytest.approx(10)
    placements = {k: v for r in results for k, v in r['print_placements'].items()}
    rebuilt, second, warnings = printing.prepare_print_plates(raw, ['p0', 'p1', 'p2'], bed=(30, 30, 30), gap=2,
        placements=placements, plate_assignments=results[0]['print_plate_assignments'])
    assert not warnings
    assert [p.model_dump() for p in rebuilt] == [p.model_dump() for p in plates]
    assert [r['print_placements'] for r in second] == [r['print_placements'] for r in results]


def test_copies_are_stable_distinct_complete_and_not_original_parts():
    design = blocks(1); before = design.model_dump()
    plates, results, warnings = printing.prepare_print_plates(design, ['p0'], copies={'p0': 5}, bed=(26, 10, 20), gap=2)
    assert not warnings and len(plates) == 3 and design.model_dump() == before
    members = [m for r in results for m in r['print_instances']]
    assert len({m['id'] for m in members}) == 5
    assert [m['copy_index'] for m in members] == [1, 2, 3, 4, 5]
    assert members[0]['id'] == 'p0' and all(m['source_part_id'] == 'p0' for m in members)
    assert sum(r['stats']['volume'] for r in results) == pytest.approx(5 * 360)
    _, repeated, _ = printing.prepare_print_plates(design, ['p0'], copies={'p0': 5}, bed=(26, 10, 20), gap=2)
    assert [r['print_instances'] for r in repeated] == [r['print_instances'] for r in results]


@pytest.mark.parametrize('name,kind', [
    ('Nominal M4x28 hub clamp bolt', 'bolt'), ('Nominal M8 support tie nut', 'nut'),
    ('M3 볼트 · 1', 'bolt'), ('M8 너트', 'nut'), ('M3_BOLT', 'bolt'),
    ('Nutating coupling', 'unknown'), ('threaded M3 frame', 'unknown'), ('boltless panel', 'unknown'),
    ('볼트용 프레임', 'unknown'), ('M4 clamp washer', 'other'), ('M8 retaining pin', 'other'),
    ('M4 nut washer', 'other'), ('Nominal radial locking screw', 'other'), ('볼트 너트', 'unknown'),
])
def test_named_bolt_nut_hints_do_not_guess_pin_washer_screw_or_dimensions(name, kind):
    part = Part(id='p', name=name, mechanical_function='fastener', geometry=dict(kind='cylinder', diameter=3, height=8))
    classification = printing.print_part_classification(part)
    assert classification['kind'] == kind
    if kind in ('bolt', 'nut'):
        assert classification['source'] == 'part_name_hint' and '미검증' in classification['reason']


def test_explicit_subtype_precedes_name_and_head_reference_is_not_bolt_identity():
    p = blocks(1).parts[0].model_dump(); p['mechanical_function'] = 'fastener'; p['name'] = 'M3 nut'
    p['product'] = {'specs': [{'label': 'fastener_type', 'value': 'washer'}]}
    assert printing.print_part_classification(p)['kind'] == 'other'
    p['product']['specs'] = [{'label': 'fastener_type', 'value': 'bolt'}]
    assert printing.print_part_classification(p) == dict(kind='bolt', source='explicit_metadata', reason='명시된 제품 종류 또는 카탈로그 분류입니다.')
    p['product']['specs'].append({'label': '체결 부품 종류', 'value': '너트'})
    assert printing.classify_print_part(p) == 'unknown'
    p['product'] = {'catalog_namespace': 'mechanical', 'catalog_id': 'iso4762_head_m4'}; p['name'] = 'Head reference'
    assert printing.classify_print_part(p) == 'unknown'
    p['product'] = {'name': 'M5 bolt'}
    assert printing.print_part_classification(p)['source'] == 'product_name_hint'
    p['name'] = 'Washer'; assert printing.classify_print_part(p) == 'other'


def test_exclusion_is_visible_reversible_unknown_preserved_and_empty_fails_closed():
    raw = blocks(4).model_dump()
    for part, name in zip(raw['parts'], ('M4 bolt', 'M8 nut', 'M4 washer', 'Unspecified fastener')):
        part.update(name=name, mechanical_function='fastener')
    before = deepcopy(raw)
    plates, results, warnings = printing.prepare_print_plates(raw, ['p0', 'p1', 'p2', 'p3'], exclude_fasteners=True,
        placements={'p0': {'x': 0, 'y': 0}}, plate_assignments={'p0': 0})
    assert not warnings and raw == before
    assert {p.id for p in plates[0].parts} == {'p2', 'p3'}
    assert results[0]['print_excluded_ids'] == ['p0', 'p1'] and results[0]['print_excluded_count'] == 2
    assert all(d['source'] == 'part_name_hint' for d in results[0]['print_excluded_details'])
    assert any(m['id'] == 'p3' and m['classification'] == 'unknown' for m in results[0]['print_instances'])
    restored, _, _ = printing.prepare_print_plates(raw, ['p0', 'p1'], exclude_fasteners=False)
    assert len(restored[0].parts) == 2
    with pytest.raises(ValueError, match='없습니다'):
        printing.prepare_print_plates(raw, ['p0', 'p1'], exclude_fasteners=True)


def test_excluded_copy_manual_controls_remain_reversible():
    raw = blocks(2).model_dump(); raw['parts'][0]['name'] = 'M4 bolt'
    _, results, _ = printing.prepare_print_plates(raw, ['p0', 'p1'], copies={'p0': 2})
    poses = {k: v for r in results for k, v in r['print_placements'].items()}
    plates, filtered, warnings = printing.prepare_print_plates(raw, ['p0', 'p1'], copies={'p0': 2}, placements=poses,
        plate_assignments=results[0]['print_plate_assignments'], exclude_fasteners=True)
    assert not warnings and [p.id for p in plates[0].parts] == ['p1']
    assert filtered[0]['print_excluded_ids'] == ['p0']


def test_oversized_height_and_xy_report_whole_part_and_block_export(tmp_path):
    design = blocks(1, (30, 10, 8))
    plates, results, warnings = printing.prepare_print_plates(design, ['p0'], bed=(20, 20, 5))
    assert warnings and '자르지' in warnings[0]
    assert len(plates[0].parts) == 1 and build(plates[0])[0].Volume() == pytest.approx(2400)
    with pytest.raises(ValueError, match='경고'):
        printing.export_print_stls(plates, results, tmp_path / 'oversized.zip')
    assert not list(tmp_path.iterdir())


def test_manual_overlap_and_pinned_capacity_are_warnings_without_relocation():
    poses = {'p0': {'x': 0, 'y': 0}, 'p1': {'x': 0, 'y': 0}}
    _, results, warnings = printing.prepare_print_plates(blocks(2), ['p0', 'p1'], placements=poses)
    assert warnings and results[0]['stats']['collisions']
    assert results[0]['print_placements']['p0']['x'] == results[0]['print_placements']['p1']['x'] == 0
    plates, _, warnings = printing.prepare_print_plates(blocks(2), ['p0', 'p1'], bed=(12, 10, 20),
        plate_assignments={'p0': 0, 'p1': 0})
    assert len(plates) == 1 and warnings


@pytest.mark.parametrize('options', [
    {'bed': (float('nan'), 20, 20)}, {'gap': -1}, {'rotation': (0, float('inf'), 0)},
    {'copies': {'p0': 0}}, {'copies': {'p0': True}}, {'copies': {'absent': 2}},
    {'plate_assignments': {'p0': 256}}, {'placements': {'p0': {'x': float('nan')}}},
    {'placements': {'absent': {'x': 0}}}, {'copies': {f'p{i}': 256 for i in range(5)}},
])
def test_invalid_batch_controls_fail_before_geometry(monkeypatch, options):
    def fail(*_):
        pytest.fail('invalid options reached geometry')
    monkeypatch.setattr(printing, 'build', fail)
    with pytest.raises(ValueError):
        printing.prepare_print_plates(blocks(5), [f'p{i}' for i in range(5)], **options)


def test_empty_unknown_selection_and_cancel_fail_closed():
    for ids in ([], ['absent']):
        with pytest.raises(ValueError, match='선택'):
            printing.prepare_print_plates(blocks(1), ids)
    with pytest.raises(printing.PrintCancelled):
        printing.prepare_print_plates(blocks(1), ['p0'], cancelled=lambda: True)


def test_zip_separate_real_stls_match_preview_and_portable_index(tmp_path):
    plates, results, _ = printing.prepare_print_plates(blocks(4), ['p0', 'p1', 'p2', 'p3'], bed=(26, 10, 20), gap=2)
    target = tmp_path / 'plates.zip'
    manifest = printing.export_print_stls(plates, results, target)
    with ZipFile(target) as archive:
        assert set(archive.namelist()) == {'plate-001.stl', 'plate-002.stl', 'print-index.json'}
        saved = json.loads(archive.read('print-index.json'))
        assert saved == manifest and saved['units'] == 'mm'
        assert 'source_path' not in json.dumps(saved) and str(tmp_path) not in json.dumps(saved)
        for record, result in zip(saved['plates'], results):
            data = archive.read(record['file'])
            assert hashlib.sha256(data).hexdigest() == record['sha256']
            assert stl_bounds(data) == pytest.approx(result['stats']['min'] + result['stats']['max'], abs=1e-5)
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('cancel', [False, True])
def test_batch_failure_or_mid_export_cancel_rolls_back_all_files(monkeypatch, tmp_path, cancel):
    plates, results, _ = printing.prepare_print_plates(blocks(4), ['p0', 'p1', 'p2', 'p3'], bed=(26, 10, 20), gap=2)
    target = tmp_path / 'existing.zip'; target.write_bytes(b'previous output')
    export = printing.cq.exporters.export; event = Event(); calls = []
    def checked(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2 and not cancel:
            raise OSError('second plate failure')
        export(*args, **kwargs)
        if cancel:
            event.set()
    monkeypatch.setattr(printing.cq.exporters, 'export', checked)
    with pytest.raises(printing.PrintCancelled if cancel else OSError):
        printing.export_print_stls(plates, results, target, cancelled=event.is_set)
    assert len(calls) == (1 if cancel else 2)
    assert target.read_bytes() == b'previous output'
    assert list(tmp_path.iterdir()) == [target]


def test_single_stl_cancel_after_actual_meshing_preserves_target(monkeypatch, tmp_path):
    prepared, _, _ = printing.prepare_print(blocks(1), ['p0'])
    target = tmp_path / 'existing.stl'; target.write_bytes(b'previous output')
    export = printing.cq.exporters.export; event = Event()
    def checked(*args, **kwargs):
        export(*args, **kwargs); event.set()
    monkeypatch.setattr(printing.cq.exporters, 'export', checked)
    with pytest.raises(printing.PrintCancelled):
        printing.export_print_stl(prepared, target, cancelled=event.is_set)
    assert target.read_bytes() == b'previous output' and list(tmp_path.iterdir()) == [target]


def test_changed_batch_snapshot_is_rejected_before_target_creation(tmp_path):
    plates, results, _ = printing.prepare_print_plates(blocks(1), ['p0'])
    plates[0].parts[0].transform.x = 50
    with pytest.raises(ValueError, match='변경'):
        printing.export_print_stls(plates, results, tmp_path / 'changed.zip')
    assert not list(tmp_path.iterdir())
