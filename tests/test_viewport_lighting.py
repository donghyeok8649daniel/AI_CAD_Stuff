"""A hollow part must not look like a filled block in the default CAD view."""
import json
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
from cadstudio.models import DraftRequest
from cadstudio.kernel import preview
from cadstudio.native.cad_tools import execute_plan
from cadstudio.native.viewport import CADViewport


def test_default_isometric_view_distinguishes_cavity_floor_and_walls():
    global _APP
    _APP=QApplication.instance() or QApplication([])
    _APP.setQuitOnLastWindowClosed(False)
    plan=dict(summary='open box',actions=[
        dict(tool='create',target='p',args=dict(name='p',color='#2266CC',geometry=dict(kind='plate',length=80,width=50,thickness=25))),
        dict(tool='shell',target='p',args=dict(thickness=2,open_faces=['+Z']))])
    design=execute_plan(json.dumps(plan),DraftRequest(prompt='open box')).design
    view=CADViewport();view.resize(900,700);view.show()
    try:
        QTest.qWait(100);view.load(preview(design));QTest.qWait(100);view.window.Render()
        capture=vtkWindowToImageFilter();capture.SetInput(view.window);capture.ReadFrontBufferOff();capture.Update()
        pixels=capture.GetOutput();colors=[]
        # Interior floor and two inward-facing walls, safely away from edges.
        for point in ((0,0,2),(-38,0,15),(0,23,15)):
            view.renderer.SetWorldPoint(*point,1);view.renderer.WorldToDisplay()
            x,y,_=view.renderer.GetDisplayPoint();x,y=round(x),round(y)
            colors.append([np.mean([pixels.GetScalarComponentAsDouble(x+dx,y+dy,0,c)
                for dx in (-1,0,1) for dy in (-1,0,1)]) for c in range(3)])
        assert np.max(np.ptp(np.array(colors),axis=0))>25,colors
    finally:
        view.shutdown();view.close();view.deleteLater();_APP.processEvents()
