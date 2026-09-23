"""Exercise threads through packaged Qt controls and actual CAD exports."""
import json,time,traceback
from pathlib import Path


def run(app,w,path):
    from PySide6.QtCore import Qt,QTimer,QPoint,QRectF,QThreadPool
    from PySide6.QtGui import QPainter,QImage
    from PySide6.QtWidgets import QApplication,QPushButton
    from PySide6.QtTest import QTest
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
    from vtkmodules.vtkIOImage import vtkPNGWriter
    from ..models import Design,Part
    from ..kernel import local_shape,export
    from .threading_tool import ThreadDialog
    from .document import read_project
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);checks=[];dialogs=[];errors=[]
    def check(value,message):
        if not value:raise AssertionError(message)
        checks.append(message)
    def wait(fn):
        end=time.monotonic()+60
        while not fn() and time.monotonic()<end:app.processEvents();QTest.qWait(15)
        if not fn():raise AssertionError('background thread preview timed out')
    def snapshot(dialog,name):
        view=dialog.viewport;view.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(view.window);capture.ReadFrontBufferOff();capture.Update()
        writer=vtkPNGWriter();writer.SetFileName(str(path.with_name(name+'-viewport.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=dialog.grab();p=QPainter(pix);pos=view.widget.mapTo(dialog,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),view.widget.width(),view.widget.height()),QImage(str(path.with_name(name+'-viewport.png'))));p.end();pix.save(str(path.with_name(name+'.png')))
    try:
        app.setQuitOnLastWindowClosed(False)
        d=Design(parts=[Part(id='bolt',name='M10 축',geometry=dict(kind='cylinder',diameter=10,height=16))]);raw=d.model_dump()
        w.apply_design(raw,'나사 시험 축');wait(lambda:not w.busy);w.select_part('bolt');v=w.viewport;v.filter.setCurrentIndex(3);v.set_view('iso');app.processEvents()
        v.renderer.SetWorldPoint(5/2**.5,-5/2**.5,8,1);v.renderer.WorldToDisplay();x,y,_=v.renderer.GetDisplayPoint();v.pick(x,y)
        check(v.face and v.face[1].get('cylinder'),'cylindrical face is pickable in the 3D viewport')
        check(any('수나사 만들기' in b.text() for b in w.findChildren(QPushButton)),'selected cylinder exposes a direct thread button')
        def edit_modal():
            dialog=QApplication.activeModalWidget()
            try:
                check(isinstance(dialog,ThreadDialog),'T opens native Thread dialog');dialogs.append(dialog)
                wait(lambda:dialog.checked is not None);dialog.fields['length'].setValue(8);wait(lambda:dialog.checked is not None)
                check(dialog.checked.parts[0].features[0].pitch==1.5,'M10 coarse pitch is suggested')
                dialog.tabs.setCurrentIndex(1);app.processEvents();snapshot(dialog,'thread-external');dialog.accept()
            except Exception:
                errors.append(traceback.format_exc())
                if isinstance(dialog,ThreadDialog):dialog.reject()
        w.activateWindow();v.widget.setFocus();app.processEvents();QTimer.singleShot(400,edit_modal);QTest.keyClick(v.widget,Qt.Key.Key_T)
        if errors:raise AssertionError(errors[0])
        wait(lambda:not w.busy);f=w.document.design['parts'][0]['features'][0]
        check(f['kind']=='thread','thread commit is a parametric feature')
        w.show_feature(f['id']);check(any('나사산 / 치수 편집' in b.text() for b in w.findChildren(QPushButton)),'history feature exposes thread editing')
        w.document.write(path.with_suffix('.cad.json'));saved=read_project(path.with_suffix('.cad.json'))
        check(saved.design.parts[0].features[0].kind=='thread','native project preserves thread parameters')
        check(saved.history.entries[-1].context['feature']['cylinder']['index']==f['cylinder']['index'],'history stores the exact selected cylinder')
        export(saved.design,path.with_suffix('.step'),'step');export(saved.design,path.with_suffix('.stl'),'stl')
        check(path.with_suffix('.step').stat().st_size>1000 and path.with_suffix('.stl').stat().st_size>1000,'modeled threads export to STEP and STL')
        w.undo();wait(lambda:not w.busy);check(not w.document.design['parts'][0]['features'],'undo removes the thread feature')
        w.redo();wait(lambda:not w.busy);check(w.document.design['parts'][0]['features'][0]['kind']=='thread','redo restores the thread feature')
        dialog=ThreadDialog(w,w.document.design,'bolt',f['id']);dialogs.append(dialog);dialog.show();wait(lambda:dialog.checked is not None)
        dialog.fields['length'].setValue(6);dialog.hand.setCurrentIndex(1);wait(lambda:dialog.checked is not None)
        check(len(dialog.checked.parts[0].features)==1 and dialog.checked.parts[0].features[0].length==6 and dialog.checked.parts[0].features[0].handedness=='left','existing thread edits without duplication')
        dialog.fields['length'].setValue(99);wait(lambda:not dialog.running and not dialog.timer.isActive())
        check(dialog.checked is None and not dialog.apply_button.isEnabled(),'invalid length cannot be applied');dialog.reject()
        tap=Design(parts=[Part(id='tap',name='M6 탭',geometry=dict(kind='cylinder',diameter=12,height=8,bore_diameter=5))])
        dialog=ThreadDialog(w,tap.model_dump(),'tap');dialogs.append(dialog);dialog.show();wait(lambda:dialog.ready)
        ref=next(r for r in dialog.refs.values() if r.internal);dialog.pick_face('tap',{'index':ref.index});wait(lambda:dialog.checked is not None)
        f=dialog.checked.parts[0].features[0];check(f.cylinder.internal and f.diameter==6 and f.pitch==1,'inner hole selection suggests an M6 tap')
        check(local_shape(dialog.checked,dialog.checked.parts[0]).Volume()<local_shape(tap,tap.parts[0]).Volume(),'internal helical thread removes real material')
        dialog.tabs.setCurrentIndex(1);app.processEvents();snapshot(dialog,'thread-internal');dialog.reject()
        dialog=ThreadDialog(w,raw,'bolt');dialogs.append(dialog);dialog.show();start=time.monotonic();dialog.reject()
        check(time.monotonic()-start<1,'cancel closes while base geometry is loading');wait(lambda:not dialog.running)
        check(QThreadPool.globalInstance().waitForDone(10000),'thread workers drain cleanly')
        w.document.dirty=False;w.close();path.write_text(json.dumps(dict(success=True,checks=checks),ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
    except Exception:
        for dialog in dialogs:
            if dialog.alive:dialog.reject()
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc()),ensure_ascii=False,indent=2),encoding='utf-8');w.document.dirty=False;w.close();app.exit(1)
