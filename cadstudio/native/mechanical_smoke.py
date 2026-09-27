"""Owned native smoke window for physical joints and component inspection."""
import json,time,traceback
from copy import deepcopy
from zipfile import ZipFile
import numpy as np
from PySide6.QtCore import Qt,QPoint,QRectF,QTimer
from PySide6.QtGui import QPainter,QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ..models import Design
from ..part_export import export_parts
from .part_inspection import ExplodedViewDialog


def run(app,w,path):
    path.parent.mkdir(parents=True,exist_ok=True);report=dict(checks=[]);errors=[]
    def check(ok,name):
        if not ok:raise AssertionError(name)
        report['checks'].append(name)
    def wait(predicate):
        end=time.monotonic()+50
        while not predicate():
            app.processEvents();QTest.qWait(10)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>end:raise TimeoutError('native UI wait')
        app.processEvents()
    def snapshot(name,target):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        v=target.viewport;app.processEvents();v.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(v.window);capture.ReadFrontBufferOff();capture.Update()
        imagepath=path.with_name(name+'-viewport.png');writer=vtkPNGWriter();writer.SetFileName(str(imagepath));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=target.grab();p=QPainter(pix);pos=v.widget.mapTo(target,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),v.widget.width(),v.widget.height()),QImage(str(imagepath)));p.end();pix.save(str(path.with_name(name+'.png')))
    def click(point):
        v=w.viewport;s=v.widget.devicePixelRatioF();p=QPoint(round(point[0]/s),round((v.window.GetSize()[1]-1-point[1])/s))
        QTest.mouseClick(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p);app.processEvents()
    try:
        app.setQuitOnLastWindowClosed(False);w.show_error=errors.append;w.resize(1120,780);w.activateWindow();app.processEvents()
        check(w.document.design is None,'blank startup retained')
        def configure():
            try:
                d=QApplication.activeModalWidget();wait(lambda:d.checked is not None)
                check(len(d.part_ids)==7,'physical joint preview contains seven CAD parts')
                check(not d.result['stats']['collisions'],'default joint has no volume interference')
                check(d.apply_button.isEnabled(),'validated physical structure can be applied')
                snapshot('mechanical280-preview',d);d.apply_button.click()
            except Exception:errors.append(traceback.format_exc());QApplication.activeModalWidget().reject()
        QTimer.singleShot(100,configure);w.actions['joint_hardware'].trigger();wait(lambda:not w.busy)
        check(not errors,'native joint command completes');check(len(w.document.design['parts'])==7,'joint command adds real parts to document')
        raw=deepcopy(w.document.design);ids=[p['id'] for p in raw['parts']]
        check(len(raw['mates'])==6,'ordinary assembly constraints connect hardware')
        check(len(raw['part_groups'][0]['part_ids'])==7,'hardware is a normal editable group')
        check(w.result['stats']['assembly_constraints']['dof']==1,'hardware has one rotary degree of freedom')
        w.actions['group_select'].trigger();check(not w.selected_parts,'turning off group selection clears current selection')
        w.select_clicked_parts([ids[0]]);check(w.selected_parts==ids[:1],'individual hardware can be selected')
        w.actions['isolate'].trigger();check(len(w.viewport.hidden)==6,'isolate hides other six components')
        w.actions['isolate'].trigger();check(not w.viewport.hidden,'isolate restores previous visibility')
        w.actions['box_select'].trigger();w.viewport.widget.setFocus();QTest.keyClick(w.viewport.widget,Qt.Key.Key_Escape);app.processEvents()
        check(w.viewport.orbit_mode and not w.viewport.box_mode and not w.selected_parts,'Escape clears selection and exits box mode to orbit')
        for axis,index in [('x',0),('y',1),('z',2)]:
            w.viewport.set_view('iso');app.processEvents();points=w.viewport.axis_points();click(points['origin']*.15+points[axis]*.85)
            camera=w.viewport.renderer.GetActiveCamera();direction=np.array(camera.GetPosition())-camera.GetFocalPoint();direction/=np.linalg.norm(direction)
            check(np.allclose(direction,np.eye(3)[index]),axis.upper()+' glyph click changes camera only')
        check(w.document.design==raw,'selection and camera actions preserve document')
        w.viewport.set_view('iso');w.actions['orbit'].trigger();w.select_parts(ids);snapshot('mechanical280-workbench',w)
        dialog=ExplodedViewDialog(w,w.result);dialog.show();QTest.qWait(150);app.processEvents()
        check(dialog.viewport.widget.isVisible() and dialog.viewport.widget.height()>150,'exploded viewport is visible and usable')
        check(dialog.viewport.result['stats']['bounds'][2]>w.result['stats']['bounds'][2]+100,'exploded view separates actual geometry')
        snapshot('mechanical280-exploded',dialog);dialog.distance.setValue(0);app.processEvents()
        check(np.allclose(dialog.viewport.result['stats']['bounds'],w.result['stats']['bounds']),'exploded view restores assembly at zero spacing');dialog.reject()
        check(w.document.design==raw,'exploded inspection never alters original joints')
        exported=export_parts(raw,ids,path.with_name('mechanical280-parts.zip'))
        with ZipFile(path.with_name('mechanical280-parts.zip')) as archive:
            check(len(archive.namelist())==15 and archive.testzip() is None,'seven separate STEP and STL files plus manifest exported')
        check(len(exported['parts'])==7,'export manifest identifies every hardware component')
        report['passed']=True
    except Exception:report['passed']=False;report['error']=traceback.format_exc()
    finally:
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');w.document.dirty=False
        QTimer.singleShot(200,lambda:app.exit(0 if report['passed'] else 1))
