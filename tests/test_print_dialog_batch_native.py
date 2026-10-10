"""Print UI state/transactions with real CAD preparation, without a GL renderer.

The separate native smoke covers pixels and picking. These tests keep Qt
workers and actual STL/ZIP output, and explicitly suppress rendering only.
"""
from copy import deepcopy
import json
import threading
import time
import zipfile
import pytest
from PySide6.QtCore import QEvent, QThreadPool
from PySide6.QtWidgets import QApplication
from cadstudio.models import Design, Part
from cadstudio.native.document import Document
from cadstudio.native.print_dialog import PrintDialog
from cadstudio.native import print_dialog
from cadstudio.native.viewport import CADViewport


def fixture_design(hardware=True):
    parts = [Part(id=key, name=key, geometry=dict(kind='plate', length=20, width=10, thickness=3, hole_count=0),
                  transform=dict(x=100 + index * 30, y=40, rz=90)) for index, key in enumerate(('body-a', 'body-b'))]
    if hardware:
        for key, name in [('bolt', 'M8 bolt'), ('nut', 'M8 nut'), ('washer', 'M8 washer'), ('pin', 'retaining pin')]:
            parts.append(Part(id=key, name=name, mechanical_function='fastener',
                              geometry=dict(kind='plate', length=2, width=2, thickness=2, hole_count=0)))
    return Design(name='Print transaction fixture', parts=parts)


@pytest.fixture(scope='module')
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    assert QThreadPool.globalInstance().waitForDone(30000)


@pytest.fixture
def dialogs(app, monkeypatch):
    # This is a UI state test, not pixel evidence. Initializing a WGL window
    # is unnecessary; the normal renderer is exercised by the owned smoke.
    monkeypatch.setattr(CADViewport, 'initialize', lambda self: setattr(self, 'initialized', True))
    monkeypatch.setattr(CADViewport, 'render', lambda self: None)
    created = []
    def create(raw=None, selected=()):
        dialog = PrintDialog(None, raw or fixture_design().model_dump(), selected)
        created.append(dialog); dialog.viewport.initialize()
        return dialog
    yield create
    for dialog in created:
        if dialog.alive: dialog.reject()
    assert QThreadPool.globalInstance().waitForDone(30000)
    for dialog in created: dialog.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()


def until(app, condition):
    end = time.monotonic() + 30
    while not condition() and time.monotonic() < end:
        app.processEvents(); time.sleep(.005)
    assert condition()


def ready(app, dialog):
    until(app, lambda: not dialog.running and not dialog.timer.isActive())
    assert dialog.checked is not None, dialog.status.text()
    assert dialog.checked_batch is not None


def small_bed(dialog, x=25, y=15):
    dialog.bed[0].setValue(x); dialog.bed[1].setValue(y)
    dialog.auto_pack()


def members(dialog):
    return {part.id for plate in dialog.checked_batch['plates'] for part in plate.parts}


def test_current_all_clear_and_narrow_exclusion_preserve_source_history(app, dialogs):
    document = Document(); document.commit(fixture_design(), 'Fixture source')
    before = document.project().model_dump(); raw = document.design; source = deepcopy(raw)
    dialog = dialogs(raw, ['body-b', 'bolt']); ready(app, dialog)
    assert members(dialog) == {'body-b', 'bolt'} and not dialog.exclude_fasteners.isChecked()
    dialog.select_parts(dialog.part_boxes); ready(app, dialog)
    assert len(members(dialog)) == 6
    dialog.exclude_fasteners.setChecked(True)
    assert dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled()
    ready(app, dialog)
    assert members(dialog) == {'body-a', 'body-b', 'washer', 'pin'}
    assert all(dialog.part_boxes[key].isChecked() for key in ('bolt', 'nut'))
    assert 'bolt' in dialog.excluded_summary.toolTip() and 'nut' in dialog.excluded_summary.toolTip()
    assert '미검증' in dialog.excluded_summary.text()
    dialog.exclude_fasteners.setChecked(False); ready(app, dialog)
    assert len(members(dialog)) == 6
    dialog.select_parts(()); until(app, lambda: not dialog.running and not dialog.timer.isActive())
    assert dialog.checked is None and dialog.checked_batch is None and not dialog.apply_button.isEnabled()
    dialog.select_current_button.click(); ready(app, dialog)
    assert members(dialog) == {'body-b', 'bolt'}
    dialog.reject()
    assert raw == source and document.project().model_dump() == before


