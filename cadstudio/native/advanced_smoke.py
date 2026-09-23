"""Exercise the shipped advanced dialogs without external desktop automation."""
import json
import time
import traceback
from pathlib import Path


def run(app,window,path):
    from PySide6.QtCore import QPoint,QRectF,QEvent,QThreadPool
    from PySide6.QtGui import QImage,QPainter
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
    from vtkmodules.vtkIOImage import vtkPNGWriter
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from ..catalog import preset
    from ..models import Design,Project
    from ..kernel import preview,build,export
    from ..drawings import export_sheet
    from ..mechanisms import four_bar
    from .modelling import ModellingDialog,EdgeFinishDialog,ClosureDialog
    from .inspect_tools import HoleDialog,MeasurementDialog,InterferenceDialog,interference_data
    from .fit_dialog import FitDialog
    from .studies import RobotStudy,TensileStudy,DrawingDialog
    from .ai_setup import AISetupDialog
    from .document import Document,read_project
    from .autodesk_export import AutodeskExportDialog
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);checks=[];dialog=None
    def check(value,title):
        if not value:raise AssertionError(title)
        checks.append(title)
    def wait(d):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            app.processEvents();timer=getattr(d,'timer',None)
            if not d.running and (timer is None or not timer.isActive()):break
            time.sleep(.015)
        check(d.checked is not None,d.windowTitle()+' preview: '+d.status.text())
    def snapshot(d,name,viewport=None):
        from PySide6.QtTest import QTest
        check(QTest.qWaitForWindowExposed(d,5000),'native dialog exposed: '+name)
        QTest.qWait(150);app.processEvents()
        if viewport:check(viewport.isVisible() and viewport.widget.width()>250 and viewport.widget.height()>120,'usable viewport layout: '+name)
        pix=d.grab()
        if viewport:
            viewport.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(viewport.window);capture.ReadFrontBufferOff();capture.Update();pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars());check(float(pixels.std())>8,'visible native geometry: '+name)
            png=path.with_name(path.stem+'-'+name+'-view.png');writer=vtkPNGWriter();writer.SetFileName(str(png));writer.SetInputConnection(capture.GetOutputPort());writer.Write();painter=QPainter(pix);pos=viewport.widget.mapTo(d,QPoint());painter.drawImage(QRectF(pos.x(),pos.y(),viewport.widget.width(),viewport.widget.height()),QImage(str(png)));painter.end()
        pix.save(str(path.with_name(path.stem+'-'+name+'.png')))
    def close(d):
        d.reject();QThreadPool.globalInstance().waitForDone(10000);app.processEvents();d.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    try:
        for kind in ('sweep','loft'):
            dialog=ModellingDialog(window,None,kind);dialog.show();wait(dialog);snapshot(dialog,kind,dialog.viewport);export(dialog.checked,path.with_name(kind+'.step'),'step');close(dialog)
        d=preset('plate');d.parts[0].geometry.hole_count=0;raw=d.model_dump();dialog=EdgeFinishDialog(window,raw,d.parts[0].id);dialog.toggle_edge(0);dialog.show();wait(dialog);snapshot(dialog,'fillet-select',dialog.selector);dialog.tabs.setCurrentIndex(1);snapshot(dialog,'fillet-result',dialog.viewport);close(dialog)
        face=next(f for f in preview(d)['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.99);dialog=HoleDialog(window,raw,d.parts[0].id,face);dialog.through.setChecked(True);dialog.show();wait(dialog);check(build(dialog.checked)[0].Volume()<build(d)[0].Volume(),'hole removes material');snapshot(dialog,'hole',dialog.viewport);close(dialog)
        dialog=MeasurementDialog(window,raw);dialog.show();dialog.pick(0);dialog.pick(1);check('mm' in dialog.output.text(),'exact vertex distance in mm');snapshot(dialog,'measure',dialog.viewport);close(dialog)
        mechanism=four_bar();dialog=ClosureDialog(window,mechanism.model_dump(),mechanism.loops[0].id);dialog.show();wait(dialog);snapshot(dialog,'closure',dialog.viewport);close(dialog)
        for cls,kind in ((RobotStudy,'robot_arm'),(TensileStudy,'flat_specimen'),(DrawingDialog,'plate')):
            dialog=cls(window,preset(kind).model_dump());dialog.show();dialog.calculate();wait(dialog)
            if cls is RobotStudy:dialog.slider.setValue(140)
            if cls is TensileStudy:dialog.deform.setValue(20)
            snapshot(dialog,dialog.kind,getattr(dialog,'viewport',None))
            if cls is DrawingDialog:
                for suffix in ('svg','pdf','dxf'):
                    target=path.with_name('drawing.'+suffix);export_sheet(dialog.output,target);check(target.stat().st_size>500,'drawing export '+suffix)
            dialog.accept();doc=Document();doc.commit(Design.model_validate(dialog.candidate),'saved study');target=path.with_name(dialog.kind+'.cad.json');doc.write(target);read_project(target);check(True,'study history reload '+dialog.kind);close(dialog)
        fit_design=preset('cylinder');fit_design.parts[0].id='shaft';fit_design.parts[0].geometry.diameter=10;part=preset('plate').parts[0];part.id='plate';part.geometry.hole_diameter=10;part.transform.x=100;fit_design.parts.append(part)
        dialog=FitDialog(window,fit_design.model_dump());dialog.show();check(abs(dialog.output['maximum']-.04)<1e-8,'fit limits use linked CAD diameters');snapshot(dialog,'fits');dialog.accept();fit_design=Design.model_validate(dialog.candidate);close(dialog)
        dialog=DrawingDialog(window,fit_design.model_dump());dialog.show();dialog.calculate();wait(dialog);snapshot(dialog,'fit-drawing');check(any('9.9800 / 10.0000' in t['text'] for t in dialog.output['texts']),'drawing includes saved diameter limits');close(dialog)
        interference=preset('cylinder');part=interference.parts[0].model_copy(deep=True);part.id='overlap';part.transform.z=10;interference.parts.append(part);result,overlaps=interference_data(interference.model_dump());dialog=InterferenceDialog(window,result,overlaps);dialog.show();snapshot(dialog,'interference',dialog.viewport);check(len(dialog.highlights)==1,'exact interference volume highlighted');close(dialog)
        for fmt in ('f3d','ipt'):
            dialog=AutodeskExportDialog(window,Project(design=preset('cylinder')),fmt);dialog.has_inventor=False;dialog.show();dialog.path.setText(str(path.with_name('native-export.'+fmt).resolve()));dialog.prepare();deadline=time.monotonic()+30
            while dialog.running and time.monotonic()<deadline:app.processEvents();time.sleep(.015)
            check(dialog.folder is not None,'native conversion job prepared: '+fmt);snapshot(dialog,fmt+'-export');close(dialog)
        dialog=AISetupDialog(window);dialog.show();snapshot(dialog,'ai-installer');check(dialog.model.currentData()=='qwen3:8b','packaged optional AI installer opens');close(dialog);dialog=None
        path.write_text(json.dumps(dict(success=True,checks=checks),ensure_ascii=False,indent=2),encoding='utf-8');window.document.dirty=False;window.viewport.shutdown();app.exit(0)
    except Exception:
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc()),ensure_ascii=False,indent=2),encoding='utf-8')
        if dialog:dialog.reject()
        window.document.dirty=False;window.viewport.shutdown();app.exit(1)
