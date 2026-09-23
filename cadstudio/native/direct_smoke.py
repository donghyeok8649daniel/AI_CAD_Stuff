"""Exercise the actual packaged widgets, handles, selection and parameter history."""
import json,time,traceback
from pathlib import Path


def run(app,w,path):
    from PySide6.QtCore import Qt,QPoint,QRectF,QEvent,QTimer
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtWidgets import QTextBrowser,QApplication
    from PySide6.QtTest import QTest
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
    from vtkmodules.vtkIOImage import vtkPNGWriter
    from ..models import Design
    from .extrude import ExtrudeDialog
    from .parameters import ParameterDialog
    from .document import read_project
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);checks=[];dialogs=[]
    def check(value,message):
        if not value:raise AssertionError(message)
        checks.append(message)
    def wait(condition):
        end=time.monotonic()+25
        while not condition() and time.monotonic()<end:app.processEvents();QTest.qWait(15)
        check(condition(),'background computation completed')
    def snapshot(host,view,name):
        view.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(view.window);capture.ReadFrontBufferOff();capture.Update();writer=vtkPNGWriter();writer.SetFileName(str(path.with_name(name+'-viewport.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=host.grab();p=QPainter(pix);pos=view.widget.mapTo(host,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),view.widget.width(),view.widget.height()),QImage(str(path.with_name(name+'-viewport.png'))));p.end();pix.save(str(path.with_name(name+'.png')))
    try:
        app.setQuitOnLastWindowClosed(False);w.resize(1180,780);w.activateWindow();app.processEvents()
        check(w.provider.currentData()=='ollama' and w.ai_dock.isVisible(),'Ollama panel enabled by default')
        w.prompt.setFocus();w.prompt.clear();QTest.keyClicks(w.prompt,'spherex');check(w.prompt.toPlainText()=='spherex' and not w.sketching,'typing letters in prompt never runs shortcuts')
        w.viewport.widget.setFocus();QTest.keyClick(w.viewport.widget,Qt.Key.Key_S);check(w.sketching,'S starts a sketch')
        e=w.editor;e.free.setChecked(True);e.set_tool('rectangle')
        for pos in [(13.37,7.21),(41.83,27.69)]:e.input_point(dict(x=pos[0],y=pos[1]))
        e.finish_drawing();wait(lambda:e.preview is not None);check(not e.g['entity_constraints'],'free rectangle creates no automatic constraints');e.finish_sketch();wait(lambda:not w.sketching)
        sid=w.document.design['sketches'][0]['id'];v=w.viewport;v.set_view('top');v.filter.setCurrentIndex(5);app.processEvents()
        v.renderer.SetWorldPoint(20,15,0,1);v.renderer.WorldToDisplay();x,y,_=v.renderer.GetDisplayPoint();v.hover_profile(x,y);v.pick(x,y);check(w.selected_profile==(sid,0),'3D closed profile can be hovered and selected')
        context=w.document.design['sketches'][0]['context'];g=w.document.design['sketches'][0]['geometry'];dlg=ExtrudeDialog(w,w.document.design,g,context,0);dialogs.append(dlg);dlg.show();wait(lambda:dlg.checked is not None);check(dlg.handle is not None,'3D extrusion handle is rendered')
        handle=dlg.handle;tip=handle.center+handle.normal*(handle.depth+handle.pixel_scale()*dlg.viewport.widget.devicePixelRatioF()*48);pos=handle.display(tip);check(handle.press(pos),'screen-projected arrow can be grabbed');handle.move(pos+(35,50));handle.release();wait(lambda:dlg.checked is not None);check(dlg.depth.value()!=8,'drag changes the exact extrusion depth')
        dlg.depth.setValue(12);wait(lambda:dlg.checked is not None);snapshot(dlg,dlg.viewport,'direct-extrude');raw=dlg.checked.model_dump();pid=dlg.part_id;dlg.accept();w.apply_design(raw,'3D 돌출');wait(lambda:not w.busy)
        w.viewport.widget.setFocus();w.activateWindow();app.processEvents();QTest.keyClick(w.viewport.widget,Qt.Key.Key_2,Qt.KeyboardModifier.ShiftModifier);check(w.viewport.selection_mode=='point' and bool(w.viewport.pick_objects),'Shift+2 enables point selection')
        v.set_view('top');vertex=next(iter(v.pick_objects));identifier,record=v.pick_objects[vertex];v.renderer.SetWorldPoint(*record['points'][0],1);v.renderer.WorldToDisplay();x,y,_=v.renderer.GetDisplayPoint();found=[];v.geometry_selected.connect(lambda *args:found.append(args));v.pick(x,y);check(found and found[-1][1]=='point','exact CAD vertex is selectable')
        w.viewport.widget.setFocus();QTest.keyClick(w.viewport.widget,Qt.Key.Key_3,Qt.KeyboardModifier.ShiftModifier);check(v.selection_mode=='edge' and bool(v.pick_objects),'Shift+3 enables edge selection')
        params=ParameterDialog(w,w.document.design);dialogs.append(params);params.show();params.add_row('depth','6');wait(lambda:params.checked is not None);raw=params.checked.model_dump();params.accept();raw['parts'][0]['geometry']['thickness_expression']='depth*2';w.apply_design(raw,'변수 연결');wait(lambda:not w.busy)
        raw=w.document.design.copy();raw['parameters']={'depth':'9'};w.apply_design(raw,'변수 변경');wait(lambda:not w.busy);check(w.document.design['parts'][0]['geometry']['thickness']==18,'variable changes rebuild the extrusion')
        w.document.write(path.with_suffix('.cad.json'));loaded=read_project(path.with_suffix('.cad.json'));check(loaded.design.parts[0].geometry.thickness==18 and len(loaded.history.entries)>=4,'expressions and full history save and reopen')
        w.undo();wait(lambda:not w.busy);check(w.document.design['parts'][0]['geometry']['thickness']==12,'undo restores variable and geometry together')
        w.start_sketch(g=w.document.design['parts'][0]['geometry']);wait(lambda:e.preview is not None);e.free.setChecked(True);line=e.g['entities'][0];e.g['entity_constraints']=[dict(id='first',kind='horizontal',a=line['id']),dict(id='duplicate',kind='horizontal',a=line['id'])];e.solve();wait(lambda:not e.solving);check('과다 구속' in e.status.text() and not e.apply_button.isEnabled(),'redundant constraints display an error and block extrusion');e.grab().save(str(path.with_name('overconstraint.png')));w.cancel_sketch()
        manual=[]
        def close_manual():
            dialog=QApplication.activeModalWidget();view=dialog.findChild(QTextBrowser) if dialog else None;manual.append(bool(view and '자유 배치' in view.toPlainText() and 'Shift+1' in view.toPlainText()))
            if dialog:dialog.accept()
        QTimer.singleShot(300,close_manual);w.help_dialog();check(manual==[True],'bundled F1 manual includes free placement and shortcuts')
        w.viewport.filter.setCurrentIndex(0);w.viewport.set_view('iso');snapshot(w,w.viewport,'direct-workbench');w.document.dirty=False;w.close();path.write_text(json.dumps(dict(success=True,checks=checks),ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
    except Exception:
        for dialog in dialogs:
            if dialog.alive:dialog.reject()
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc()),ensure_ascii=False,indent=2),encoding='utf-8');w.document.dirty=False;w.close();app.exit(1)