def test_split_preview_switch_and_atomic_zip_contain_all_checked_plates(app, dialogs, monkeypatch, tmp_path):
    raw = fixture_design().model_dump(); before = deepcopy(raw)
    dialog = dialogs(raw); small_bed(dialog); ready(app, dialog)
    assert len(dialog.checked_batch['plates']) >= 2 and dialog.apply_button.isEnabled()
    placements = deepcopy(dialog.placements); assignments = dict(dialog.plate_assignments)
    dialog.plate_choice.setCurrentIndex(1)
    assert dialog.result['print_plate_index'] == 1 and set(dialog.viewport.actors) == {p.id for p in dialog.checked.parts}
    assert dialog.placements == placements and dialog.plate_assignments == assignments
    path = tmp_path / 'all-plates.zip'
    monkeypatch.setattr(print_dialog.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), 'ZIP'))
    dialog.accept(); until(app, lambda: not dialog.running)
    assert path.is_file()
    assert dialog.status.text() == 'STL 저장 완료 · ' + str(path)
    assert 'schema_version' not in dialog.status.text()
    with zipfile.ZipFile(path) as archive:
        index = json.loads(archive.read('print-index.json'))
        assert len([name for name in archive.namelist() if name.endswith('.stl')]) == len(dialog.checked_batch['plates'])
        assert index and all(len(archive.read(name)) > 84 for name in archive.namelist() if name.endswith('.stl'))
    assert raw == before


def test_manual_pose_move_between_plates_and_auto_pack_retains_existing_controls(app, dialogs):
    dialog = dialogs(fixture_design(False).model_dump()); small_bed(dialog, 50, 25); ready(app, dialog)
    dialog.active_part.setCurrentIndex(dialog.active_part.findData('body-b'))
    dialog.pose_inputs['x'].setValue(15); dialog.pose_inputs['y'].setValue(0); ready(app, dialog)
    dialog.active_part.setCurrentIndex(dialog.active_part.findData('body-a'))
    dialog.pose_inputs['x'].setValue(-10); dialog.pose_inputs['y'].setValue(0)
    ready(app, dialog)
    assert dialog.placements['body-a']['x'] == pytest.approx(-10)
    dialog.pose_inputs['rz'].setValue(180); ready(app, dialog)
    assert dialog.placements['body-a']['rz'] == 180 and dialog.apply_button.isEnabled()
    pose = dict(dialog.placements['body-a'])
    dialog.target_plate.setCurrentIndex(dialog.target_plate.findData(1)); ready(app, dialog)
    assert len(dialog.checked_batch['plates']) == 2 and dialog.plate_assignments['body-a'] == 1
    assert dialog.placements['body-a'] == pose and dialog.active_part.currentData() == 'body-a'
    dialog.plate_choice.setCurrentIndex(0)
    assert dialog.active_part.currentData() == 'body-b' and dialog.placements['body-a'] == pose
    dialog.auto_pack(); ready(app, dialog)
    assert len(dialog.checked_batch['plates']) == 1 and dialog.placements['body-a']['rz'] == 0


def test_warning_on_nonvisible_oversized_plate_blocks_entire_export(app, dialogs, monkeypatch, tmp_path):
    design = fixture_design(False).model_dump(); design['parts'][1]['geometry']['length'] = 40
    dialog = dialogs(design); small_bed(dialog); ready(app, dialog)
    assert len(dialog.checked_batch['plates']) == 2
    dialog.plate_choice.setCurrentIndex(0)
    assert 'body-a' in {p.id for p in dialog.checked.parts}
    assert dialog.warnings and not dialog.apply_button.isEnabled()
    assert '자르지' in dialog.status.text()
    assert dialog.current_stl_button.isEnabled()
    path = tmp_path / 'must-not-export.zip'
    monkeypatch.setattr(print_dialog.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), 'ZIP'))
    dialog.accept(); assert not path.exists() and not dialog.running
    one = tmp_path / 'clear-current.stl'
    monkeypatch.setattr(print_dialog.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(one), 'STL'))
    dialog.current_stl_button.click(); until(app, lambda: not dialog.running)
    assert one.stat().st_size > 84
    from vtkmodules.vtkIOGeometry import vtkSTLReader
    reader = vtkSTLReader(); reader.SetFileName(str(one)); reader.Update()
    assert reader.GetOutput().GetBounds()[1] - reader.GetOutput().GetBounds()[0] == pytest.approx(20)
    dialog.plate_choice.setCurrentIndex(1)
    assert not dialog.current_stl_button.isEnabled()


