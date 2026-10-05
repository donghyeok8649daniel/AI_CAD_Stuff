"""Real board-pin disconnection is a staged, explicit native editing action."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.models import Part
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def workspace():
    return ElectricalWorkspace.model_validate(dict(
        name="Explicit physical power wiring", nodes=["GND", "POWER", "DATA"],
        components=[
            dict(id="battery", name="Virtual supply", kind="battery", a="POWER", b="GND", voltage_v=5),
            dict(id="pi", name="Controller", kind="mcu", catalog_id="rpi4b", part_id="controller",
                 a="POWER", b="GND", analysis_enabled=False,
                 signal_pins={"GPIO17": "DATA"},
                 board_supply_pins={"5V_2": "POWER", "GND_6": "GND"},
                 supply_pinout_catalog_id="rpi4b"),
        ],
        schematic_positions={"battery": {"x": 0, "y": 45}, "pi": {"x": 320, "y": 45}},
    ))


def show(app, dialog):
    dialog.resize(1180, 850)
    dialog.show()
    app.processEvents()
    dialog.fit_scene()
    app.processEvents()


def click_pin(app, dialog, key):
    point = dialog.view.mapFromScene(dialog.component_items["pi"].port_scene_position(key))
    QTest.mouseClick(dialog.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()


def component(dialog):
    return next(item for item in dialog.workspace.components if item.id == "pi")


def test_disconnect_real_supply_changes_only_selected_pin_in_draft_then_saves(app):
    original = workspace()
    before = original.model_dump()
    dialog = ElectricalSchematicDialog(None, original)
    try:
        show(app, dialog)
        assert dialog.view_mode == "physical" and not dialog.wire_button.isChecked()
        click_pin(app, dialog, "supply:5V_2")
        assert dialog.selected_terminal == ("pi", "supply:5V_2")
        assert dialog.disconnect_button.isEnabled()
        assert not dialog.workspace_changed and original.model_dump() == before
        dialog.disconnect_button.click()
        app.processEvents()
        board = component(dialog)
        assert board.board_supply_pins == {"GND_6": "GND"}
        assert board.signal_pins == {"GPIO17": "DATA"}
        assert (board.a, board.b) == ("POWER", "GND")
        assert dialog.workspace.nodes == original.nodes
        assert dialog.workspace.schematic_positions == original.schematic_positions
        assert dialog.component_items["pi"].port_node("supply:5V_2") is None
        for key in ("3V3_1", "3V3_17", "5V_4", "GND_9", "GND_14", "GND_20"):
            assert dialog.component_items["pi"].port_node("supply:" + key) is None
        assert dialog.workspace_changed and dialog.apply_button.isEnabled()
        assert not dialog.disconnect_button.isEnabled() and dialog.selected_terminal is None
        assert dialog.accepted_workspace is None
        assert original.model_dump() == before
        dialog.apply_button.click()
        assert dialog.accepted_workspace is not None
        accepted_board = next(item for item in dialog.accepted_workspace.components if item.id == "pi")
        assert accepted_board.board_supply_pins == {"GND_6": "GND"}
        assert original.model_dump() == before
    finally:
        dialog.reject()


def test_cancel_after_disconnection_preserves_exact_input(app):
    original = workspace()
    before = original.model_dump()
    dialog = ElectricalSchematicDialog(None, original)
    try:
        show(app, dialog)
        click_pin(app, dialog, "supply:5V_2")
        dialog.disconnect_button.click()
        assert "5V_2" not in component(dialog).board_supply_pins
        dialog.close_button.click()
        assert dialog.accepted_workspace is None
        assert original.model_dump() == before
    finally:
        dialog.reject()


def test_read_only_physical_canvas_hides_and_guards_disconnection(app):
    original = workspace()
    before = original.model_dump()
    dialog = ElectricalSchematicDialog(None, original, editable=False)
    try:
        show(app, dialog)
        assert dialog.disconnect_button.isHidden()
        click_pin(app, dialog, "supply:5V_2")
        assert not dialog.disconnect_button.isEnabled()
        dialog.disconnect_selected_pin()  # The method also protects read-only callers.
        assert dialog.workspace.model_dump() == before
        assert not dialog.workspace_changed and dialog.accepted_workspace is None
        assert original.model_dump() == before
    finally:
        dialog.reject()


def test_body_click_clears_selected_pin_disconnection_target(app):
    original = workspace()
    before = original.model_dump()
    dialog = ElectricalSchematicDialog(None, original)
    activated = []
    dialog.partActivated.connect(activated.append)
    try:
        show(app, dialog)
        click_pin(app, dialog, "supply:5V_2")
        assert dialog.disconnect_button.isEnabled()
        board = dialog.component_items["pi"]
        point = dialog.view.mapFromScene(board.mapToScene(QPointF(85, 185)))
        QTest.mouseClick(dialog.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        assert dialog.selected_terminal is None
        assert not dialog.disconnect_button.isEnabled()
        assert activated == ["controller"]
        assert not dialog.workspace_changed and dialog.workspace.model_dump() == before
    finally:
        dialog.reject()


def test_view_mode_changes_preserve_topology_layout_and_cad_geometry(app):
    original = workspace()
    before = original.model_dump()
    part = Part(id="controller", name="Controller CAD body", role="electrical",
                geometry=dict(kind="cylinder"), transform=dict(x=42))
    parts = (part.model_dump(),)
    geometry_before = deepcopy(parts)
    dialog = ElectricalSchematicDialog(None, original, parts=parts)
    try:
        show(app, dialog)
        physical_positions = {key: QPointF(item.pos()) for key, item in dialog.component_items.items()}
        click_pin(app, dialog, "supply:5V_2")
        assert dialog.disconnect_button.isEnabled()
        dialog.mode_picker.setCurrentIndex(dialog.mode_picker.findData("symbols"))
        app.processEvents()
        assert dialog.view_mode == "symbols"
        assert dialog.selected_terminal is None and not dialog.disconnect_button.isEnabled()
        assert dialog.workspace.model_dump() == before and not dialog.workspace_changed
        dialog.mode_picker.setCurrentIndex(dialog.mode_picker.findData("physical"))
        app.processEvents()
        assert dialog.view_mode == "physical"
        assert {key: item.pos() for key, item in dialog.component_items.items()} == physical_positions
        assert dialog.component_items["pi"].port_node("supply:5V_2") == "POWER"
        assert dialog.workspace.model_dump() == before and original.model_dump() == before
        assert dialog.parts == parts == geometry_before
    finally:
        dialog.reject()
