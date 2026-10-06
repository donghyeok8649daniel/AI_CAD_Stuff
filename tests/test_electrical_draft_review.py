"""AI wiring review compares the actual saved circuit, never geometry alone."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from cadstudio.models import Design, Part
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.electrical_diff import electrical_changes, electrical_snapshot
from cadstudio.electrical_registration import register_part
from cadstudio.circuit_connections import add_schematic_wire


def wired_design():
    design = Design(parts=[Part(id='pi', name='Controller CAD', geometry=dict(kind='plate',length=85,width=56,thickness=2,hole_count=0)),
                           Part(id='encoder', name='Encoder CAD', geometry=dict(kind='cylinder',diameter=15,height=2), transform=dict(x=100))])
    design = register_part(design, 'pi', dict(catalog_id='rpi4b'))
    design = register_part(design, 'encoder', dict(catalog_id='ams_as5600_asot'))
    a, b = [component.id for component in design.electrical.components]
    workspace = add_schematic_wire(design.electrical, a, 'pin:GPIO17', b, 'port:OUT',
                                   name='Encoder output',length_mm=250,cross_section_mm2=.25,wire_color='#FF0000')
    design.electrical = workspace
    return design


def test_wire_change_has_before_after_endpoints_length_color_and_preserves_inputs():
    before = wired_design(); saved = deepcopy(before.model_dump())
    after = before.model_copy(deep=True)
    wire = after.electrical.components[-1]
    wire.length_mm = 300; wire.wire_color = '#00FF00'
    changes = electrical_changes(before, after)
    fields = {change.field for change in changes}
    assert {'length_mm','wire_color'} <= fields
    assert next(c for c in changes if c.field=='length_mm').before==250
    assert next(c for c in changes if c.field=='length_mm').after==300
    assert before.model_dump()==saved
    workspace, names = electrical_snapshot(before)
    workspace.components[-1].name = 'Private preview only'
    assert before.model_dump()==saved and names['pi']=='Controller CAD'


def test_link_rename_and_wire_delete_are_individually_visible():
    before = wired_design(); after = before.model_copy(deep=True)
    after.parts[0].name='Control board'
    wire_id=after.electrical.components[-1].id
    after.electrical.components.pop()
    changes=electrical_changes(before,after)
    assert any(c.field=='cad_name' and c.after=='Control board' for c in changes)
    assert any(c.component_id==wire_id and c.field=='component' and c.after is None for c in changes)
    after.electrical.components[0].part_id='encoder'
    assert any(c.field=='part_id' and c.before=='pi' and c.after=='encoder'
               for c in electrical_changes(before,after))


def test_node_order_and_omitted_legacy_defaults_are_not_fake_edits():
    before=wired_design(); after=before.model_copy(deep=True)
    after.electrical.nodes.reverse()
    assert electrical_changes(before,after)==()
    # Serializer field presence differs, but the compared model values agree.
    legacy={'name':'Legacy','nodes':['GND','V'],'components':[dict(id='r',name='R',kind='resistor',a='V',b='GND',resistance_ohm=100)]}
    explicit=deepcopy(legacy); explicit['components'][0].update(part_registration=False,wire_endpoints=[],wire_color=None)
    assert ElectricalWorkspace.model_validate(legacy).model_dump()!=ElectricalWorkspace.model_validate(explicit).model_dump()
    assert electrical_changes({'electrical':legacy},{'electrical':explicit})==()


def test_registration_addition_and_new_workspace_are_visible_without_meshing():
    before=Design();after=wired_design()
    changes=electrical_changes(before,after)
    assert sum(c.field=='component' for c in changes)==3
    wire=next(c for c in changes if c.field=='component' and c.after['kind']=='wire')
    assert len(wire.after['wire_endpoints'])==2
    assert any(c.field=='nodes' for c in changes)
    assert electrical_changes(None, Design())==()


def test_saved_schematic_position_change_is_in_review():
    before=wired_design();after=before.model_copy(deep=True)
    from cadstudio.electrical import ElectricalSchematicPosition
    after.electrical.schematic_positions[after.electrical.components[0].id]=ElectricalSchematicPosition(x=12,y=45)
    assert any(c.field=='schematic_positions' for c in electrical_changes(before,after))


@pytest.fixture
def review_ui(monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QWidget
    from cadstudio.native import draft_preview
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    class GeometryView(QWidget):
        def __init__(self):super().__init__();self.result=None;self.loads=[];self.closed=False
        def load(self,result,fit=False):self.result=result;self.loads.append(result)
        def select_many(self,ids):pass
        def shutdown(self):self.closed=True
    monkeypatch.setattr(draft_preview,'CADViewport',GeometryView)
    monkeypatch.setattr(app,'cad_language',SimpleNamespace(language='ko'),raising=False)
    yield app,draft_preview
    app.processEvents()
    # pytest has no outer Qt event loop. Honor deferred GUI destruction before
    # releasing Python wrappers to the next test's geometry/GC work.
    app.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_real_circuit_before_after_preview_is_readonly_and_geometry_stays_lazy(review_ui):
    app,module=review_ui
    before=wired_design();after=before.model_copy(deep=True);after.electrical.components[-1].length_mm=300
    saved_before=before.model_dump();saved_after=after.model_dump()
    dialog=module.DraftPreviewDialog(None,{'before':'mesh'},{'after':'mesh'},'Offline wiring review',
        before_design=before,after_design=after)
    try:
        dialog.show();app.processEvents()
        panel=dialog.electrical_panel
        assert dialog.tabs.currentIndex()==1 and dialog.viewport.loads==[]
        assert panel.view.viewport().height()>=180
        assert panel.workspace.model_dump()==after.electrical.model_dump()
        assert dialog.change_table.rowCount()>=1
        for widget in (panel.edit_button,panel.link_button,panel.ai_button,panel.add_wire_button,panel.delete_wire_button):
            assert widget.isHidden()
        for action in (panel.edit_cad_link,panel.prepare_ai_request,panel.add_wire,panel.delete_selected_wire,panel.edit_selected,panel.open_simulation):
            action()
        assert panel.workspace.model_dump()==after.electrical.model_dump()
        dialog.mode.setCurrentIndex(dialog.mode.findData('before'));app.processEvents()
        assert panel.workspace.model_dump()==before.electrical.model_dump()
        dialog.tabs.setCurrentIndex(0);app.processEvents()
        assert dialog.viewport.loads==[{'before':'mesh'}]
        dialog.reject();assert dialog.viewport.closed
        assert before.model_dump()==saved_before and after.model_dump()==saved_after
    finally:dialog.deleteLater();app.processEvents()


def test_new_document_electrical_preview_has_empty_before_and_english_labels(review_ui,monkeypatch):
    app,module=review_ui
    monkeypatch.setattr(app,'cad_language',SimpleNamespace(language='en'))
    dialog=module.DraftPreviewDialog(None,None,{},'New wiring',before_design=None,after_design=wired_design())
    try:
        assert dialog.tabs.tabText(1)=='Wiring / CAD links'
        assert dialog.change_table.horizontalHeaderItem(2).text()=='Before'
        dialog.mode.setCurrentIndex(dialog.mode.findData('before'))
        assert dialog.electrical_panel.workspace.components==[]
        assert dialog.viewport.loads==[]
        dialog.accept();assert dialog.result()==dialog.DialogCode.Accepted and dialog.viewport.closed
    finally:dialog.deleteLater();app.processEvents()


def test_blocked_wiring_draft_can_be_inspected_but_never_accepted(review_ui):
    app,module=review_ui
    before=wired_design();after=before.model_copy(deep=True);after.electrical.components[-1].closed=False
    dialog=module.DraftPreviewDialog(None,{}, {},'Needs repair',validation={'status':'needs_repair'},
        before_design=before,after_design=after)
    try:
        assert dialog.electrical_panel is not None and not dialog.apply_button.isEnabled()
        dialog.accept();assert dialog.result()!=dialog.DialogCode.Accepted and not dialog.viewport.closed
        dialog.reject();assert dialog.viewport.closed
    finally:dialog.deleteLater();app.processEvents()
