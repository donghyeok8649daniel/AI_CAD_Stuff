"""Self-closing actual native open of an owned copy; no OS input injection."""
import hashlib,json,time,traceback
from pathlib import Path


def run(app,window,output,input_path):
    from PySide6.QtCore import QTimer
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
    from vtkmodules.vtkIOImage import vtkPNGWriter
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from . import window as W
    output=Path(output);input_path=Path(input_path)
    assert input_path.parent==output.parent/'input' and not output.exists()
    original=hashlib.sha256(input_path.read_bytes()).hexdigest()
    started=time.perf_counter();state=dict(started=False,loaded=False,last_tick=started,render_times=[])
    report=dict(success=False,OS_input_actions=0,original_writes=0,opening={},checks=[],max_timer_gap_seconds=0)
    errors=[];window.show_error=errors.append
    real_open=W.load_project_preview
    def observed(*args,**kwargs):return real_open(*args,**kwargs,audit=report['opening'])
    W.load_project_preview=observed
    def check(value,name):
        if not value:raise AssertionError(name)
        report['checks'].append(name)
    timer=QTimer(window);timer.setInterval(100)
    def tick():
        now=time.perf_counter();report['max_timer_gap_seconds']=max(report['max_timer_gap_seconds'],now-state['last_tick']);state['last_tick']=now
        try:
            if not state['started']:
                state['started']=True;check(window.document.design is None,'blank private window did not restore user work')
                window.open_project(input_path);return
            if window.busy:return
            if not state['loaded']:
                check(not errors,'no native open errors: '+str(errors))
                check(window.result is not None and report['opening']['cache_hit'],'ordinary native open used the authenticated exact-file cache')
                report['open_seconds']=time.perf_counter()-started
                report.update(parts=len(window.viewport.meshes),history=len(window.document.journal.data['entries']),triangles=window.result['stats']['triangles'])
                check(len(window.viewport.actors)==len(window.document.design['parts'])==report['parts'],'all bodies installed in native viewport')
                check(window.result['stats']['valid'] and window.isVisible() and window.viewport.initialized,'valid visible native scene')
                state.update(loaded=True,loaded_at=now)
            if len(state['render_times'])<3:
                mark=time.perf_counter();camera=window.viewport.renderer.GetActiveCamera();camera.Azimuth(4)
                window.viewport.render();state['render_times'].append(time.perf_counter()-mark);return
            if now-state['loaded_at']<12:return
            timer.stop();capture=vtkWindowToImageFilter();capture.SetInput(window.viewport.window);capture.ReadFrontBufferOff();capture.Update()
            pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars());check(float(pixels.std())>3,'actual VTK framebuffer is nonempty')
            writer=vtkPNGWriter();writer.SetFileName(str(output.with_suffix('.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
            check(hashlib.sha256(input_path.read_bytes()).hexdigest()==original,'owned input unchanged')
            window.document.dirty=False;window.close();check(not window.isVisible(),'normal owned window close')
            report.update(success=True,total_seconds=time.perf_counter()-started,render_seconds=state['render_times'],original_sha256=original)
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');W.load_project_preview=real_open;app.exit(0)
        except Exception:
            timer.stop();report['error']=traceback.format_exc();output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            W.load_project_preview=real_open;window.document.dirty=False;window.close();app.exit(1)
    timer.timeout.connect(tick);timer.start()
