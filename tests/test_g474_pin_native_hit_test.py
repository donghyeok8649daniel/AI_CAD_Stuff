"""A connected wire must not hide the clickable centre of a board pad."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.native.mcu_pin_dialog import McuPinDialog
from native_desktop import parse_startup_args


def test_connected_pad_centre_selects_through_unlabelled_wire_overlay():
    app = QApplication.instance() or QApplication([])
    workspace = ElectricalWorkspace(nodes=['GND', 'P', 'N'], components=[
        dict(id='board', name='G474', kind='mcu', a='P', b='GND',
             catalog_id='st_nucleo_g474re', pinout_catalog_id='st_nucleo_g474re',
             signal_pins={'PA11': 'N'}, analysis_enabled=False)])
    original = workspace.model_dump()
    dialog = McuPinDialog(None, workspace)
    try:
        dialog.show(); app.processEvents(); dialog.pin_view.fit(); app.processEvents()
        point = dialog.pin_view.mapFromScene(QPointF(*dialog.pin_view.pin_positions['PA11']))
        stack = dialog.pin_view.items(point)
        assert not stack[0].data(0)  # The connected wire is drawn above the pad.
        assert any(item.data(0) == 'PA11' for item in stack)
        QTest.mouseClick(dialog.pin_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        assert dialog.selected_pin == 'PA11'
        assert dialog.connect_button.isEnabled()
        assert dialog.pin_table.item(dialog.pin_table.currentRow(), 0).data(Qt.ItemDataRole.UserRole) == 'PA11'
        dialog.reject()
        assert workspace.model_dump() == original
    finally:
        dialog.close(); dialog.deleteLater(); app.processEvents()


def test_owned_native_validation_rejects_user_project_and_other_actions():
    assert parse_startup_args(['--g474-pin-smoke', 'owned.json', '--renderer', 'software', '--no-restore']).g474_pin_smoke.name == 'owned.json'
    for extra in (['--open', 'user.pcad'], ['user.pcad'], ['--register-cad-files'], ['--v3-smoke', 'other.json']):
        with pytest.raises(SystemExit):
            parse_startup_args(['--g474-pin-smoke', 'owned.json', *extra])


def test_owned_project_review_requires_a_paired_input_and_rejects_other_startup_actions():
    paired = ['--project-review-smoke', 'report.json', '--review-project', 'copy.pcad']
    args = parse_startup_args([*paired, '--renderer', 'software', '--no-restore'])
    assert args.review_project.name == 'copy.pcad' and args.project_review_smoke.name == 'report.json'
    for command in (paired[:2], paired[2:], [*paired, '--open', 'user.pcad'],
                    [*paired, '--register-cad-files'], [*paired, '--g474-pin-smoke', 'other.json']):
        with pytest.raises(SystemExit):
            parse_startup_args(command)
