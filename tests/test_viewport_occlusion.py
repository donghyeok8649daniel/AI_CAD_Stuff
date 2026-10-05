"""Orbiting and face feedback must preserve opaque CAD depth ordering."""
from contextlib import contextmanager
import math

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

from cadstudio.native.viewport import CADViewport


def _box(identifier, color, minimum, maximum):
    # Closed mesh, with top face 1, built without invoking the shape kernel.
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    vertices = [[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],
                [x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]]
    triangles = [[0,2,1],[0,3,2],[4,5,6],[4,6,7],
                 [0,1,5],[0,5,4],[1,2,6],[1,6,5],
                 [2,3,7],[2,7,6],[3,0,4],[3,4,7]]
    return dict(id=identifier, name=identifier, color=color, vertices=vertices,
                triangles=triangles, triangle_faces=[0,0,1,1]+[0]*8,
                faces=[dict(index=0, planar=True),dict(index=1, planar=True)])


def _scene(meshes, sketches=()):
    points = np.concatenate([np.asarray(m['vertices']) for m in meshes])
    minimum, maximum = points.min(axis=0), points.max(axis=0)
    return dict(meshes=meshes, sketches=list(sketches), stats=dict(
        min=minimum.tolist(), max=maximum.tolist(),
        bounds=(maximum-minimum).tolist(), parts=len(meshes), volume=1,
        assembly_constraints=dict(mates=0), collisions=[]))


@contextmanager
def _viewport():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    _APP.setQuitOnLastWindowClosed(False)
    view = CADViewport()
    view.resize(900,700)
    view.show()
    QTest.qWait(100)
    view.show_axes(False)
    view.show_grid(False)
    view.show_edges = False
    try:
        yield view
    finally:
        view.shutdown()
        view.close()
        view.deleteLater()
        _APP.processEvents()


def _capture(view):
    view.window.Render()
    capture = vtkWindowToImageFilter()
    capture.SetInput(view.window)
    capture.ReadFrontBufferOff()
    capture.Update()
    pixels = capture.GetOutput()
    width,height,_ = pixels.GetDimensions()
    return vtk_to_numpy(pixels.GetPointData().GetScalars()).reshape(height,width,-1)[:,:,:3].copy()


def _patch(view, image, point=(0,0,0)):
    view.renderer.SetWorldPoint(*point,1)
    view.renderer.WorldToDisplay()
    x,y,_ = view.renderer.GetDisplayPoint()
    x,y = round(x),round(y)
    patch = image[y-2:y+3,x-2:x+3]
    assert patch.shape == (5,5,3)
    return patch.astype(int)


def _orbit(view, degrees):
    camera = view.renderer.GetActiveCamera()
    angle = math.radians(degrees)
    camera.ParallelProjectionOn()
    camera.SetPosition(200*math.sin(angle),0,200*math.cos(angle))
    camera.SetFocalPoint(0,0,0)
    camera.SetViewUp(0,1,0)
    camera.SetParallelScale(60)
    view.renderer.ResetCameraClippingRange()


def _covered_faces():
    return [_box('cover','#00CC00',(-50,-50,.03),(50,50,.06)),
            _box('behind','#CC0000',(-50,-50,-.1),(50,50,0))]


def test_selected_hidden_face_does_not_show_through_cover_during_orbit():
    with _viewport() as view:
        view.load(_scene(_covered_faces()))
        for angle in (0,60,80,85):
            view.clear_face()
            _orbit(view,angle)
            before = _patch(view,_capture(view))
            assert before[:,:,1].mean() > before[:,:,0].mean()+40
            view.highlight_face('behind',1)
            after = _patch(view,_capture(view))
            assert np.max(np.abs(after-before)) <= 3, (angle,before[2,2],after[2,2])
        # Selection feedback must still appear on an actually visible face.
        view.clear_face()
        view.highlight_face('cover',1)
        visible = _patch(view,_capture(view))
        assert np.max(np.abs(visible-before)) > 10


def test_hidden_sketch_profile_does_not_show_through_cover_at_grazing_angle():
    meshes = _covered_faces()
    region = dict(index=0,vertices=[[-48,-48,0],[48,-48,0],[48,48,0],[-48,48,0]],
                  triangles=[[0,1,2],[0,2,3]])
    sketch = dict(id='hidden-sketch',lines=[],regions=[region])
    with _viewport() as view:
        view.load(_scene(meshes))
        _orbit(view,80)
        before = _patch(view,_capture(view))
        view.load(_scene(meshes,[sketch]),fit=False)
        # Exercise the actual brighter hover profile, which must remain behind
        # opaque solids just as the unhovered profile does.
        for actor in view.profile_actors:
            actor.GetProperty().SetOpacity(.4)
        after = _patch(view,_capture(view))
        assert np.max(np.abs(after-before)) <= 3, (before[2,2],after[2,2])


def test_focus_small_part_keeps_front_assembly_occlusion_and_zoom():
    meshes = [_box('small','#CC0000',(-2.5,-2.5,-2.5),(2.5,2.5,2.5)),
              _box('front','#00CC00',(20,-50,-50),(30,50,50))]
    with _viewport() as view:
        view.load(_scene(meshes))
        camera = view.renderer.GetActiveCamera()
        camera.ParallelProjectionOn()
        camera.SetPosition(200,0,0)
        camera.SetFocalPoint(0,0,0)
        camera.SetViewUp(0,0,1)
        # This is the UI's focus-on-one-part operation. ResetCamera puts the
        # eye near the small part while the rest of the assembly stays visible.
        view.renderer.ResetCamera(view.actors['small'][0].GetBounds())
        view.renderer.ResetCameraClippingRange()
        scale = camera.GetParallelScale()
        focal = camera.GetFocalPoint()
        color = _patch(view,_capture(view)).mean(axis=(0,1))
        assert color[1] > color[0]+40, color
        assert camera.GetParallelScale() == scale
        assert camera.GetFocalPoint() == focal
        # Rebuilding without fitting must not leave the old near/far range
        # cutting away the closest face, or reset the user's viewport framing.
        view.load(_scene(meshes),fit=False)
        color = _patch(view,_capture(view)).mean(axis=(0,1))
        assert color[1] > color[0]+40, color
        assert camera.GetParallelScale() == scale
        assert camera.GetFocalPoint() == focal


def _check(ok,title):
    assert ok,title


def test_full_orbit_and_geometry_rebuild_preserve_model_projection():
    from cadstudio.native.occlusion_smoke2191 import framing_checks
    with _viewport() as view:
        framing_checks(view,_check)


def test_extrusion_overlay_depth_includes_drag_handle():
    from cadstudio.native.occlusion_smoke2191 import overlay_checks
    with _viewport() as view:
        overlay_checks(view,_check)
