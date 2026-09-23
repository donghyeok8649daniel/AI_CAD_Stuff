import time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QThreadPool
from cadstudio.catalog import preset
from cadstudio.native.document import Document


def test_blank_startup_preserves_autosave_and_explicit_recovery_restores_history(monkeypatch,tmp_path):
    import cadstudio.native.window as module
    global APP
    APP=QApplication.instance() or QApplication([]);APP.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    doc=Document();doc.commit(preset('cylinder'),'이전 작업');path=tmp_path/'native-autosave.cad.json';doc.write(path,autosave=True);before=path.read_bytes()
    w=module.MainWindow();w.show();QTest.qWait(250)
    assert w.document.design is None and w.result is None and path.read_bytes()==before
    w.new_document();assert path.read_bytes()==before
    w.actions['recover'].trigger();end=time.monotonic()+20
    while w.busy and time.monotonic()<end:APP.processEvents();QTest.qWait(10)
    assert not w.busy and w.document.design==doc.design
    assert w.document.path is None and w.document.dirty and w.document.journal.path()[0]['label']=='이전 작업'
    w.document.dirty=False;w.close();APP.processEvents()
    w=module.MainWindow();w.show();QTest.qWait(200);before=path.read_bytes()
    assert w.document.design is None
    w.close();APP.processEvents();assert path.read_bytes()==before
    QThreadPool.globalInstance().waitForDone(5000)


def test_part_selection_hides_old_property_controls_before_deferred_deletion(monkeypatch,tmp_path):
    import cadstudio.native.window as module
    from PySide6.QtWidgets import QLineEdit
    from cadstudio.models import Design,Part
    global APP
    APP=QApplication.instance() or QApplication([]);APP.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    design=Design(parts=[Part(id='a',name='이전 원통',geometry=dict(kind='cylinder')),Part(id='b',name='현재 판',geometry=dict(kind='plate',hole_count=0))])
    w=module.MainWindow();w.document.commit(design,'시작');w.show();w.select_part('a');APP.processEvents()
    old=w.properties.findChildren(QLineEdit);assert old and any(x.isVisible() for x in old)
    w.select_part('b')
    assert not any(x.isVisible() for x in old)
    assert w.property_layout.itemAt(0).widget().text()=='현재 판'
    assert any(x.text()=='현재 판' for x in w.properties.findChildren(QLineEdit))
    APP.processEvents()
    assert any(x.text()=='현재 판' and x.isVisible() for x in w.properties.findChildren(QLineEdit))
    w.document.dirty=False;w.close();APP.processEvents();QThreadPool.globalInstance().waitForDone(5000)
