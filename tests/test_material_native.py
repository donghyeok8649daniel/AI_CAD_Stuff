"""Real Qt material preview: explicit targets, cache attestation and cancellation."""
import time
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt, QThreadPool, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QPushButton

from cadstudio.models import Design, Material, Part
from cadstudio.kernel import KERNEL_LOCK, preview
from cadstudio.material_assignments import assign_material, custom_material
from cadstudio.material_catalog import material_from_catalog
from cadstudio.native.material_dialog import MaterialDialog
from cadstudio.native.workflows import PreviewDialog


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    _APP.setQuitOnLastWindowClosed(False)
    yield _APP
    assert QThreadPool.globalInstance().waitForDone(10000)
    _APP.processEvents()


@pytest.fixture
def prepared():
    design = Design(parts=[Part(id='frame', name='Frame', geometry=dict(kind='plate', hole_count=0)),
        Part(id='window', name='Window', geometry=dict(kind='cylinder'), transform=dict(x=150))])
    with KERNEL_LOCK:
        result = preview(design)
    parent = QWidget()
    parent.result = result
    yield design.model_dump(), parent
    parent.close()
    parent.deleteLater()


def wait(app, condition):
    deadline = time.monotonic()+20
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert condition()


def dispose(app, dialog):
    dialog.reject()
    assert QThreadPool.globalInstance().waitForDone(10000)
    dialog.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_search_is_read_only_and_material_preview_reuses_verified_mesh(app, prepared, monkeypatch):
    raw, parent = prepared
    before = deepcopy(raw)
    def forbidden(*_):
        raise AssertionError('Material metadata changes must not rebuild the shape')
    monkeypatch.setattr(PreviewDialog, 'compute', forbidden)
    dialog = MaterialDialog(parent, raw, part_ids=['frame', 'window'])
    dialog.resize(920, 650)
    dialog.show()
    try:
        wait(app, lambda:dialog.checked is not None)
        assert dialog.selected_part_ids() == ('frame', 'window')
        assert not dialog.apply_button.isEnabled()
        assert not dialog.inputs['density'].text()
        revision = dialog.revision
        dialog.query.setText('6061')
        app.processEvents()
        assert dialog.revision == revision and dialog.checked.model_dump() == before
        assert dialog.entry.catalog_id == 'al_6061_t6_extruded'
        dialog.use_catalog()
        wait(app, lambda:dialog.checked is not None and dialog.apply_button.isEnabled())
        assert all(p.material.catalog_id == 'al_6061_t6_extruded' for p in dialog.checked.parts)
        assert dialog.result['meshes'][0]['vertices'] is parent.result['meshes'][0]['vertices']
        assert not dialog.interference['blocked'] and dialog.travel is None
        assert len(dialog.viewport.actors) == 2
        assert dialog.apply_button.visibleRegion().contains(dialog.apply_button.rect())
    finally:
        dispose(app, dialog)
    assert raw == before


def test_existing_custom_unknowns_require_replacement_and_apply_is_scoped(app, prepared):
    raw, parent = prepared
    old = Material(name='Measured steel', density=8000, youngs_modulus=190000, poisson=.28).model_dump()
    raw['parts'][0]['material'] = deepcopy(old)
    before = deepcopy(raw)
    dialog = MaterialDialog(parent, raw, 'frame')
    dialog.show()
    try:
        wait(app, lambda:dialog.checked is not None)
        assert dialog.name.text() == 'Measured steel' and dialog.inputs['poisson'].text() == '0.28'
        dialog.query.setText('Si')
        assert dialog.entry.catalog_id == 'silicon_single_crystal'
        dialog.use_catalog()
        wait(app, lambda:not dialog.running and not dialog.timer.isActive())
        assert dialog.checked is None and not dialog.apply_button.isEnabled()
        assert '기존 재질' in dialog.status.text()
        dialog.replace_existing.setChecked(True)
        wait(app, lambda:dialog.checked is not None and dialog.apply_button.isEnabled())
        si = dialog.checked.parts[0].material
        assert si.behavior == 'anisotropic' and si.youngs_modulus is None and si.poisson is None
        assert 'material' not in dialog.checked.model_dump()['parts'][1]
        checked_raw = dialog.checked.model_dump()
        dialog.accept()
        assert not dialog.alive and dialog.checked.model_dump() == checked_raw
    finally:
        dispose(app, dialog)
    assert raw == before


def test_invalid_search_targets_and_empty_density_never_enable_apply(app, prepared):
    raw, parent = prepared
    dialog = MaterialDialog(parent, raw, 'frame')
    dialog.show()
    try:
        wait(app, lambda:dialog.checked is not None)
        dialog.use_catalog()
        wait(app, lambda:dialog.apply_button.isEnabled())
        dialog.query.setText('nonexistent material')
        wait(app, lambda:not dialog.running and not dialog.timer.isActive())
        assert dialog.entry is None and dialog.checked is None
        assert not dialog.source_button.isEnabled() and not dialog.catalog_button.isEnabled()
        assert not dialog.apply_button.isEnabled()
        dialog.mode.setCurrentIndex(dialog.mode.findData('custom'))
        wait(app, lambda:not dialog.running and not dialog.timer.isActive())
        assert '밀도' in dialog.status.text() and dialog.checked is None
        dialog.inputs['density'].setText('1250')
        wait(app, lambda:dialog.checked is not None)
        assert dialog.checked.parts[0].material.youngs_modulus is None
        assert dialog.checked.parts[0].material.poisson is None
        dialog.targets.item(0).setCheckState(Qt.CheckState.Unchecked)
        wait(app, lambda:not dialog.running and not dialog.timer.isActive())
        assert dialog.checked is None and '체크' in dialog.status.text()
    finally:
        dispose(app, dialog)


