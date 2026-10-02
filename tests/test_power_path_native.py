"""Native guided power entry previews before appending to the saved circuit."""

from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.native.electrical_dialog import ElectricalDialog
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog
from cadstudio.native.power_path_dialog import PowerPathDialog


@pytest.fixture(scope='module')
def app():
    qt = QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    yield qt
    qt.processEvents()


def fill(dialog):
    dialog.name.setText('Board supply')
    dialog.source_voltage.setValue(5)
    dialog.source_internal_r.setValue(.2)
    dialog.feed_length.setValue(300)
    dialog.feed_area.setValue(.5)
    dialog.load_kind.setCurrentIndex(dialog.load_kind.findData('mcu'))
    dialog.load_voltage.setValue(5)
    dialog.load_current.setValue(.2)
    dialog.return_length.setValue(400)
    dialog.return_area.setValue(.5)


def test_required_actual_inputs_gate_preview_and_apply(app):
    dialog = PowerPathDialog(None, dict(nodes=['GND'], components=[]), [])
    try:
        assert dialog.source_voltage.value() == 0
        assert dialog.feed_length.value() == 0
        assert dialog.feed_area.value() == 0
        assert dialog.load_current.value() == 0
        assert dialog.return_length.value() == 0
        assert not dialog.apply_button.isEnabled()
        assert '필수 입력' in dialog.preview.toPlainText()
        fill(dialog)
        assert dialog.apply_button.isEnabled()
        assert dialog.schematic_button.isEnabled()
        assert len(dialog.build.workspace.components) == 5
        report = dialog.preview.toPlainText()
        assert '부하 단자 전압' in report and '용량 미검증' in report
        assert '배터리 내부 I²R' in report and '리턴선 I²R' in report
    finally:
        dialog.reject()


def test_off_source_preview_is_zero_and_new_schematic_has_actual_nodes(app, monkeypatch):
    captured = []

    def inspect(self):
        captured.append((self.workspace, self.result, self.branch_layout))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ElectricalSchematicDialog, 'exec', inspect)
    dialog = PowerPathDialog(None, dict(nodes=['GND'], components=[]), [])
    try:
        fill(dialog)
        dialog.source_enabled.setChecked(False)
        assert dialog.apply_button.isEnabled()  # An intentionally OFF draft is valid.
        assert dialog.build.report.state == 'source_off'
        assert dialog.build.report.current_a == 0
        dialog.schematic_button.click()
        assert len(captured) == 1
        workspace, result, layout = captured[0]
        assert len(workspace.components) == 5
        assert result.source_power_w == 0
        assert layout[dialog.build.ids['source']]['active'] is False
        assert layout[dialog.build.ids['feed']]['a'] == workspace.components[2].a
    finally:
        dialog.reject()


def test_main_electrical_dialog_appends_once_and_cancel_does_not_modify_old_circuit(app, monkeypatch):
    original = dict(name='Old circuit', nodes=['GND', 'A', 'SPARE'], components=[
        dict(id='old_wire', name='old lead', kind='wire', a='A', b='GND',
             length_mm=100, cross_section_mm2=.5)])
    design = dict(parts=[dict(id='board_body', name='Board body')], electrical=deepcopy(original))
    dialog = ElectricalDialog(None, design)
    try:
        assert dialog.power_path_button.objectName() == 'electricalPowerPathButton'
        before = deepcopy(dialog.components)
        monkeypatch.setattr(PowerPathDialog, 'exec', lambda self: QDialog.DialogCode.Rejected)
        dialog.power_path_button.click()
        assert dialog.components == before

        def accept_with_values(self):
            fill(self)
            self.load_part.setCurrentIndex(self.load_part.findData('board_body'))
            self.accept()
            return self.result()

        monkeypatch.setattr(PowerPathDialog, 'exec', accept_with_values)
        dialog.power_path_button.click()
        assert len(dialog.components) == len(before) + 5
        assert dialog.components[0] == before[0]
        workspace = dialog.candidate()
        assert 'SPARE' in workspace.nodes  # An unused project net must survive append/save.
        restored = ElectricalWorkspace.model_validate_json(workspace.model_dump_json())
        assert restored.components[-2].part_id == 'board_body'
        assert next(c for c in restored.components if c.kind == 'mcu').part_id == 'board_body'
        assert evaluate_electrical(restored).source_power_w > 0
        report = dialog.report.toPlainText()
        assert '배터리 내부 I²R' in report
        assert report.count('용량 미검증') >= 4
        assert '도체 I²R' in report
    finally:
        dialog.reject()


def test_wire_sku_in_editor_uses_official_dcr_but_keeps_capacity_unverified(app):
    from cadstudio.mechanical_catalog import get_catalog_entry

    entry = get_catalog_entry('belden_9918')
    dialog = PowerPathDialog(None, dict(nodes=['GND'], components=[]), [])
    try:
        fill(dialog)
        dialog.feed_catalog.setCurrentIndex(dialog.feed_catalog.findData(entry.catalog_id))
        dialog.return_catalog.setCurrentIndex(dialog.return_catalog.findData(entry.catalog_id))
        assert dialog.build is not None
        assert not dialog.feed_resistivity.isEnabled()
        assert entry.display_name in dialog.feed_catalog_note.text()
        assert '자동 적용하지 않습니다' in dialog.feed_catalog_note.text()
        assert dialog.build.report.capacities[2].status == 'unverified'
        assert dialog.build.report.capacities[3].status == 'unverified'
        feed = next(c for c in dialog.build.workspace.components if c.id == dialog.build.ids['feed'])
        assert feed.catalog_id == entry.catalog_id
        assert feed.source_url == entry.source_url
        expected = entry.wire_spec.dcr_ohm_per_m * dialog.feed_length.value() / 1000
        result = next(c for c in dialog.build.result.components if c.id == dialog.build.ids['feed'])
        assert result.resistance_ohm == pytest.approx(expected)
    finally:
        dialog.reject()
