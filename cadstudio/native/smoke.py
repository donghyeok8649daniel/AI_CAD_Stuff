"""Reproducible tests of this application's own Qt widgets and CAD workflow."""
import json
import math
from pathlib import Path
import time
import traceback

def kernel_self_test(path):
    from ..catalog import preset
    from ..kernel import preview,export
    from ..models import Design,Part,Extrusion
    from ..sketch_engine import sketch_status
    from .document import Document,read_project
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);report={}
    for kind in ('round_specimen','extrusion','robot_arm'):
        d=preset(kind);r=preview(d);step=path.with_name(kind+'.step');export(d,step,'step');report[kind]=dict(valid=r['stats']['valid'],parts=len(d.parts),step_bytes=step.stat().st_size)
    g=Extrusion(sketch_mode='entities',entities=[dict(id='circle',kind='circle',center=dict(x=0,y=0),radius=10)],entity_constraints=[dict(id='origin',kind='fixed',a='circle',a_point='center'),dict(id='diameter',kind='diameter',a='circle',value=20)])
    doc=Document();doc.commit(Design(parts=[Part(id='body',name='Circle',geometry=g)]),'Circle');doc.write(path.with_suffix('.cad.json'));read_project(path.with_suffix('.cad.json'));report['analytic']=dict(dof=sketch_status(g)['dof'],valid=preview(doc.project().design)['stats']['valid']);path.write_text(json.dumps(report,indent=2),encoding='utf-8')

