"""Mixed component editing preserves SI units, pin wiring and project history."""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from cadstudio.electrical import ElectricalComponent, ElectricalWorkspace
from cadstudio.models import Design, Part
from cadstudio.native.document import Document, read_project
from cadstudio.native.electrical_dialog import ComponentDialog, CatalogDialog
from cadstudio.native.electrical_part_dialog import ElectricalPartDialog
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog
from cadstudio.electrical_catalog import get_catalog_entry


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


@pytest.mark.parametrize('kind,field,entered,stored',[
    ('capacitor','capacitance_f',.1,1e-7),
    ('capacitor','capacitance_f',470,470e-6),
    ('capacitor','capacitance_f',2000000,2),
    ('inductor','inductance_h',.01,10e-6),
])
def test_passive_forms_display_convenient_units_and_reopen_exact_si(app,kind,field,entered,stored):
    dialog=ComponentDialog(None,[])
    try:
        dialog.kind.setCurrentIndex(dialog.kind.findData(kind))
        dialog.inputs[field].setValue(entered)
        if kind=='capacitor':dialog.capacitor_polarized.setChecked(True)
        candidate=ElectricalComponent.model_validate(dialog.candidate())
        assert getattr(candidate,field)==pytest.approx(stored)
        assert ('µF' if kind=='capacitor' else 'mH') in dialog.inputs[field].suffix()
        reopened=ComponentDialog(None,[],candidate.model_dump())
        try:
            assert reopened.inputs[field].value()==pytest.approx(entered)
            assert ElectricalComponent.model_validate(reopened.candidate())==candidate
        finally:reopened.reject()
    finally:dialog.reject()


def test_exact_actuator_catalog_does_not_inherit_virtual_current(app,monkeypatch):
    def choose(catalog):
        catalog.entry=get_catalog_entry('robotis_xl330_m288t')
        assert catalog.entry is not None
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CatalogDialog,'exec',choose)
    dialog=ComponentDialog(None,[])
    try:
        dialog.kind.setCurrentIndex(dialog.kind.findData('actuator'))
        assert dialog.inputs['rated_current_a'].value()==1
        dialog.select_catalog()
        candidate=ElectricalComponent.model_validate(dialog.candidate())
        assert candidate.kind=='actuator' and not candidate.analysis_enabled
        assert candidate.rated_current_a==0 and candidate.startup_current_a is None
    finally:dialog.reject()


@pytest.mark.parametrize('allow',[False,True])
def test_product_model_change_requires_port_consent_and_clears_old_provenance(app,monkeypatch,allow):
    def choose(catalog):
        catalog.entry=get_catalog_entry('robotis_xl330_m288t')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CatalogDialog,'exec',choose)
    questions=[]
    def consent(*args):
        questions.append(args)
        return QMessageBox.StandardButton.Yes if allow else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox,'question',consent)
    existing=dict(id='wired',name='Wired motor',kind='motor',a='PWR',b='GND',catalog_id='pololu_4755',
                  analysis_enabled=False,product_pinout_catalog_id='pololu_4755',terminal_pins={'ENCODER_A':'SIG'})
    dialog=ComponentDialog(None,[],existing)
    try:
        dialog.select_catalog();candidate=ElectricalComponent.model_validate(dialog.candidate())
        assert len(questions)==1
        if allow:
            assert candidate.kind=='actuator' and not candidate.terminal_pins
            assert candidate.product_pinout_catalog_id=='' and not candidate.analysis_enabled
        else:
            assert candidate.kind=='motor' and candidate.catalog_id=='pololu_4755'
            assert candidate.terminal_pins=={'ENCODER_A':'SIG'}
            assert candidate.product_pinout_catalog_id=='pololu_4755'
    finally:dialog.reject()


def test_registration_keeps_verified_specs_even_without_pin_diagram(app):
    design=Design(parts=[Part(id='body',name='Capacitor body',geometry=dict(kind='cylinder'))])
    dialog=ElectricalPartDialog(None,design,'body')
    try:
        index=next(i for i in range(dialog.model_combo.count())
                   if 'EEUFR1H101B' in dialog.model_combo.itemText(i))
        dialog.model_combo.setCurrentIndex(index)
        entry=get_catalog_entry(dialog.model_combo.currentData())
        assert entry.spec_summary in dialog.note.toPlainText()
        assert dialog.source_button.isEnabled()
    finally:dialog.reject()


def mixed():
    return ElectricalWorkspace.model_validate(dict(nodes=['GND','PWR','CAP','COIL'],components=[
        dict(id='source',name='Battery',kind='battery',a='PWR',b='GND',voltage_v=5),
        dict(id='c',name='Filter capacitor',kind='capacitor',a='CAP',b='GND',
             capacitance_f=100e-6,rated_voltage_v=25,capacitor_polarized=True),
        dict(id='l',name='Coil',kind='inductor',a='COIL',b='GND',inductance_h=.01,winding_resistance_ohm=100),
        dict(id='a',name='Linear actuator',kind='actuator',a='PWR',b='GND',
             rated_voltage_v=5,rated_current_a=.1,startup_current_a=.2),
    ]))


def test_mixed_physical_and_logical_canvas_wiring_commit_undo_redo_save(app,tmp_path):
    original=mixed();before=deepcopy(original.model_dump())
    for mode in ('physical','symbols'):
        dialog=ElectricalSchematicDialog(None,original,view_mode=mode)
        try:
            dialog.show();app.processEvents()
            assert {'capacitor','inductor','actuator'}<={dialog.kind_combo.itemData(i) for i in range(dialog.kind_combo.count())}
            assert all({'a','b'}<=set(dialog.component_items[identifier].ports) for identifier in ('c','l','a'))
            assert dialog.connect_terminals('c','a','source','a')
            assert dialog.connect_terminals('l','a','source','a')
            assert next(c for c in dialog.workspace.components if c.id=='c').a=='PWR'
            dialog.accept();accepted=dialog.accepted_workspace
            assert accepted is not None and original.model_dump()==before
            design=Design(name='Mixed electronics',electrical=original)
            document=Document();document.commit(design.model_dump(),'Original')
            updated=design.model_dump();updated['electrical']=accepted.model_dump()
            document.commit(updated,'Connect passives')
            path=tmp_path/f'{mode}.cad.json';document.write(path)
            loaded=read_project(path)
            assert loaded.design.electrical==accepted
            current=document.journal.data['cursor'];previous=document.journal.index[current]['parent']
            document.commit(document.journal.at(previous),'Undo',cursor=previous)
            assert document.design['electrical']==before
            document.commit(document.journal.at(current),'Redo',cursor=current)
            assert document.design['electrical']==accepted.model_dump()
        finally:dialog.reject()


@pytest.mark.parametrize('kind',['capacitor','inductor','actuator'])
def test_any_existing_cad_body_can_register_new_kind_without_geometry_change(app,kind):
    design=Design(parts=[Part(id='body',name='Existing body',geometry=dict(kind='cylinder'))])
    dialog=ElectricalPartDialog(None,design,'body')
    try:
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(kind))
        dialog.register_preview()
        assert dialog.component().kind==kind and not dialog.component().analysis_enabled
        assert dialog.draft.parts[0].geometry==design.parts[0].geometry
        assert dialog.draft.parts[0].transform==design.parts[0].transform
        assert dialog.draft.parts[0].color==design.parts[0].color
        assert dialog.draft.parts[0].role=='electrical'
        assert design.electrical is None
    finally:dialog.reject()
