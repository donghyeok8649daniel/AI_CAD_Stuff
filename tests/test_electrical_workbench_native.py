"""Native electrical workspace indexes actual CAD roles and saves one draft."""
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from cadstudio.models import Design, Part
from cadstudio.electrical_registration import register_part
from cadstudio.native.electrical_workbench import ElectricalWorkbenchDialog


@pytest.fixture(scope='module')
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def fixture_design():
    design = Design(name='Original electrical test', parts=[
        Part(id='board', name='Main controller', role='electrical', color='#123456', geometry=dict(kind='cylinder')),
        Part(id='sensor', name='Force sensor', role='electrical', color='#446688', geometry=dict(kind='cylinder')),
        Part(id='motor', name='Drive motor', role='transmission', color='#336633', geometry=dict(kind='cylinder')),
        Part(id='yellow_housing', name='Yellow enclosure', role='structure', color='#FFD400', geometry=dict(kind='cylinder'))],
        part_groups=[dict(id='old', name='Original group', part_ids=['board', 'yellow_housing'])],
        electrical=dict(name='Original net', nodes=['GND', 'PWR', 'KEEP'], components=[
            dict(id='source', name='5 V source', kind='battery', a='PWR', b='GND', voltage_v=5),
            dict(id='legacy', name='Legacy motor', kind='motor', a='PWR', b='GND', part_id='motor', rated_voltage_v=5, rated_current_a=.2)]))
    return register_part(design, 'board', dict(catalog_id='rpi4b'))


def select_body(dialog, part_id):
    row = next(index for index, row in enumerate(dialog._visible_rows) if row.part_id == part_id)
    dialog.table.selectRow(row)


def test_actual_roles_and_legacy_links_are_visible_without_color_guess(app):
    design = fixture_design(); before = design.model_dump(mode='json')
    dialog = ElectricalWorkbenchDialog(None, design)
    try:
        assert dialog.report.counts['electrical_parts'] == 2
        assert dialog.report.counts['registered_electrical_parts'] == 1
        assert dialog.report.counts['unregistered_parts'] == 1
        assert {'board', 'sensor', 'motor'} == {row.part_id for row in dialog._visible_rows if row.part_id}
        assert 'yellow_housing' not in {row.part_id for row in dialog._visible_rows}
        assert dialog.report.hardware_execution_supported is False
        assert dialog.report.dc_calculation_performed is False
        assert not dialog.apply_button.isEnabled()
        dialog.all_cad.setChecked(True)
        assert 'yellow_housing' in {row.part_id for row in dialog._visible_rows}
        assert design.model_dump(mode='json') == before
    finally: dialog.reject()


def test_missing_actual_cad_registration_precedes_many_wires_without_hiding_them(app):
    from cadstudio.electrical import ElectricalWorkspace
    original = fixture_design()
    raw = original.electrical.model_dump()
    raw['components'] += [dict(id=f'wire_{index}', name=f'Wire {index}', kind='wire', a='PWR', b='GND',
        length_mm=100, cross_section_mm2=.5) for index in range(50)]
    original.electrical = ElectricalWorkspace.model_validate(raw)
    dialog = ElectricalWorkbenchDialog(None, original)
    try:
        assert dialog._visible_rows[0].part_id == 'sensor'
        assert dialog._visible_rows[0].registration == 'unregistered'
        assert len([row for row in dialog._visible_rows if row.kind == 'wire']) == 50
        first_wire = next(index for index, row in enumerate(dialog._visible_rows) if row.kind == 'wire')
        assert first_wire > next(index for index, row in enumerate(dialog._visible_rows) if row.part_id == 'board')
        assert first_wire > next(index for index, row in enumerate(dialog._visible_rows) if row.component_id == 'source')
        dialog.all_cad.setChecked(True)
        assert dialog._visible_rows[-1].part_id == 'yellow_housing'
    finally: dialog.reject()


def test_search_kind_and_registration_filters_keep_explicit_identity(app):
    dialog = ElectricalWorkbenchDialog(None, fixture_design())
    try:
        dialog.state_filter.setCurrentIndex(dialog.state_filter.findData('unregistered'))
        assert [row.part_id for row in dialog._visible_rows] == ['sensor']
        dialog.state_filter.setCurrentIndex(0)
        dialog.query.setText('rpi4b')
        assert [row.part_id for row in dialog._visible_rows] == ['board']
        dialog.query.clear()
        dialog.kind_filter.setCurrentIndex(dialog.kind_filter.findData('motor'))
        assert [row.component_id for row in dialog._visible_rows] == ['legacy']
        dialog.query.setText('impossible-model')
        assert not dialog._visible_rows and not dialog.register_button.isEnabled()
        assert not dialog.focus_button.isEnabled()
    finally: dialog.reject()


def test_cad_focus_emits_only_selected_actual_body(app):
    dialog = ElectricalWorkbenchDialog(None, fixture_design(), 'board')
    spy = QSignalSpy(dialog.partActivated)
    try:
        assert dialog.selected_row().part_id == 'board'
        dialog.focus_button.click()
        assert spy.count() == 1 and spy.at(0) == ['board']
        dialog.table.selectRow(next(index for index, row in enumerate(dialog._visible_rows) if row.component_id == 'source'))
        assert not dialog.focus_button.isEnabled()
        dialog.focus_selected()
        assert spy.count() == 1
    finally: dialog.reject()


