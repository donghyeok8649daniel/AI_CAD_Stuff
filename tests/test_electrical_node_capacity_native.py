"""Source Qt editors retain late nets and transaction boundaries at capacity."""
import pytest
from PySide6.QtWidgets import QApplication

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.native.electrical_dialog import ElectricalDialog
from cadstudio.native.mcu_pin_dialog import McuPinDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def populated_workspace():
    return ElectricalWorkspace.model_validate(dict(
        nodes=["GND", "PWR", *(f"NET_{i:03}" for i in range(1, 511))],
        components=[
            dict(id="pi", name="Documented Pi 4", kind="mcu", catalog_id="rpi4b",
                 pinout_catalog_id="rpi4b", supply_pinout_catalog_id="rpi4b", a="PWR", b="GND", analysis_enabled=False,
                 signal_pins={"GPIO17": "NET_130"}, board_supply_pins={"5V_2": "PWR", "GND_6": "GND"}),
            dict(id="terminals", name="Manual terminal bank", kind="load", a="PWR", b="GND",
                 analysis_enabled=False, terminal_pins={f"P{i:03}": f"NET_{min(i,129):03}" for i in range(1, 131)}),
            dict(id="signal_wire", name="Stored physical signal lead", kind="wire",
                 a="NET_130", b="NET_129", analysis_enabled=False,
                 wire_endpoints=[dict(component_id="pi", terminal="pin:GPIO17"),
                                 dict(component_id="terminals", terminal="port:P130")]),
        ]))


def test_pin_editor_lists_net512_reassigns_existing_and_rejects513_atomically(app):
    workspace = populated_workspace()
    original = workspace.model_dump()
    dialog = McuPinDialog(None, workspace, mcu_id="pi")
    try:
        assert dialog.node_combo.count() == 512
        assert dialog.node_combo.findText("NET_510") == 511
        dialog.select_pin("GPIO18")
        dialog.node_combo.setCurrentText("NET_510")
        dialog.node_button.click()
        app.processEvents()
        board = dialog.current_mcu()
        assert board.signal_pins == {"GPIO17": "NET_130", "GPIO18": "NET_510"}
        assert len(dialog.workspace.nodes) == 512
        accepted_before_failure = dialog.workspace.model_dump()
        dialog.node_combo.setCurrentText("NEW_NODE_513")
        dialog.node_button.click()
        app.processEvents()
        assert "512" in dialog.status.text()
        assert dialog.workspace.model_dump() == accepted_before_failure
        dialog.select_pin("5V_2")
        assert not dialog.node_button.isEnabled()
        assert dialog.current_mcu().board_supply_pins == {"5V_2": "PWR", "GND_6": "GND"}
        dialog.reject()
        assert workspace.model_dump() == original
    finally:
        dialog.reject()


def test_main_electrical_editor_preserves_full_node_list_owned_endpoints_and_pin_provenance(app):
    workspace = populated_workspace()
    before = workspace.model_dump()
    dialog = ElectricalDialog(None, dict(parts=[], electrical=before))
    try:
        candidate = dialog.candidate()
        assert len(candidate.nodes) == 512 and set(candidate.nodes) == set(workspace.nodes)
        assert candidate.components == workspace.components
        assert workspace.model_dump() == before
    finally:
        dialog.reject()