def test_pending_preview_discards_old_batch_and_honors_new_plate_selection(app, dialogs, monkeypatch):
    dialog = dialogs(); small_bed(dialog); ready(app, dialog)
    entered = threading.Event(); release = threading.Event(); original = dialog.checked_compute
    first = True
    def blocked(payload, revision):
        nonlocal first
        if first:
            first = False; entered.set(); assert release.wait(10)
        return original(payload, revision)
    monkeypatch.setattr(dialog, 'checked_compute', blocked)
    try:
        dialog.schedule(); dialog.timer.stop(); dialog.calculate(); until(app, entered.is_set)
        assert dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled()
        dialog.plate_choice.setCurrentIndex(1)
        release.set(); ready(app, dialog)
        assert dialog.plate_choice.currentData() == 1 and dialog.result['print_plate_index'] == 1
    finally: release.set()


def test_file_picker_revision_change_cannot_export_stale_preview(app, dialogs, monkeypatch, tmp_path):
    dialog = dialogs(fixture_design(False).model_dump(), ['body-a']); ready(app, dialog)
    path = tmp_path / 'stale.stl'
    def changed(*args, **kwargs):
        dialog.bed[0].setValue(10); return str(path), 'STL'
    monkeypatch.setattr(print_dialog.QFileDialog, 'getSaveFileName', changed)
    dialog.accept()
    assert not dialog.running and dialog.checked_batch is None and not path.exists()
    ready(app, dialog); assert dialog.warnings and not dialog.apply_button.isEnabled()


def test_current_plate_picker_cannot_silently_switch_exported_plate(app, dialogs, monkeypatch, tmp_path):
    dialog = dialogs(fixture_design(False).model_dump()); small_bed(dialog); ready(app, dialog)
    path = tmp_path / 'wrong-plate.stl'
    def changed(*args, **kwargs):
        dialog.plate_choice.setCurrentIndex(1); return str(path), 'STL'
    monkeypatch.setattr(print_dialog.QFileDialog, 'getSaveFileName', changed)
    dialog.current_stl_button.click()
    assert not path.exists() and not dialog.running
    assert dialog.result['print_plate_index'] == 1 and dialog.current_stl_button.isEnabled()


def test_single_stl_and_dialog_cancel_leave_document_untouched(app, dialogs, monkeypatch, tmp_path):
    document = Document(); document.commit(fixture_design(), 'Original'); before = document.project().model_dump()
    dialog = dialogs(document.design, ['body-a']); ready(app, dialog)
    path = tmp_path / 'one.stl'
    monkeypatch.setattr(print_dialog.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), 'STL'))
    dialog.accept(); until(app, lambda: not dialog.running)
    assert path.stat().st_size > 84 and dialog.alive
    dialog.reject(); assert document.project().model_dump() == before


def test_cancel_during_export_preserves_existing_zip(app, dialogs, monkeypatch, tmp_path):
    raw = fixture_design().model_dump(); before = deepcopy(raw)
    dialog = dialogs(raw); small_bed(dialog); ready(app, dialog)
    path = tmp_path / 'existing.zip'; path.write_bytes(b'prior-user-output')
    entered = threading.Event(); release = threading.Event(); original = print_dialog.export_print_stls
    def blocked(*args, **kwargs):
        entered.set(); assert release.wait(10); return original(*args, **kwargs)
    monkeypatch.setattr(print_dialog, 'export_print_stls', blocked)
    monkeypatch.setattr(print_dialog.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), 'ZIP'))
    try:
        dialog.accept(); until(app, entered.is_set); dialog.reject(); release.set()
        until(app, lambda: not dialog.running)
        assert path.read_bytes() == b'prior-user-output' and raw == before and not dialog.alive
        assert not list(tmp_path.glob('*.tmp'))
    finally: release.set()


def overhang_design():
    # Native asymmetric L outline: at explicit print Rx=90 the raised roof
    # needs support; its native flat orientation has a broad bed footprint.
    points = [dict(x=x, y=y) for x, y in [(0, 0), (8, 0), (8, 16), (30, 16), (30, 20), (0, 20)]]
    part = Part(id='overhang', name='Asymmetric overhang',
                geometry=dict(kind='extrusion', points=points, thickness=12),
                transform=dict(x=120, y=50, rz=90))
    return Design(name='Orientation ownership fixture', parts=[part])