def test_unattested_cache_rebuilds_baseline_once_and_close_cancels(app, prepared, monkeypatch):
    raw, parent = prepared
    parent.result = dict(parent.result, _geometry_key='wrong')
    calls = []
    original = PreviewDialog.compute
    def compute(data):
        calls.append(deepcopy(data))
        return original(data)
    monkeypatch.setattr(PreviewDialog, 'compute', staticmethod(compute))
    dialog = MaterialDialog(parent, raw, 'frame')
    dialog.show()
    try:
        wait(app, lambda:dialog.checked is not None)
        assert len(calls) == 1 and calls[0] == raw
        dialog.use_catalog()
        wait(app, lambda:dialog.apply_button.isEnabled())
        assert len(calls) == 1
        dialog.query.setText('304')
        dialog.reject()
        assert not dialog.alive and not dialog.timer.isActive()
        assert QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()
        assert raw['parts'][0].get('material') is None
    finally:
        dispose(app, dialog)


def study_design(material):
    return Design(parts=[Part(id='specimen', name='Sample', geometry=dict(kind='round_specimen'),
                             material=material)], studies=[dict(id='tensile-saved', kind='tensile',
        name='Saved experiment', settings=dict(part_id='specimen', force_n=37,
            young_gpa=200, poisson=.3, yield_mpa=250, refinement=2))]).model_dump()


def click_import(dialog):
    controls = [item for item in dialog.findChildren(QPushButton)
                if item.text() == '선택 시편의 재질값 가져오기']
    assert len(controls) == 1
    controls[0].click()


def test_tensile_material_import_is_explicit_and_preserves_load_saved_study(app, monkeypatch):
    from cadstudio.native import studies
    monkeypatch.setattr(studies, 'analyze', lambda *_:pytest.fail('Import must not run the solver'))
    material = Material(name='Measured metal', density=7800, youngs_modulus=190000,
                        poisson=.28, yield_strength=280, behavior='isotropic')
    raw = study_design(material)
    before = deepcopy(raw)
    dialog = studies.TensileStudy(None, raw, identifier='tensile-saved')
    dialog.show()
    try:
        app.processEvents()
        assert dialog.settings().young_gpa == 200 and dialog.settings().poisson == .3
        click_import(dialog)
        imported = dialog.settings()
        assert (imported.young_gpa, imported.poisson, imported.yield_mpa) == (190, .28, 280)
        assert imported.force_n == 37 and imported.refinement == 2
        assert dialog.base.model_dump() == before and raw == before
        assert dialog.checked is None and not dialog.save_button.isEnabled()
    finally:
        dispose(app, dialog)


@pytest.mark.parametrize('catalog_id, message', [
    ('al_6061_t6_extruded', 'poisson'),
    ('silicon_single_crystal', '이방성 또는 비선형'),
    ('silicone_lr3003_50', '이방성 또는 비선형')])
def test_tensile_unknown_or_nonlinear_import_refuses_without_mutation(app, monkeypatch, catalog_id, message):
    from cadstudio.native import studies
    monkeypatch.setattr(studies, 'analyze', lambda *_:pytest.fail('Refusal must not run the solver'))
    material = material_from_catalog(catalog_id)
    if material.behavior != 'isotropic':
        # Even complete scalars must not erase the selected constitutive model.
        material = custom_material(material, dict(youngs_modulus=130000, poisson=.28, yield_strength=280))
    raw = study_design(material)
    before = deepcopy(raw)
    dialog = studies.TensileStudy(None, raw, identifier='tensile-saved')
    dialog.show()
    try:
        app.processEvents()
        settings = dialog.settings().model_dump()
        click_import(dialog)
        assert message in dialog.status.text()
        assert dialog.settings().model_dump() == settings
        assert dialog.base.model_dump() == before and raw == before
        assert dialog.checked is None and not dialog.save_button.isEnabled()
    finally:
        dispose(app, dialog)


@pytest.mark.parametrize('yield_strength, accepted', [(0.005, True), (1e-9, False)])
def test_tensile_small_values_import_without_clamping_or_partial_changes(app, monkeypatch, yield_strength, accepted):
    from cadstudio.native import studies
    monkeypatch.setattr(studies, 'analyze', lambda *_:pytest.fail('Import must not run the solver'))
    material = Material(name='Specified compliant solid', density=1200, youngs_modulus=5,
                        poisson=.29, yield_strength=yield_strength, behavior='isotropic')
    raw = study_design(material)
    before = deepcopy(raw)
    dialog = studies.TensileStudy(None, raw, identifier='tensile-saved')
    dialog.show()
    try:
        settings = dialog.settings().model_dump()
        click_import(dialog)
        imported = dialog.settings()
        if accepted:
            assert imported.young_gpa == .005 and imported.yield_mpa == .005
            assert imported.poisson == .29
            assert imported.force_n == 37 and imported.refinement == 2
        else:
            assert dialog.settings().model_dump() == settings
            assert '범위' in dialog.status.text()
        assert dialog.base.model_dump() == before and raw == before
        assert dialog.checked is None and not dialog.save_button.isEnabled()
    finally:
        dispose(app, dialog)
