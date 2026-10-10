from copy import deepcopy
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from cadstudio.firmware_bundle import create_bundle
from cadstudio.firmware_libraries import import_library_directory, pinned_dependency
from cadstudio.native.document import Document, read_project
from cadstudio.native.firmware_dialog import FirmwareDialog
from cadstudio.models import Design


CONFIG=dict(model='owned-model',effort='high',catalog=[dict(model='owned-model',name='Owned',efforts=['high'])])


def workspace():
    return dict(nodes=['GND','V5'],components=[dict(id='board',name='Pi',kind='mcu',a='V5',b='GND',
        catalog_id='rpi4b',pinout_catalog_id='rpi4b',part_registration=True,part_id='cad_board',analysis_enabled=False)])


def candidate(work, libraries=()):
    return create_bundle('Imported library controller','raspberry_python',work,'board',
        [dict(path='main.py',content='import sensor\nvalue = sensor.VALUE\n')],'main.py',libraries=libraries)


@pytest.fixture(scope='module')
def app():
    application=QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    font=Path('C:/Windows/Fonts/malgun.ttf')
    if font.is_file(): QFontDatabase.addApplicationFont(str(font))
    from cadstudio.native.widgets import apply_theme
    apply_theme(application)
    return application


def wait(app,predicate):
    deadline=time.monotonic()+8
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();QTest.qWait(10)
    assert predicate()


def dispose(app,dialog):
    dialog.reject();dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_native_import_preview_generation_and_save_preserve_sources(app,tmp_path):
    root=tmp_path/'source';root.mkdir();(root/'sensor.py').write_bytes(b'VALUE = 42\n')
    seen=[]
    def generate(work,board,operation,model,**options):
        seen.append(deepcopy(options['libraries']))
        return SimpleNamespace(bundle=candidate(work,options['libraries']),message='Ready',pending_checks=())
    original=workspace();before=deepcopy(original)
    dialog=FirmwareDialog(original,language='en',codex_config=CONFIG,generation_transport=generate)
    dialog.show();dialog.import_library('directory',root,name='Sensor',version='1.2.3')
    wait(app,lambda:dialog.task is None)
    assert dialog.libraries_table.rowCount()==1
    assert dialog.library_source.toPlainText()=='VALUE = 42\n'
    assert dialog.library_source.isReadOnly() and dialog.accepted_workspace is None
    dialog.tabs.setCurrentWidget(dialog.libraries_table.parentWidget());app.processEvents()
    dialog.resize(1024,700);app.processEvents()
    assert dialog.width()<=1024 and dialog.height()<=700
    assert dialog.grab().save(str(tmp_path/'firmware-libraries-v3.png'))
    dialog.operation.setPlainText('Use the selected sensor library')
    dialog.generate();wait(app,lambda:dialog.task is None)
    assert seen[0][0].version=='1.2.3' and dialog.bundle.libraries==seen[0]
    dialog.accept();wait(app,lambda:dialog.task is None)
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert dialog.accepted_workspace.firmware_bundles[0].libraries==seen[0]
    assert original==before and (root/'sensor.py').read_bytes()==b'VALUE = 42\n'
    dispose(app,dialog)


def test_native_library_removal_cancel_and_reopen_do_not_mutate_saved_bundle(app,tmp_path):
    root=tmp_path/'source';root.mkdir();(root/'sensor.py').write_bytes(b'VALUE = 42\n')
    item=import_library_directory(root,name='Sensor',version='1.2.3',ecosystem='python')
    original=workspace();saved=candidate(original,[item]);original['firmware_bundles']=[saved.model_dump(mode='json')]
    before=deepcopy(original)
    dialog=FirmwareDialog(original,language='en',selected_component_id='board')
    dialog.saved_bundles.setCurrentIndex(dialog.saved_bundles.findData(saved.id))
    assert dialog.libraries_table.rowCount()==1
    dialog.remove_library();assert not dialog._libraries
    dispose(app,dialog)
    assert original==before
    reopened=FirmwareDialog(original,language='en',selected_component_id='board')
    reopened.saved_bundles.setCurrentIndex(reopened.saved_bundles.findData(saved.id))
    assert reopened._libraries==[item]
    dispose(app,reopened)


def test_firmware_effort_labels_match_exact_supported_catalog(app):
    config=dict(model='owned-model',effort='ultra',catalog=[dict(model='owned-model',name='Owned',
        efforts=['low','medium','high','xhigh','max','ultra']),dict(model='owned-other',name='Other',
        efforts=['low','medium','high'])])
    dialog=FirmwareDialog(workspace(),language='ko',codex_config=config)
    assert [dialog.effort.itemText(i) for i in range(dialog.effort.count())]==['Low','Medium','High','Extra high','Max','Ultra']
    assert dialog.effort.currentData()=='ultra'
    dialog.models.setCurrentIndex(dialog.models.findData('owned-other'))
    assert [dialog.effort.itemText(i) for i in range(dialog.effort.count())]==['Low','Medium','High']
    assert dialog.effort.currentData()=='medium'
    dispose(app,dialog)


def test_project_save_open_and_undo_redo_preserve_exact_library_snapshot(tmp_path):
    root=tmp_path/'source';root.mkdir();(root/'sensor.py').write_bytes(b'VALUE = 42\n')
    item=import_library_directory(root,name='Sensor',version='1.2.3',ecosystem='python')
    base=Design.model_validate(dict(name='Library project',parts=[dict(id='cad_board',name='Board',role='electrical',
        geometry=dict(kind='plate',length=85,width=56,thickness=2,hole_count=0))],electrical=workspace()))
    doc=Document();doc.commit(base,'Original')
    changed=base.model_dump();changed['electrical']['firmware_bundles']=[candidate(workspace(),[item]).model_dump()]
    doc.commit(Design.model_validate(changed),'Import firmware library')
    project=tmp_path/'library-project.pcad';doc.write(project)
    loaded=read_project(project)
    assert loaded.design.electrical.firmware_bundles[0].libraries==[item]
    doc.load(loaded,project);entries=doc.journal.path()
    doc.commit(doc.journal.at(entries[0]['id']),'Undo import',cursor=entries[0]['id'])
    assert not doc.project().design.electrical.firmware_bundles
    doc.commit(doc.journal.at(entries[1]['id']),'Redo import',cursor=entries[1]['id'])
    assert doc.project().design.electrical.firmware_bundles[0].libraries==[item]
