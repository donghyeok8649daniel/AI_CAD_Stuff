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
    from PySide6.QtCore import QTimer,Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    from ..kernel import export
    from .document import read_project
    from .geometry import pt
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);report={'renderer':'Qt Widgets / VTK OpenGL','browser':False,'checks':[]};errors=[];window.show_error=lambda message:errors.append(message);stages=[];started=time.monotonic();state={'index':0,'wait':False};timer=QTimer(window);timer.setInterval(100)
    def check(value,message):
        if not value:raise AssertionError(message)
        report['checks'].append(message)
    def render_frame(name):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.util.numpy_support import vtk_to_numpy
        window.viewport.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(window.viewport.window);capture.ReadFrontBufferOff();capture.Update();pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars());check(float(pixels.std())>8,'native OpenGL renders visible geometry: '+name);writer=vtkPNGWriter();writer.SetFileName(str(path.with_name(path.stem+'-'+name+'-viewport.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        # QWidget.grab cannot include a native OpenGL child. Render that child's
        # own framebuffer into the widget-test snapshot at its actual geometry.
        from PySide6.QtGui import QImage,QPainter
        from PySide6.QtCore import QRectF
        image=QImage(str(path.with_name(path.stem+'-'+name+'-viewport.png')));pixmap=window.grab();painter=QPainter(pixmap);widget=window.viewport.widget;pos=widget.mapTo(window,QPoint(0,0));painter.drawImage(QRectF(pos.x(),pos.y(),widget.width(),widget.height()),image);painter.end();pixmap.save(str(path.with_name(path.stem+'-'+name+'-workbench.png')))
    def draw(tool,points):
        e=window.editor;e.set_tool(tool)
        submit=next(b for b in e.findChildren(QPushButton) if b.text()=='좌표로 점 입력')
        for point in points:
            e.x.setValue(point[0]);e.y.setValue(point[1]);QTest.mouseClick(submit,Qt.MouseButton.LeftButton)
        e.finish_drawing()
    def sketch():
        check(window.isVisible(),'native main window visible');window.start_sketch('XY');draw('rectangle',[(-30,-20),(30,20)]);draw('circle',[(0,0),(5,0)]);e=window.editor;e.depth.setValue(8)
    def finish_sketch():
        window.editor.grab().save(str(path.with_name(path.stem+'-sketch.png')));window.editor.finish()
    def solid():
        check(not window.sketching,'native sketch completion');check(window.result['stats']['valid'],'valid extruded solid');expected=(60*40-math.pi*25)*8;check(abs(window.result['stats']['volume']-expected)<.1,'rectangle and circular hole volume');report['initial_volume']=window.result['stats']['volume'];window.viewport.set_view('top');renderer=window.viewport.renderer;renderer.SetWorldPoint(12,10,8,1);renderer.WorldToDisplay();x,y,_=renderer.GetDisplayPoint();window.viewport.pick(int(x),int(y));check(bool(window.viewport.face and window.viewport.face[1]['planar']),'OpenGL triangle face picking');window.grab().save(str(path.with_name(path.stem+'-solid.png')));window.start_face_sketch();draw('circle',[(15,0),(18,0)]);e=window.editor;e.operation.setCurrentIndex(1);e.depth.setValue(4);e.finish()
    def pocket():
        check(not window.sketching,'face sketch completion');check(abs(window.result['stats']['volume']-(report['initial_volume']-math.pi*9*4))<.2,'face pocket removes exact volume');p=window.part();check(len(p['features'])==1 and p['features'][0]['support_feature']=='base','face and previous feature references');check(len(window.document.journal.data['entries'])==2,'timeline commits preserved');entry=window.document.journal.data['entries'][-1];check(bool(entry['context']['tool_actions']),'sketch tools stored in history');window.document.write(path.with_suffix('.cad.json'));project=read_project(path.with_suffix('.cad.json'));check(project.history is not None,'project history reload validation');export(project.design,path.with_suffix('.step'),'step');check(path.with_suffix('.step').stat().st_size>500,'STEP export');window.undo()
    def undone():
        check(len(window.part()['features'])==0,'undo restores prior feature state');window.redo()
    def redone():
        check(len(window.part()['features'])==1,'redo restores face feature');window.add_preset('robot_arm')
    def assembly():
        check(len(window.document.design['mates'])==4,'native assembly with four joints');check(window.result['stats']['valid'],'assembly geometry valid');window.viewport.set_view('iso');window.grab().save(str(path.with_name(path.stem+'-assembly.png')));window.undo()
    def finished():
        check(len(window.part()['features'])==1,'history returns from assembly to CAD');window.viewport.set_view('iso');render_frame('final');window.grab().save(str(path.with_name(path.stem+'-final.png')));report['success']=True;report['elapsed_seconds']=round(time.monotonic()-started,2);path.write_text(json.dumps(report,indent=2),encoding='utf-8');timer.stop();window.document.dirty=False;window.viewport.shutdown();app.exit(0)
    stages.extend([sketch,finish_sketch,solid,pocket,undone,redone,assembly,finished])
    def tick():
        try:
            if time.monotonic()-started>100:raise TimeoutError('native smoke workflow exceeded 100 seconds')
            if errors:raise AssertionError('; '.join(errors))
            if window.busy or window.editor.solving or window.editor.solve_timer.isActive():return
            index=state['index']
            if index>=len(stages):return
            state['index']+=1;stages[index]()
        except Exception:
            timer.stop();report.update(success=False,stage=state['index'],error=traceback.format_exc(),sketch_status=window.editor.status.text());path.write_text(json.dumps(report,indent=2),encoding='utf-8');window.document.dirty=False;app.exit(1)
    timer.timeout.connect(tick);timer.start()
