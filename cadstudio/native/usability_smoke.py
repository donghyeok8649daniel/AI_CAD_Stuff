"""Owned Qt/VTK integration checks for v2.9. No paid or network requests."""
import json,time,traceback
from copy import deepcopy
from PySide6.QtCore import QTimer,QPoint,QRectF
from PySide6.QtGui import QPainter,QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ..models import Design,Part,Project
from ..kernel import local_shape
from ..component_specs import parse_product_page,spec_prompt
from .print_profile_dialog import PrintProfileDialog
from .electronics_dialog import ElectronicsMountDialog


def run(app,w,path):
    path.parent.mkdir(parents=True,exist_ok=True);report={'checks':[]};errors=[];dialogs=[]
    def check(condition,name):
        if not condition:raise AssertionError(name)
        report['checks'].append(name)
    def wait(predicate):
        end=time.monotonic()+45
        while not predicate():
            app.processEvents();QTest.qWait(10)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>end:raise TimeoutError('native usability wait')
        app.processEvents()
    def snapshot(name,target):
        app.processEvents()
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        v=target.viewport;v.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(v.window);capture.ReadFrontBufferOff();capture.Update();imagepath=path.with_name(name+'-viewport.png');writer=vtkPNGWriter();writer.SetFileName(str(imagepath));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=target.grab();p=QPainter(pix);pos=v.widget.mapTo(target,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),v.widget.width(),v.widget.height()),QImage(str(imagepath)));p.end();pix.save(str(path.with_name(name+'.png')))
    try:
        app.setQuitOnLastWindowClosed(False);w.show_error=errors.append;w.resize(1200,820);w.activateWindow();app.processEvents()
        check(w.document.design is None,'blank startup')
        check('v2.10.0' in w.windowTitle(),'title bar exposes current app version')
        check('10 mm' in w.viewport.grid_label.text(),'3D grid reports actual ten-mm cell')
        w.actions['grid'].trigger();w.actions['axes'].trigger()
        check(not w.viewport.grid_actor.GetVisibility() and not w.viewport.axes_widget.GetEnabled(),'grid and axis glyph can be hidden independently of CAD data')
        check(w.viewport.axis_at((10,10)) is None,'hidden axis glyph cannot capture clicks')
        w.actions['grid'].trigger();w.actions['axes'].trigger()
        d=Design(parts=[Part(id='host',name='한글 장착판',geometry=dict(kind='plate',length=100,width=80,thickness=10,hole_count=0))]);w.apply_design(d.model_dump(),'장착판');wait(lambda:not w.busy)
        original=deepcopy(w.document.design)
        def configure():
            try:
                dialog=QApplication.activeModalWidget();dialogs.append(dialog);wait(lambda:dialog.checked is not None)
                check(dialog.inputs['hole_expansion'].value()==.2 and dialog.inputs['shaft_reduction'].value()==0,'PLA initial hole +0.2 and shaft zero')
                dialog.inputs['uncertainty'].setValue(.1);wait(lambda:dialog.checked is not None)
                snapshot('usability290-printer',dialog);dialog.apply_button.click()
            except Exception:errors.append(traceback.format_exc());QApplication.activeModalWidget().reject()
        QTimer.singleShot(80,configure);w.actions['print_profile'].trigger();wait(lambda:not w.busy)
        check(w.document.design['print_profile']['uncertainty']==.1,'printer settings committed via native action')
        w.undo();wait(lambda:not w.busy);check('print_profile' not in w.document.design,'undo restores pre-profile design')
        w.redo();wait(lambda:not w.busy);check(w.document.design['print_profile']['hole_expansion']==.2,'redo restores profile')
        face=next(f for f in w.result['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.99)
        dialog=ElectronicsMountDialog(w,w.document.design,'host',face);dialogs.append(dialog);dialog.show();wait(lambda:dialog.checked is not None)
        check(len(dialog.checked.parts[0].features)==5,'electronics preview has pocket plus four ordinary cut features')
        check(dialog.result['stats']['volume']<80000,'electronics preview removes actual material')
        check(w.document.design['parts'][0]['features']==[],'preview is non-destructive before apply')
        w.language_service.set_language('en',False);app.processEvents();wait(lambda:dialog.apply_button.text()=='Apply to design')
        check(dialog.shape.itemText(0)=='Rectangular seat','new dialog controls switch to English')
        snapshot('usability290-electronics-en',dialog);candidate=dialog.checked.model_dump();dialog.accept()
        w.apply_design(candidate,'전장부품 장착');wait(lambda:not w.busy)
        check(len(w.document.design['parts'][0]['features'])==5,'mounting features applied to CAD')
        check(w.document.design['parts'][0]['name']=='한글 장착판','language switch preserves user part name')
        check(w.actions['component_specs'].text()=='Product specs · import URL…','English product-source action exists')
        before=deepcopy(w.document.design);w.actions['grid'].trigger();w.viewport.load(w.result)
        check(not w.viewport.grid_actor.GetVisibility(),'grid visibility survives model reload')
        w.actions['grid'].trigger();check(w.document.design==before,'display toggles preserve geometry and history')
        record=parse_product_page('<title>Example controller</title><p>Dimensions: 40 x 60 x 8 mm</p>','https://example.com/controller')
        record['selected_dimensions_mm']=record['candidates'][0]['dimensions_mm'];w.use_component_source(record)
        check('https://example.com/controller' in w.prompt.toPlainText(),'source URL and evidence transferred into AI prompt')
        check(w.ai_task is None and w.document.design==before,'preparing source prompt does not call AI or change CAD')
        w.ai_dock.hide();w.select_parts(['host']);w.viewport.set_view('iso');snapshot('usability290-workbench-en',w)
        path.with_name('usability290-project.cad.json').write_text(Project(design=Design.model_validate(before)).model_dump_json(indent=2),encoding='utf-8')
        loaded=Project.model_validate_json(path.with_name('usability290-project.cad.json').read_text(encoding='utf-8'))
        check(loaded.design.print_profile.material=='PLA','project roundtrip preserves printer profile')
        w.language_service.set_language('ko',False);app.processEvents();check(w.actions['component_specs'].text()=='제품 스펙 · URL 가져오기…','switch back to Korean')
        w.start_sketch('XY');app.processEvents();check(w.sketching,'sketch mode opens')
        w.actions['grid'].trigger();w.actions['axes'].trigger();app.processEvents()
        check(not w.editor.grid_visible and not w.editor.axes_visible,'grid/axis visibility works in sketch mode')
        w.editor.canvas.grab().save(str(path.with_name('usability290-sketch-grid.png')))
        from .picking import grid_step
        a=grid_step(w.editor.canvas.scale);w.editor.canvas.scale*=5;b=grid_step(w.editor.canvas.scale);w.editor.canvas.update();app.processEvents()
        check(a!=b,'sketch cell length follows adaptive zoom grid')
        w.cancel_sketch();report['passed']=True
    except Exception:report['passed']=False;report['error']=traceback.format_exc()
    finally:
        for dialog in dialogs:
            if getattr(dialog,'alive',False):dialog.reject()
        w.language_service.set_language('ko',False);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');w.document.dirty=False
        QTimer.singleShot(200,lambda:app.exit(0 if report['passed'] else 1))
