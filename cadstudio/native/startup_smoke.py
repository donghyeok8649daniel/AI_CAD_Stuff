"""Exercise the normal event loop, real 3D frames and clean shutdown."""
import json
import os
from pathlib import Path
import time
import traceback


def run(app, window, path):
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
    from vtkmodules.vtkIOImage import vtkPNGWriter
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from ..catalog import preset
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    report={'checks':[],'renderer':os.getenv('CADSTUDIO_RENDERER'),'frames':0}
    started=time.monotonic();state={'built':False,'stage':0};errors=[]
    window.show_error=lambda message:errors.append(message)
    heartbeat=QTimer(window);heartbeat.setInterval(100)
    def check(value,name):
        if not value:raise AssertionError(name)
        report['checks'].append(name)
    def tick():
        try:
            check_once=state['stage']==0
            if check_once:
                check(window.isVisible() and window.viewport.initialized,'ordinary blank startup initializes a visible native viewport')
                check(window.document.design is None,'startup does not restore or overwrite the previous project')
                state['stage']=1
            elapsed=time.monotonic()-started
            camera=window.viewport.renderer.GetActiveCamera();camera.Azimuth(1)
            window.viewport.window.Render();report['frames']+=1
            if elapsed>3 and not state['built']:
                state['built']=True;window.apply_design(preset('robot_arm').model_dump(),'Startup test assembly',fit=True)
            if elapsed<15 or window.busy:return
            heartbeat.stop()
            check(not errors and window.result and window.result['stats']['valid'],'real robot assembly builds and renders after startup')
            check(report['frames']>=20,'native event loop remains responsive through repeated orbit rendering')
            for size in [(820,560),(1280,800)]:window.resize(*size);QTest.qWait(100);window.viewport.window.Render()
            capture=vtkWindowToImageFilter();capture.SetInput(window.viewport.window);capture.ReadFrontBufferOff();capture.Update()
            pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())
            check(float(pixels.std())>8,'rendered assembly framebuffer contains visible geometry')
            writer=vtkPNGWriter();writer.SetFileName(str(path.with_suffix('.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
            project=path.with_suffix('.cad.json');window.document.write(project)
            from .document import read_project
            check(read_project(project).design is not None,'render fallback preserves normal native project saving')
            window.document.dirty=False;window.close();check(not window.isVisible(),'normal window close shuts down the render context')
            report['seconds']=round(time.monotonic()-started,2);path.write_text(json.dumps(report,indent=2),encoding='utf-8');app.exit(0)
        except Exception:
            heartbeat.stop();report['error']=traceback.format_exc();path.write_text(json.dumps(report,indent=2),encoding='utf-8');app.exit(1)
    heartbeat.timeout.connect(tick);heartbeat.start()