def test_physical_pins_ratings_and_unknowns_are_separate(app):
    dialog = ElectricalWorkbenchDialog(None, fixture_design(), 'board')
    try:
        assert len(dialog.diagram.pin_items) == 40
        assert dialog._components[dialog.selected_row().component_id].rated_current_a == 0
        report = dialog._component_reports[dialog.selected_row().component_id]
        assert f'0 / {report.available_terminals}' in dialog.details.toPlainText()
        assert '계산 제외' in dialog.details.toPlainText()
        assert dialog.source_button.isEnabled()
        assert dialog.issues.count() > 0
    finally: dialog.reject()


def test_registration_draft_cancel_and_single_history_commit(app, tmp_path):
    from cadstudio.native.document import Document, read_project
    original = fixture_design(); before = original.model_dump(mode='json')
    dialog = ElectricalWorkbenchDialog(None, original, 'sensor')
    try:
        updated = register_part(dialog.draft, 'sensor', dict(catalog_id='ams_as5600_asot'))
        dialog.adopt_design(updated)
        assert dialog.apply_button.isEnabled() and dialog.checked is None
        assert original.model_dump(mode='json') == before
        assert dialog.draft.parts == original.parts
        assert dialog.draft.part_groups == original.part_groups
        dialog.reject(); assert dialog.checked is None
    finally: dialog.reject()
    saved = ElectricalWorkbenchDialog(None, original, 'sensor')
    try:
        saved.adopt_design(updated); saved.accept()
        assert saved.checked is not None
        assert 'KEEP' in saved.checked.electrical.nodes
        document = Document(); document.commit(before, 'Original')
        cursor = document.journal.data['cursor']
        document.commit(saved.checked.model_dump(mode='json'), 'Electrical workspace')
        path = tmp_path / 'electrical-workspace.cad.json'; document.write(path)
        project = read_project(path)
        assert project.design == saved.checked
        assert len(project.history.entries) == 2
        assert document.journal.at(cursor) == before
        assert [part.color for part in project.design.parts] == [part.color for part in original.parts]
    finally: saved.reject()


def test_catalog_counts_filter_and_reference_only_cannot_register(app):
    from cadstudio.electrical_catalog import catalog_counts, catalog_support
    dialog = ElectricalWorkbenchDialog(None, fixture_design(), 'sensor')
    try:
        counts = catalog_counts()
        assert len(dialog._catalog_rows) == counts['total']
        reference_index = next(index for index, entry in enumerate(dialog._catalog_rows) if catalog_support(entry.catalog_id) == 'reference')
        dialog.catalog_table.selectRow(reference_index)
        assert dialog.catalog_source_button.isEnabled()
        assert not dialog.catalog_use_button.isEnabled()
        dialog.catalog_registerable.setChecked(True)
        assert len(dialog._catalog_rows) == counts['registerable']
        assert all(catalog_support(entry.catalog_id) != 'reference' for entry in dialog._catalog_rows)
        dialog.catalog_query.setText('rpi4b')
        assert len(dialog._catalog_rows) == 1 and dialog.catalog_use_button.isEnabled()
        dialog.catalog_category.setCurrentIndex(dialog.catalog_category.findData(dialog._catalog_rows[0].category))
        assert len(dialog._catalog_rows) == 1
    finally: dialog.reject()


@pytest.mark.parametrize('manufacturer,model,catalog_id', [
    ('MEAN WELL', 'HDR-60-5', 'meanwell_hdr60_5'),
    ('TI', 'REF5025AID SOIC8', 'ti_ref5025aid'),
])
def test_product_metadata_reference_is_explicit_and_preserves_custom_registration(app, manufacturer, model, catalog_id):
    from cadstudio.part_product import ProductMetadata
    original = fixture_design()
    original.parts[1].product = ProductMetadata(manufacturer=manufacturer, model=model)
    original = register_part(original, 'sensor', dict(kind='load', terminal_pins={'CUSTOM_OUT': 'KEEP'}))
    before = original.model_dump(mode='json')
    dialog = ElectricalWorkbenchDialog(None, original, 'sensor')
    try:
        assert dialog.metadata_button.isEnabled()
        assert '후보' in dialog.details.toPlainText()
        dialog.metadata_button.click()
        assert dialog.tabs.currentIndex() == 1
        assert [entry.catalog_id for entry in dialog._catalog_rows] == [catalog_id]
        assert not dialog.apply_button.isEnabled()
        assert dialog.draft.model_dump(mode='json') == before
        component = dialog._components[dialog.selected_row().component_id]
        assert not component.catalog_id and component.terminal_pins == {'CUSTOM_OUT': 'KEEP'}
        assert original.model_dump(mode='json') == before
    finally: dialog.reject()


@pytest.mark.parametrize('language', ['ko', 'en'])
def test_600px_layout_retains_outer_save_cancel_and_workflow_actions(app, language):
    old_language = getattr(app, 'cad_language', None)
    app.cad_language = SimpleNamespace(language=language)
    dialog = ElectricalWorkbenchDialog(None, fixture_design(), 'sensor')
    try:
        dialog.resize(1040, 600); dialog.show(); app.processEvents(); QTest.qWait(20)
        assert dialog.height() == 600
        for widget in (dialog.apply_button, dialog.cancel_button, dialog.register_button,
                       dialog.focus_button, dialog.schematic_button, dialog.power_button):
            assert widget.isVisible()
            assert dialog.rect().contains(widget.mapTo(dialog, widget.rect().bottomRight()))
        if language == 'en':
            assert 'Electrical workspace' in dialog.windowTitle()
            assert dialog.apply_button.text() == 'Save electrical changes'
            assert 'Unregistered' in dialog.counts_label.text()
    finally:
        dialog.reject(); app.cad_language = old_language