def test_explicit_auto_orientation_reduces_real_support_estimate_and_preserves_manual_override(app, dialogs, monkeypatch):
    document = Document(); document.commit(overhang_design(), 'Original overhang')
    before = document.project().model_dump(); raw = deepcopy(document.design)
    dialog = dialogs(raw); ready(app, dialog)
    dialog.pose_inputs['rx'].setValue(90); ready(app, dialog)
    dialog.pose_inputs['x'].setValue(999); ready(app, dialog)
    assert dialog.warnings
    calls = []; original = print_dialog.recommend_print_orientations
    def counted(*args, **kwargs):
        calls.append(1); return original(*args, **kwargs)
    monkeypatch.setattr(print_dialog, 'recommend_print_orientations', counted)
    dialog.auto_orientation_button.click()
    assert dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled()
    ready(app, dialog)
    report = dialog.orientation_reports['overhang']; chosen = report['chosen']
    assert report['baseline']['support_proxy_mm3'] > report['recommended']['support_proxy_mm3'] + 1
    assert report['recommended']['contact_area_mm2'] > 0 and report['recommended']['stable_contact']
    assert report['recommended']['fits_bed'] and not dialog.warnings and len(calls) == 1
    assert dialog.placements['overhang']['x'] != 999
    assert dialog.orientation_state.text() == '추천 자세 적용'
    assert '→' in dialog.orientation_metrics['support'].text()
    assert '통과' in dialog.orientation_metrics['stability'].text()
    dialog.pose_inputs['rz'].setValue(chosen['rz'] + 37); ready(app, dialog)
    manual = deepcopy(dialog.placements['overhang'])
    assert dialog.orientation_state.text() == '수동 자세 · 자동 추천 이후 변경됨'
    assert dialog.orientation_reports['overhang'] == report and len(calls) == 1
    dialog.schedule(); ready(app, dialog)
    assert dialog.placements['overhang'] == manual and len(calls) == 1
    dialog.bed[0].setValue(210); ready(app, dialog)
    assert dialog.orientation_state.text() == '이전 출력 영역 추천 · 다시 비교하세요.'
    assert dialog.placements['overhang'] == manual and len(calls) == 1
    dialog.reject()
    assert raw == document.design and document.project().model_dump() == before


def test_manual_change_during_auto_worker_discards_recommendation(app, dialogs, monkeypatch):
    dialog = dialogs(overhang_design().model_dump()); ready(app, dialog)
    dialog.pose_inputs['rx'].setValue(90); ready(app, dialog)
    entered = threading.Event(); release = threading.Event(); original = print_dialog.recommend_print_orientations
    def blocked(*args, **kwargs):
        entered.set(); assert release.wait(10); return original(*args, **kwargs)
    monkeypatch.setattr(print_dialog, 'recommend_print_orientations', blocked)
    try:
        dialog.auto_orientation_button.click(); dialog.timer.stop(); dialog.calculate(); until(app, entered.is_set)
        revision = dialog.revision
        dialog.pose_inputs['rx'].setValue(180)
        assert dialog.revision > revision and not dialog.auto_requested
        assert not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled()
        release.set(); ready(app, dialog)
        assert dialog.placements['overhang']['rx'] == 180 and not dialog.orientation_reports
    finally: release.set()


def test_cancel_during_auto_worker_preserves_source_and_saved_poses(app, dialogs, monkeypatch):
    raw = overhang_design().model_dump(); before = deepcopy(raw)
    dialog = dialogs(raw); ready(app, dialog)
    dialog.pose_inputs['rx'].setValue(90); ready(app, dialog); poses = deepcopy(dialog.placements)
    entered = threading.Event(); release = threading.Event(); original = print_dialog.recommend_print_orientations
    def blocked(*args, **kwargs):
        entered.set(); assert release.wait(10); return original(*args, **kwargs)
    monkeypatch.setattr(print_dialog, 'recommend_print_orientations', blocked)
    try:
        dialog.auto_orientation_button.click(); dialog.timer.stop(); dialog.calculate(); until(app, entered.is_set)
        dialog.reject(); release.set(); until(app, lambda: not dialog.running)
        assert not dialog.alive and raw == before and dialog.source == before
        assert dialog.placements == poses and not dialog.orientation_reports
    finally: release.set()


def test_failed_auto_request_keeps_manual_poses_without_exporting_old_preview(app, dialogs, monkeypatch):
    dialog = dialogs(overhang_design().model_dump()); ready(app, dialog)
    dialog.pose_inputs['rx'].setValue(90); ready(app, dialog); before = deepcopy(dialog.placements)
    def failed(*args, **kwargs): raise ValueError('자동 자세 계산 시간 한도를 넘었습니다.')
    monkeypatch.setattr(print_dialog, 'recommend_print_orientations', failed)
    dialog.auto_orientation_button.click(); until(app, lambda: not dialog.running and not dialog.timer.isActive())
    assert dialog.placements == before and not dialog.orientation_reports and not dialog.auto_requested
    assert dialog.checked is None and dialog.checked_batch is None
    assert not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled()
    assert '시간 한도' in dialog.status.text()
