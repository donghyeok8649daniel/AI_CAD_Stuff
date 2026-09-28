"""Owned native integration checks; all AI/account responses are offline fixtures."""
import json,time,traceback
from copy import deepcopy
from PySide6.QtCore import QTimer,QPoint,QRectF
from PySide6.QtGui import QImage,QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog,QMessageBox
from ..models import Design,Part
from ..kernel import preview
from ..joint_hardware import add_revolute_hardware
from .workflows import JointDriveDialog
from .print_dialog import PrintDialog
from .draft_preview import DraftPreviewDialog
from . import ai_chat,codex_connection


def run(app,w,path):
    path.parent.mkdir(parents=True,exist_ok=True);report={'checks':[],'live_ai_calls':0};dialogs=[];errors=[]
    original_answer=ai_chat.answer;original_connect=codex_connection.connect;original_save=QFileDialog.getSaveFileName
    def check(condition,name):
        if not condition:raise AssertionError(name)
        report['checks'].append(name)
    def wait(condition):
        end=time.monotonic()+60
        while not condition():
            app.processEvents();QTest.qWait(10)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>end:raise TimeoutError('native integration wait')
        app.processEvents()
    def snapshot(name,target):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        app.processEvents();v=target.viewport;v.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(v.window);capture.ReadFrontBufferOff();capture.Update()
        imagepath=path.with_name(name+'-viewport.png');writer=vtkPNGWriter();writer.SetFileName(str(imagepath));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=target.grab();p=QPainter(pix);pos=v.widget.mapTo(target,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),v.widget.width(),v.widget.height()),QImage(str(imagepath)));p.end();pix.save(str(path.with_name(name+'.png')))
    try:
        w.show_error=errors.append;w.resize(1200,820);app.setQuitOnLastWindowClosed(False)
        check(w.document.design is None,'blank startup retained')
        check('v2.10.0' in w.windowTitle(),'version 2.10.0 visible')
        design=Design(parts=[Part(id='base',name='기준판',fixed=True,geometry=dict(kind='plate',length=5,width=5,thickness=2,hole_count=0)),
            Part(id='arm',name='회전 팔',geometry=dict(kind='extrusion',thickness=2,sketch_mode='polygon',points=[dict(x=x,y=y) for x,y in [(0,-1),(20,-1),(20,1),(0,1)]])),
            Part(id='stop',name='장애물',fixed=True,geometry=dict(kind='plate',length=4,width=4,thickness=2,hole_count=0),transform=dict(x=15,z=4))],
            mates=[dict(id='hinge',kind='revolute',parent='base',child='arm',z=4,rz=-90)])
        w.apply_design(design.model_dump(),'motion fixture');wait(lambda:not w.busy);before=deepcopy(w.document.design)
        dialog=JointDriveDialog(w,before);dialogs.append(dialog);dialog.resize(1000,720);dialog.show();dialog.inputs[('hinge','rz')].setValue(90);wait(lambda:dialog.checked is not None)
        check(bool(dialog.travel['blocked']),'clear endpoints still catch intermediate obstruction')
        check(not dialog.apply_button.isEnabled(),'colliding motion cannot apply')
        dialog.accept();check(dialog.alive,'accept guard cannot bypass collision')
        check(dialog.viewport.collision_button.isVisible(),'first collision pose has visible warning badge')
        check(bool(dialog.result['stats']['collisions']),'preview shows actual colliding intermediate pose')
        snapshot('motion210-blocked',dialog)
        dialog.stop_button.click();wait(lambda:dialog.checked is not None)
        check(dialog.apply_button.isEnabled() and not dialog.travel['blocked'],'last checked pose revalidates without overlap')
        dialog.reject();check(w.document.design==before,'motion preview cancellation preserves original')
        hardware,_=add_revolute_hardware(prefix='print-');check(not preview(hardware)['stats']['collisions'],'physical hardware has no nominal overlap')
        print_raw=hardware.model_dump();print_before=deepcopy(print_raw)
        printing=PrintDialog(w,print_raw);dialogs.append(printing);printing.resize(1100,760);printing.show();wait(lambda:printing.checked is not None)
        check(not printing.warnings and printing.apply_button.isEnabled(),'seven separate hardware parts fit build plate')
        check(abs(printing.result['stats']['min'][2])<1e-6,'all parts sit on Z zero')
        check(not printing.result['stats']['collisions'],'output plate has no interference')
        printing.bed[0].setValue(5);wait(lambda:printing.checked is not None);check(not printing.apply_button.isEnabled(),'outside build volume blocks STL')
        printing.bed[0].setValue(220);wait(lambda:printing.checked is not None);snapshot('printing210-preview',printing)
        output=path.with_name('printing210-hardware.stl');QFileDialog.getSaveFileName=lambda *a,**k:(str(output),'STL');printing.apply_button.click();wait(lambda:not printing.running)
        check(output.is_file() and output.stat().st_size>84,'frozen app writes STL from checked preview')
        check(print_raw==print_before,'print preparation and export do not modify source assembly');printing.reject()
        comparison=DraftPreviewDialog(w,w.result,preview(hardware),'하우징 / 부시 / 축 · 7개 부품');dialogs.append(comparison);comparison.show()
        check(len(comparison.viewport.result['meshes'])==7,'AI after preview displays candidate')
        comparison.mode.setCurrentIndex(1);app.processEvents();check(len(comparison.viewport.result['meshes'])==3,'AI before preview displays original')
        comparison.mode.setCurrentIndex(0);snapshot('ai210-compare',comparison);comparison.reject();check(w.document.design==before,'comparison dismissal preserves document')
        w.ai_dock.show();w.ai_dock.raise_();w.codex_config=dict(executable='offline-fixture',model='fixture');w.provider.setCurrentIndex(w.provider.findData('codex'));w.provider_changed()
        check('✓' not in w.codex_status.text(),'saved model alone has no connected checkmark')
        codex_connection.connect=lambda *a,**k:dict(account={'plan':'pro'},models=[dict(model='fixture',efforts=['medium'])],executable='offline-fixture')
        w.codex_check_button.click();wait(lambda:w.codex_probe_task is None);check('✓' in w.codex_status.text(),'verified account and selected model show green checkmark')
        ai_chat.answer=lambda *a,**k:'필렛은 모서리를 둥글게 만드는 기능입니다. 이 답변은 설계를 바꾸지 않습니다.'
        w.ai_mode.setCurrentIndex(w.ai_mode.findData('chat'));w.prompt.setPlainText('필렛은 뭐야?');w.generate_button.click();wait(lambda:w.ai_task is None)
        check('필렛' in w.ai_result.toPlainText() and w.last_draft is None,'question answer shown without draft')
        check(w.document.design==before and not w.accept_draft.isEnabled(),'Q&A cannot apply CAD changes')
        snapshot('ai210-chat-connected',w)
        def unavailable(*a,**k):raise ValueError('Offline fixture: login required')
        codex_connection.connect=unavailable;w.codex_check_button.click();wait(lambda:w.codex_probe_task is None);check('✓' not in w.codex_status.text(),'failed check removes connected checkmark')
        w.ai_mode.setCurrentIndex(0);w.provider.setCurrentIndex(w.provider.findData('ollama'));w.ai_settings_toggle.setChecked(False);w.resize(820,560);w.ai_scroll.verticalScrollBar().setValue(0);app.processEvents()
        check(w.prompt.visibleRegion().contains(w.prompt.rect()),'prompt accessible in compact layout')
        check(w.generate_button.visibleRegion().contains(w.generate_button.rect()) and w.accept_draft.visibleRegion().contains(w.accept_draft.rect()),'generate and preview actions accessible in compact layout')
        from .display_style import preferences,DisplayStyleDialog,DisplayPreferences
        prefs=preferences();style_before=prefs.style.model_copy(deep=True)
        display=DisplayStyleDialog(w);display.show();display.fields['grid_width'].setValue(2.5);display.fields['grid_brightness'].setValue(65);display.fields['axes_width'].setValue(3.5);display.set_value('grid_color','#69b9e0');app.processEvents()
        check(w.viewport.grid_actor.GetProperty().GetLineWidth()==2.5,'grid thickness changes immediately')
        check(abs(w.viewport.grid_actor.GetProperty().GetOpacity()-.65)<1e-6,'grid brightness reaches actual VTK grid')
        check(w.viewport.axes.GetXAxisShaftProperty().GetLineWidth()==3.5,'XYZ line thickness reaches orientation axes')
        check(w.editor.canvas.display_prefs.style.grid_color=='#69b9e0','sketch and 3D share appearance preferences')
        display.reject();check(prefs.style==style_before,'appearance cancel restores original values')
        display=DisplayStyleDialog(w);display.fields['axes_width'].setValue(3);display.accept()
        check(DisplayPreferences(prefs.path).style.axes_width==3,'appearance persists independently of project and language')
        prefs.set(style_before,persist=True)
        from .joint_alignment_dialog import JointAlignmentDialog
        from ..joint_alignment import options
        from ..assembly_motion import set_joint_motion
        from ..kernel import build
        import numpy as np
        from ..threads import cylinder_records
        eccentric=Design(parts=[Part(id='a',name='기준 구멍',fixed=True,geometry=dict(kind='cylinder',diameter=30,bore_diameter=12.4,height=20),transform=dict(rx=70,ry=20)),Part(id='b',name='회전 축',geometry=dict(kind='cylinder',diameter=12,height=20))],mates=[dict(id='j',kind='revolute',parent='a',child='b',x=1.6,rx=15)])
        raw=eccentric.model_dump();a,b=options(raw,'j');pi=next(r['index'] for r in a if r['internal']);ci=b[0]['index']
        alignment=JointAlignmentDialog(w,raw,'j');dialogs.append(alignment);alignment.show();wait(lambda:alignment.faces_for=='j')
        check(not alignment.apply_button.isEnabled(),'concentric repair requires explicit cylinder selections')
        alignment.parent_face.setCurrentIndex(alignment.parent_face.findData(pi));alignment.child_face.setCurrentIndex(alignment.child_face.findData(ci));wait(lambda:alignment.alignment is not None)
        check(abs(alignment.alignment['offset_mm']-1.6)<1e-7,'eccentricity measured from actual cylindrical axes')
        check(alignment.apply_button.isEnabled() and not alignment.result['stats']['collisions'],'concentric repair preview clears shaft/bore interference')
        snapshot('joint210-alignment',alignment)
        alignment.keep_pose.setChecked(False);alignment.gap.setValue(20);alignment.flip.setChecked(True);wait(lambda:alignment.checked is not None)
        check(alignment.checked.joint_frames[0].flipped and alignment.apply_button.isEnabled() and not alignment.result['stats']['collisions'],'opposite shaft orientation and insertion depth remain concentric and clear')
        changed=alignment.checked.model_dump();set_joint_motion(changed,'j',{'rz':87});shapes=build(Design.model_validate(changed));refs=[next(r for r in cylinder_records(s) if r.internal==bool(i==0)) for i,s in enumerate(shapes)];delta=np.array(refs[1].frame.origin)-refs[0].frame.origin
        check(np.linalg.norm(np.cross(delta,refs[0].frame.normal))<1e-7 and abs(np.dot(refs[0].frame.normal,refs[1].frame.normal))>1-1e-7,'actual cylinder axes remain concentric after joint rotation')
        alignment.reject();check(raw==eccentric.model_dump() and w.document.design==before,'joint repair preview cancellation preserves source work')
        report['passed']=True
    except Exception:report['passed']=False;report['error']=traceback.format_exc()
    finally:
        ai_chat.answer=original_answer;codex_connection.connect=original_connect;QFileDialog.getSaveFileName=original_save
        for dialog in dialogs:
            if getattr(dialog,'alive',False):dialog.reject()
        w.document.dirty=False;path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');QTimer.singleShot(200,lambda:app.exit(0 if report['passed'] else 1))
