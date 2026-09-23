"""Installed-EXE verification of the 2.4 native modelling workbench."""
import json,time,traceback,math
from pathlib import Path


def run(app,window,path):
    from PySide6.QtCore import QThreadPool,QEvent,QPoint,QRectF
    from PySide6.QtGui import QImage,QPainter
    from ..models import Design,Part,Material,SolidFeature,Extrusion
    from ..kernel import preview,local_shape,build,export
    from ..catalog import preset
    from ..imported import import_asset
    from .solid_dialog import RevolveDialog,SolidDialog
    from .feature_manager import FeatureManager
    from .sheetmetal_dialog import SheetMetalDialog
    from .inspection_dialog import InspectionDialog
    from .motion_dialog import MotionDialog
    from .studies import DrawingDialog
    from .document import Document,read_project
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);report={'version':'2.4.0','checks':[]};dialogs=[]
    def check(value,name):
        if not value:raise AssertionError(name)
        report['checks'].append(name)
    def wait(predicate):
        deadline=time.monotonic()+60
        while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        check(predicate(),'native operation completes without blocking the event loop')
    def close(dialog):
        dialog.reject();QThreadPool.globalInstance().waitForDone(30000);app.processEvents();dialog.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();dialogs.remove(dialog)
    def capture(dialog,name):
        from PySide6.QtTest import QTest
        QTest.qWait(100);app.processEvents();view=dialog.viewport
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        view.window.Render();image=vtkWindowToImageFilter();image.SetInput(view.window);image.ReadFrontBufferOff();image.Update();writer=vtkPNGWriter();writer.SetInputConnection(image.GetOutputPort());file=path.with_name(name+'-viewport.png');writer.SetFileName(str(file));writer.Write();pix=dialog.grab();painter=QPainter(pix);pos=view.widget.mapTo(dialog,QPoint(0,0));painter.drawImage(QRectF(pos.x(),pos.y(),view.widget.width(),view.widget.height()),QImage(str(file)));painter.end();pix.save(str(path.with_name(name+'.png')))
    try:
        d=preset('plate');d.parts[0].geometry.hole_count=0;raw=d.model_dump();face=next(f for f in preview(d)['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.9)
        w=SolidDialog(window,raw,d.parts[0].id,face=face);dialogs.append(w);w.show();wait(lambda:w.checked is not None);check(local_shape(w.checked,w.checked.parts[0]).Volume()<local_shape(d,d.parts[0]).Volume(),'native shell removes exact volume');w.tabs.setCurrentIndex(1);capture(w,'native240-solid');raw=w.checked.model_dump();close(w)
        w=FeatureManager(window,raw,d.parts[0].id);dialogs.append(w);w.show();wait(lambda:w.checked is not None);check(w.list.count()==1,'feature manager retains feature sequence');close(w)
        w=RevolveDialog(window,Design().model_dump());dialogs.append(w);w.show();wait(lambda:w.checked is not None);check(abs(build(w.checked)[0].Volume()-math.pi*200*20)<1e-5,'revolution matches analytical annulus volume');close(w)
        w=SheetMetalDialog(window,Design().model_dump());dialogs.append(w);w.show();wait(lambda:w.checked is not None);capture(w,'native240-sheetmetal');check('전개 길이' in w.summary.text(),'sheet metal displays bend allowance and developed length');close(w)
        raw=preset('robot_arm').model_dump();w=MotionDialog(window,raw);dialogs.append(w);w.show();w.ratio.setValue(-2);w.add_link();wait(lambda:w.checked is not None);check(len(w.checked.motion_links)==1,'native motion link validates');capture(w,'native240-motion');close(w)
        d=Design(parts=[Part(id='tube',name='튜브',geometry=dict(kind='cylinder',diameter=20,bore_diameter=10,height=30),material=Material())]);w=InspectionDialog(window,d.model_dump(),'tube');dialogs.append(w);w.show();w.mode.setCurrentIndex(w.mode.findData('section'));w.origin[2].setValue(15);wait(lambda:w.checked is not None);check('235.619449' in w.output.text(),'section area is exact annulus area');capture(w,'native240-inspection');close(w)
        w=DrawingDialog(window,d.model_dump());dialogs.append(w);w.show();w.extra.setCurrentIndex(w.extra.findData('section'));w.section_axis.setCurrentIndex(w.section_axis.findData('Z'));w.section_offset.setValue(15);w.all_parts.setChecked(True);w.calculate();wait(lambda:not w.running);check(w.checked is not None,w.status.text());check(len(w.output['pages'])==2,'drawing book contains assembly and component sheets');w.grab().save(str(path.with_name('native240-drawing.png')))
        from ..drawings import export_book
        pdf=path.with_name('native240-drawing.pdf');export_book(w.output['pages'],pdf);check(pdf.stat().st_size>1000,'multipage PDF exports');close(w)
        step=path.with_name('native240-import.step');export(d,step,'step');asset=import_asset(step);imported=Design(parts=[Part(id='import',name='Imported',geometry=dict(kind='imported',asset_id='asset'))],assets={'asset':asset});doc=Document();doc.commit(imported,'Import');file=path.with_name('native240-import.cad.json');doc.write(file);step.unlink();reopened=read_project(file);check(abs(local_shape(reopened.design,reopened.design.parts[0]).Volume()-math.pi*75*30)<1e-5,'imported geometry survives deletion of external source and project reopen')
        check(all(key in window.actions for key in ('revolve','solid_tools','feature_manager','import_model','motion_links','configurations','inspection','sheetmetal')),'new native commands are discoverable in command search')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');window.document.dirty=False;app.exit(0)
    except Exception:
        report['error']=traceback.format_exc();path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        for dialog in list(dialogs):close(dialog)
        window.document.dirty=False;app.exit(1)
