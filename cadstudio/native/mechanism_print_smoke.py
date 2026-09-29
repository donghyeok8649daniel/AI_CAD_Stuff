"""Owned native integration test: no user document, login, or paid AI requests."""
import json,time,traceback
from copy import deepcopy
from PySide6.QtCore import Qt,QPoint,QPointF,QRectF,QThreadPool
from PySide6.QtGui import QImage,QPainter,QWheelEvent
from PySide6.QtWidgets import QFileDialog
from PySide6.QtTest import QTest


def run(app,w,path):
    from .gear_dialog import GearDialog
    from .print_dialog import PrintDialog
    from ..models import Design
    from ..kernel import exact_bounds,build
    from ..joint_readiness import COLORS
    path.parent.mkdir(parents=True,exist_ok=True);report={'checks':[],'live_ai_calls':0};dialogs=[];errors=[]
    original_save=QFileDialog.getSaveFileName
    def check(value,name):
        if not value:raise AssertionError(name)
        report['checks'].append(name)
    def wait(fn):
        end=time.monotonic()+90
        while not fn():
            app.processEvents();QTest.qWait(10)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>end:raise TimeoutError('native mechanism test wait')
        app.processEvents()
    def snapshot(name,target):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        v=target.viewport;v.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(v.window);capture.ReadFrontBufferOff();capture.Update()
        imagepath=path.with_name(name+'-viewport.png');writer=vtkPNGWriter();writer.SetFileName(str(imagepath));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=target.grab();p=QPainter(pix);pos=v.widget.mapTo(target,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),v.widget.width(),v.widget.height()),QImage(str(imagepath)));p.end();pix.save(str(path.with_name(name+'.png')))
    def display(v,point):
        v.renderer.SetWorldPoint(*point,1);v.renderer.WorldToDisplay();return v.renderer.GetDisplayPoint()[:2]
    def qtpoint(v,p):
        ratio=v.widget.devicePixelRatioF();return QPoint(round(p[0]/ratio),round((v.window.GetSize()[1]-1-p[1])/ratio))
    try:
        w.show_error=errors.append;app.setQuitOnLastWindowClosed(False);w.resize(1200,820)
        gear=GearDialog(w,None);dialogs.append(gear);gear.show();wait(lambda:gear.checked is not None)
        check(gear.apply_button.isEnabled() and len(gear.checked.parts)==3,'real three-part gear pair builds in native preview')
        check(not gear.result['stats']['collisions'],'gear pair preview has no actual volume overlap')
        check(all(r['state']=='ready' for r in gear.result['stats']['joint_readiness'].values()),'both physical shaft/bore pairs checked')
        raw=gear.checked.model_dump();gear.apply_button.click();check(not gear.isVisible(),'checked gear assembly can apply')
        w.apply_design(raw,'gear fixture',fit=True);wait(lambda:not w.busy);source=deepcopy(w.document.design)
        check('gears' in w.actions,'gear command available in native assembly UI')
        w.actions['joints'].setChecked(True);w.toggle_joints();v=w.viewport
        check(len(v.joints.records)==2 and all(r['readiness']['state']=='ready' for r in v.joints.records),'joint markers use current geometry readiness')
        check(tuple(v.joints.actors[0].GetProperty().GetColor())==COLORS['ready'],'checked joint glyph actually renders green')
        w.show_mate(raw['mates'][0]['id']);check(w.selected_joint==raw['mates'][0]['id'],'joint inspection remains available')
        app.processEvents();v.set_view('top');point=(8,0,8);xy=display(v,point);q=qtpoint(v,xy);scale=v.renderer.GetActiveCamera().GetParallelScale()
        event=QWheelEvent(QPointF(q),QPointF(v.widget.mapToGlobal(q)),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        app.sendEvent(v.widget,event);app.processEvents();after=display(v,point)
        check(abs(v.renderer.GetActiveCamera().GetParallelScale()-scale/1.18)<1e-6,'one Qt wheel event applies one cursor zoom increment')
        check(sum((a-b)**2 for a,b in zip(after,xy))**.5<2,'surface under mouse stays at same screen location')
        snapshot('mechanism2110-joints',w)
        # Sketch wheel uses exactly the same cursor anchoring convention.
        canvas=w.editor.canvas;canvas.resize(600,400);q=QPointF(411,133);before=canvas.world(q,False)
        event=QWheelEvent(q,q,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        canvas.wheelEvent(event);after=canvas.world(q,False)
        check(all(abs(before[k]-after[k])<1e-8 for k in ('x','y')),'sketch zoom preserves arbitrary cursor coordinates')
        printing=PrintDialog(w,source);dialogs.append(printing);printing.show();wait(lambda:printing.checked is not None)
        check(printing.apply_button.isEnabled(),'initial automatic print packing fits')
        first=source['parts'][1]['id'];printing.active_part.setCurrentIndex(printing.active_part.findData(first))
        printing.pose_inputs['x'].setValue(55);printing.pose_inputs['y'].setValue(60);printing.pose_inputs['rx'].setValue(180)
        check(not printing.apply_button.isEnabled() and printing.checked is None,'changing placement immediately invalidates STL export')
        wait(lambda:printing.checked is not None);check(printing.apply_button.isEnabled(),'individual orientation and position revalidate')
        p=printing.placements[first];check(p['rx']==180 and p['x']==55 and p['y']==60,'per-part orientation and bed center stored in checked preview')
        v=printing.viewport;printing.top_plate();actor=v.actors[first][0];bounds=actor.GetBounds();xy=display(v,(p['x'],p['y'],bounds[5]));start=qtpoint(v,xy)
        QTest.mousePress(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
        QTest.mouseMove(v.widget,start+QPoint(18,-10),30);app.processEvents()
        check(not printing.apply_button.isEnabled(),'direct drag blocks exporting stale placement')
        QTest.mouseRelease(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start+QPoint(18,-10))
        wait(lambda:printing.checked is not None)
        check(printing.placements[first]['x']>55 and printing.placements[first]['y']>60,'actual mouse drag moves part on plate in world millimeters')
        check(printing.apply_button.isEnabled(),'dragged placement is checked before export')
        printing.pose_inputs['x'].setValue(210);wait(lambda:printing.checked is not None)
        check(not printing.apply_button.isEnabled() and printing.warnings,'manual placement outside bed blocks STL')
        printing.pose_inputs['x'].setValue(55);wait(lambda:printing.checked is not None)
        target=path.with_name('manually-arranged.stl');QFileDialog.getSaveFileName=lambda *a,**k:(str(target),'STL')
        printing.apply_button.click();wait(lambda:not printing.running)
        check(target.is_file() and target.stat().st_size>84,'native export writes actual arranged STL')
        from vtkmodules.vtkIOGeometry import vtkSTLReader
        reader=vtkSTLReader();reader.SetFileName(str(target));reader.Update();actual=reader.GetOutput().GetBounds();s=printing.result['stats'];expected=[v for pair in zip(s['min'],s['max']) for v in pair]
        check(max(abs(a-b) for a,b in zip(actual,expected))<.05,'STL bounds agree with manual plate preview')
        snapshot('printing2110-manual',printing)
        check(source==w.document.design,'preview, drag, orientation and export preserve original assembly')
        printing.reject();check(not printing.alive,'print preview closes safely after export')
        report['success']=True
    except Exception:
        report['error']=traceback.format_exc();report['success']=False
    finally:
        QFileDialog.getSaveFileName=original_save
        for d in dialogs:
            if d.alive:d.reject()
        QThreadPool.globalInstance().waitForDone(10000);w.document.dirty=False;w.close()
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');app.exit(0 if report.get('success') else 1)