def run_smoke(app,window,path):
    from PySide6.QtCore import QTimer,Qt,QPoint,QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    from ..kernel import export
    from .document import read_project
    from .geometry import pt
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);report={'renderer':'Qt Widgets / VTK OpenGL','browser':False,'checks':[]};errors=[];window.show_error=lambda message:errors.append(message);stages=[];started=time.monotonic();state={'index':0,'wait':False};timer=QTimer(window);timer.setInterval(100)
    def check(value,message):
        if not value:raise AssertionError(message)
        report['checks'].append(message)
    def render_frame(name,view=None,host=None):
        view=view or window.viewport;host=host or window
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.util.numpy_support import vtk_to_numpy
        view.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(view.window);capture.ReadFrontBufferOff();capture.Update();pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars());check(float(pixels.std())>8,'native OpenGL renders visible geometry: '+name);writer=vtkPNGWriter();writer.SetFileName(str(path.with_name(path.stem+'-'+name+'-viewport.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        # QWidget.grab cannot include a native OpenGL child. Render that child's
        # own framebuffer into the widget-test snapshot at its actual geometry.
        from PySide6.QtGui import QImage,QPainter
        from PySide6.QtCore import QRectF
        image=QImage(str(path.with_name(path.stem+'-'+name+'-viewport.png')));pixmap=host.grab();painter=QPainter(pixmap);widget=view.widget;pos=widget.mapTo(host,QPoint(0,0));painter.drawImage(QRectF(pos.x(),pos.y(),widget.width(),widget.height()),image);painter.end();pixmap.save(str(path.with_name(path.stem+'-'+name+'-workbench.png')))
    def draw(tool,points):
        e=window.editor;e.set_tool(tool)
        submit=next(b for b in e.findChildren(QPushButton) if b.text()=='좌표로 점 입력')
        for point in points:
            e.x.setValue(point[0]);e.y.setValue(point[1]);QTest.mouseClick(submit,Qt.MouseButton.LeftButton)
        e.finish_drawing()
    def sketch():
        check(window.isVisible(),'native main window visible');window.resize(1024,640);window.start_sketch('XY');e=window.editor;e.set_tool('line');canvas=e.canvas
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,canvas.screen(pt(0,0)).toPoint());QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,canvas.screen(pt(20,10)).toPoint());e.finish_drawing()
        check(len(e.g['entities'])==1,'mouse clicks create an open line')
        b=e.finish_button;check(window.rect().contains(b.mapTo(window,b.rect().bottomRight())),'finish button visible at 1024 x 640')
        QTest.mouseClick(b,Qt.MouseButton.LeftButton)
    def saved_line():
        check(not window.sketching and not window.document.design['parts'],'open sketch finishes without a solid');check(len(window.document.design['sketches'])==1,'open sketch is stored in the document')
        window.document.write(path.with_name(path.stem+'-open.cad.json'));read_project(path.with_name(path.stem+'-open.cad.json'));check(True,'open sketch project and history reload')
        identifier=window.document.design['sketches'][0]['id'];window.edit_saved_sketch(identifier);e=window.editor;line=e.g['entities'][0];QTest.mouseClick(e.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,e.canvas.screen(line['end']).toPoint());check(e.ap.currentData()=='end','mouse endpoint selection feeds exact constraint anchor');e.delete_selected();draw('rectangle',[(-30,-20),(30,20)]);draw('circle',[(0,0),(5,0)]);e.depth.setValue(8)
    def finish_sketch():
        e=window.editor;e.set_tool('point');pos=e.canvas.screen(pt(15,20));app.sendEvent(e.canvas,QMouseEvent(QEvent.Type.MouseMove,pos,e.canvas.mapToGlobal(pos),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier));check(bool(e.canvas.snap),'hover recommends a point on existing sketch geometry');e.grab().save(str(path.with_name(path.stem+'-sketch.png')));QTest.mouseClick(e.finish_button,Qt.MouseButton.LeftButton)
    def open_extrusion(saved):
        from .extrude import ExtrudeDialog
        dialog=ExtrudeDialog(window,window.document.design,saved['geometry'],saved['context']);state['dialog']=dialog;dialog.show()
    def apply_extrusion():
        d=state.pop('dialog');check(d.checked is not None,'3D extrusion preview validates');result=d.checked.model_dump();identifier=d.part_id;d.accept();window.apply_design(result,'3D 돌출',{'tool':'extrude-3d'},after=lambda:window.select_part(identifier))
    def saved_closed():
        check(not window.sketching and not window.document.design['parts'],'closed sketch can finish without extrusion');open_extrusion(window.document.design['sketches'][0])
    def solid():
        check(not window.sketching,'native sketch completion');check(window.result['stats']['valid'],'valid extruded solid');expected=(60*40-math.pi*25)*8;check(abs(window.result['stats']['volume']-expected)<.1,'rectangle and circular hole volume');report['initial_volume']=window.result['stats']['volume'];window.viewport.filter.setCurrentIndex(window.viewport.filter.findData('face'));window.viewport.set_view('top');renderer=window.viewport.renderer;renderer.SetWorldPoint(12,10,8,1);renderer.WorldToDisplay();x,y,_=renderer.GetDisplayPoint();window.viewport.pick(int(x),int(y));check(bool(window.viewport.face and window.viewport.face[1]['planar']),'OpenGL triangle face picking');window.grab().save(str(path.with_name(path.stem+'-solid.png')));window.start_face_sketch();draw('circle',[(15,0),(18,0)]);e=window.editor;e.operation.setCurrentIndex(1);e.depth.setValue(4);e.finish_sketch()
    def saved_face():
        check(not window.sketching,'face sketch can finish before a feature');saved=window.document.design['sketches'][-1];check('face' in saved['context'],'saved face sketch retains support plane');open_extrusion(saved);check(state['dialog'].operation.currentData()=='cut','saved face sketch remembers cut operation')
    def pocket():
        check(not window.sketching,'face sketch completion');check(abs(window.result['stats']['volume']-(report['initial_volume']-math.pi*9*4))<.2,'face pocket removes exact volume');p=window.part();check(len(p['features'])==1 and p['features'][0]['support_feature']=='base','face and previous feature references');check(len(window.document.journal.data['entries'])==5,'timeline commits preserved');entries=window.document.journal.data['entries'];check(any(e['context'].get('tool_actions') for e in entries),'sketch tools stored in history');window.document.write(path.with_suffix('.cad.json'));project=read_project(path.with_suffix('.cad.json'));check(project.history is not None,'project history reload validation');export(project.design,path.with_suffix('.step'),'step');check(path.with_suffix('.step').stat().st_size>500,'STEP export');state['cad_cursor']=window.document.journal.data['cursor'];window.undo()
    def undone():
        check(len(window.part()['features'])==0,'undo restores prior feature state');window.redo()
    def redone():
        from ..catalog import preset
        check(len(window.part()['features'])==1,'redo restores face feature');window.apply_design(preset('robot_arm').model_dump(),'로봇 검증 장면',{'tool':'robot'},fit=True)
    def assembly():
        check(len(window.document.design['mates'])==4,'native assembly with four joints');check(window.result['stats']['valid'],'assembly geometry valid');window.viewport.set_view('iso');window.grab().save(str(path.with_name(path.stem+'-assembly.png')))
        from .workflows import JointDriveDialog
        d=JointDriveDialog(window,window.document.design);state['dialog']=d;d.show();d.inputs[('shoulder','rz')].setValue(75);d.inputs[('elbow','rz')].setValue(-30)
    def driven():
        d=state.pop('dialog');check(d.checked is not None,'joint drive native preview validates');p={p.id:p for p in d.checked.parts};check(abs(p['link-2'].transform.rz-45)<1e-6,'joint slider rotates child and descendants');render_frame('joint-drive',d.viewport,d);result=d.checked.model_dump();d.accept();window.apply_design(result,'관절 자세 적용',{'tool':'joint-drive'})
    def specimen():
        from .workflows import SpecimenDialog
        d=SpecimenDialog(window,window.document.design);state['dialog']=d;d.show();d.kind.setCurrentIndex(d.kind.findData('flat_specimen'));d.inputs['length'].setValue(140);d.inputs['gauge_length'].setValue(40);d.inputs['gauge_width'].setValue(8)
    def specimen_applied():
        d=state.pop('dialog');check(d.checked is not None,'specimen dimension preview validates');check('mm²' in d.metrics.text(),'specimen gauge area and grip length displayed');render_frame('specimen',d.viewport,d);result=d.checked.model_dump();state['specimen_id']=d.part_id;d.accept();window.apply_design(result,'시편 치수 설계',{'tool':'specimen'})
    def face_joint():
        from ..models import Design,Part
        from ..kernel import preview
        from .workflows import FaceJointDialog
        check(any(p['id']==state['specimen_id'] for p in window.document.design['parts']),'specimen applies without losing robot assembly')
        design=Design(parts=[Part(id='base',name='베이스',geometry={'kind':'cylinder','diameter':30,'height':10},fixed=True),Part(id='child',name='이동 부품',geometry={'kind':'plate','length':20,'width':16,'thickness':4,'hole_count':0},transform={'x':60})]);r=preview(design);first=next(f for f in r['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.99);second=next(f for f in r['meshes'][1]['faces'] if f['planar'] and f['normal'][2]<-.99);d=FaceJointDialog(window,design.model_dump(),('base',first),('child',second));state['dialog']=d;d.show();d.angle.setValue(40);d.gap.setValue(2)
    def face_joint_applied():
        d=state.pop('dialog');check(d.checked is not None,'face joint native preview validates');check(abs(d.checked.parts[1].transform.z-12)<1e-6,'face joint aligns actual planes with offset');render_frame('face-joint',d.viewport,d);result=d.checked.model_dump();d.accept();window.apply_design(result,'면 조인트 생성',{'tool':'face-joint'})
    def workflows_complete():
        window.document.write(path.with_name(path.stem+'-workflows.cad.json'));p=read_project(path.with_name(path.stem+'-workflows.cad.json'));check(len(p.design.joint_frames)==1,'face joint and workflow history reload');window.restore_history(state['cad_cursor'])
    def finished():
        check(len(window.part()['features'])==1,'history returns from assembly to CAD');window.viewport.set_view('iso');render_frame('final');window.grab().save(str(path.with_name(path.stem+'-final.png')));report['success']=True;report['elapsed_seconds']=round(time.monotonic()-started,2);path.write_text(json.dumps(report,indent=2),encoding='utf-8');timer.stop();window.document.dirty=False;window.editor.stop();window.viewport.shutdown();app.exit(0)
    stages.extend([sketch,saved_line,finish_sketch,saved_closed,apply_extrusion,solid,saved_face,apply_extrusion,pocket,undone,redone,assembly,driven,specimen,specimen_applied,face_joint,face_joint_applied,workflows_complete,finished])
    def tick():
        try:
            if time.monotonic()-started>100:raise TimeoutError('native smoke workflow exceeded 100 seconds')
            if errors:raise AssertionError('; '.join(errors))
            if window.busy or window.editor.solving or window.editor.solve_timer.isActive():return
            d=state.get('dialog')
            if d and (d.running or d.timer.isActive()):return
            index=state['index']
            if index>=len(stages):return
            state['index']+=1;stages[index]()
        except Exception:
            timer.stop();report.update(success=False,stage=state['index'],error=traceback.format_exc(),sketch_status=window.editor.status.text());path.write_text(json.dumps(report,indent=2),encoding='utf-8');window.document.dirty=False;app.exit(1)
    timer.timeout.connect(tick);timer.start()
