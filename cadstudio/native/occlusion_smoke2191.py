"""Real native pixel/depth checks for orbit, focus and selection overlays."""
import itertools
import json
import math
import traceback

import numpy as np
from PySide6.QtTest import QTest
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter


def _box(identifier, color, minimum, maximum):
    x0,y0,z0 = minimum
    x1,y1,z1 = maximum
    vertices = [[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],
                [x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]]
    triangles = [[0,2,1],[0,3,2],[4,5,6],[4,6,7],
                 [0,1,5],[0,5,4],[1,2,6],[1,6,5],
                 [2,3,7],[2,7,6],[3,0,4],[3,4,7]]
    return dict(id=identifier,name=identifier,color=color,vertices=vertices,
                triangles=triangles,triangle_faces=[0,0,1,1]+[0]*8,
                faces=[dict(index=0,planar=True),dict(index=1,planar=True)])


def _scene(meshes, sketches=()):
    points = np.concatenate([np.asarray(m['vertices']) for m in meshes])
    minimum,maximum = points.min(axis=0),points.max(axis=0)
    return dict(meshes=meshes,sketches=list(sketches),stats=dict(
        min=minimum.tolist(),max=maximum.tolist(),
        bounds=(maximum-minimum).tolist(),parts=len(meshes),volume=1,
        assembly_constraints=dict(mates=0),collisions=[]))


def _capture(view, png=None):
    view.window.Render()
    capture = vtkWindowToImageFilter()
    capture.SetInput(view.window)
    capture.ReadFrontBufferOff()
    capture.Update()
    if png is not None:
        from vtkmodules.vtkIOImage import vtkPNGWriter
        writer=vtkPNGWriter();writer.SetFileName(str(png))
        writer.SetInputConnection(capture.GetOutputPort());writer.Write()
    pixels = capture.GetOutput()
    width,height,_ = pixels.GetDimensions()
    return vtk_to_numpy(pixels.GetPointData().GetScalars()).reshape(height,width,-1)[:,:,:3].copy()


def _display(view, point):
    view.renderer.SetWorldPoint(*point,1)
    view.renderer.WorldToDisplay()
    return np.asarray(view.renderer.GetDisplayPoint())


def _patch(view, image, point=(0,0,0)):
    x,y,_ = _display(view,point)
    x,y = round(x),round(y)
    patch = image[y-2:y+3,x-2:x+3]
    assert patch.shape==(5,5,3), 'Interior pixel patch is inside the render image'
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


def hidden_face_checks(view, check):
    view.load(_scene(_covered_faces()))
    for angle in (0,60,80,85):
        view.clear_face();_orbit(view,angle)
        before = _patch(view,_capture(view))
        check(before[:,:,1].mean()>before[:,:,0].mean()+40,
              f'opaque cover is the nearest face at {angle} degrees')
        view.highlight_face('behind',1)
        after = _patch(view,_capture(view))
        check(np.max(np.abs(after-before))<=3,
              f'hidden selected face does not bleed through at {angle} degrees: {before[2,2]} / {after[2,2]}')
    view.clear_face();view.highlight_face('cover',1)
    visible = _patch(view,_capture(view))
    check(np.max(np.abs(visible-before))>10,'actually visible coplanar selection feedback remains visible')


def profile_checks(view, check):
    meshes = _covered_faces()
    region = dict(index=0,vertices=[[-48,-48,0],[48,-48,0],[48,48,0],[-48,48,0]],
                  triangles=[[0,1,2],[0,2,3]])
    sketch = dict(id='hidden-sketch',lines=[],regions=[region])
    view.load(_scene(meshes));_orbit(view,80)
    before = _patch(view,_capture(view))
    view.load(_scene(meshes,[sketch]),fit=False)
    for actor in view.profile_actors:
        actor.GetProperty().SetOpacity(.4)
    after = _patch(view,_capture(view))
    check(np.max(np.abs(after-before))<=3,
          f'hidden hover profile is occluded at a grazing angle: {before[2,2]} / {after[2,2]}')


def focus_checks(view, check):
    meshes = [_box('small','#CC0000',(-2.5,-2.5,-2.5),(2.5,2.5,2.5)),
              _box('front','#00CC00',(20,-50,-50),(30,50,50))]
    view.load(_scene(meshes))
    camera = view.renderer.GetActiveCamera()
    camera.ParallelProjectionOn();camera.SetPosition(200,0,0)
    camera.SetFocalPoint(0,0,0);camera.SetViewUp(0,0,1)
    view.renderer.ResetCamera(view.actors['small'][0].GetBounds())
    view.renderer.ResetCameraClippingRange()
    scale,focal = camera.GetParallelScale(),camera.GetFocalPoint()
    color = _patch(view,_capture(view)).mean(axis=(0,1))
    check(color[1]>color[0]+40,f'focusing a small part preserves opaque front assembly: {color}')
    check(camera.GetParallelScale()==scale and camera.GetFocalPoint()==focal,
          'focus depth correction preserves requested zoom and focal point')
    view.load(_scene(meshes),fit=False)
    color = _patch(view,_capture(view)).mean(axis=(0,1))
    check(color[1]>color[0]+40,f'fit=False rebuild preserves front assembly depth: {color}')
    check(camera.GetParallelScale()==scale and camera.GetFocalPoint()==focal,
          'fit=False rebuild preserves requested zoom and focal point')


def framing_checks(view, check):
    meshes = [_box('small','#CC0000',(-2.5,-2.5,-2.5),(2.5,2.5,2.5)),
              _box('front','#00CC00',(20,-50,-50),(30,50,50))]
    view.load(_scene(meshes));camera=view.renderer.GetActiveCamera()
    camera.SetPosition(200,0,0);camera.SetFocalPoint(0,0,0);camera.SetViewUp(0,0,1)
    view.renderer.ResetCamera(view.actors['small'][0].GetBounds())
    scale,focal = camera.GetParallelScale(),camera.GetFocalPoint()
    for angle in range(0,361,15):
        distance=camera.GetDistance();radians=math.radians(angle)
        camera.SetPosition(distance*math.cos(radians),distance*math.sin(radians),0)
        view.window.Render()
        depths=[_display(view,p)[2] for mesh in meshes for p in mesh['vertices']]
        check(min(depths)>=0 and max(depths)<=1,
              f'all opaque vertices remain between clipping planes during {angle}-degree orbit')
    check(camera.GetParallelScale()==scale and camera.GetFocalPoint()==focal,
          '360-degree focus orbit preserves zoom and focal point')
    points=((0,0,0),(0,1,0),(0,0,1))
    before=np.asarray([_display(view,p)[:2] for p in points])
    changed=[dict(mesh,color='#3355AA') for mesh in meshes]
    view.update_metadata(_scene(changed),fit=False)
    after=np.asarray([_display(view,p)[:2] for p in points])
    check(np.max(np.abs(after-before))<1e-6,'metadata edit preserves projected model positions')
    # A newly rebuilt/moved body may be well beyond the old camera eye.
    moved=[meshes[0],_box('front','#00CC00',(700,-50,-50),(710,50,50))]
    view.load(_scene(moved),fit=False);view.window.Render()
    depths=[_display(view,p)[2] for mesh in moved for p in mesh['vertices']]
    check(min(depths)>=0 and max(depths)<=1,'fit=False body movement beyond old eye remains inside depth range')
    check(camera.GetParallelScale()==scale and camera.GetFocalPoint()==focal,
          'body movement beyond old eye preserves zoom and focal point')
    after=np.asarray([_display(view,p)[:2] for p in points])
    check(np.max(np.abs(after-before))<1e-6,'depth correction preserves screen coordinates after body movement')


def overlay_checks(view, check):
    from .interaction import ExtrusionHandle
    view.load(_scene([_box('solid','#00CC00',(-5,-5,-5),(5,5,5))]))
    _orbit(view,80)
    camera=view.renderer.GetActiveCamera();camera.SetParallelScale(15)
    # Deliberately point a long drag handle towards the eye: overlay controls
    # use the same camera and must be included in depth bounds.
    direction=-np.asarray(camera.GetDirectionOfProjection())
    handle=ExtrusionHandle(view,(0,0,0),direction,[[[-2,-2,0],[2,-2,0],[2,2,0],[-2,2,0],[-2,-2,0]]],lambda value:None)
    try:
        scale,focal=camera.GetParallelScale(),camera.GetFocalPoint()
        handle.update(600);view.window.Render()
        depths=[]
        for actor in handle.pickable:
            bounds=actor.GetBounds()
            for corner in itertools.product(*[(bounds[i],bounds[i+1]) for i in (0,2,4)]):
                depths.append(_display(view,corner)[2])
        check(min(depths)>=0 and max(depths)<=1,'extrusion handle tip and shaft remain inside shared camera depth range')
        check(camera.GetParallelScale()==scale and camera.GetFocalPoint()==focal,
              'overlay depth correction preserves extrusion preview framing')
        image=_capture(view);patch=_patch(view,image,handle.center+handle.normal*600)
        check(patch[:,:,0].mean()>120 and patch[:,:,1].mean()>70,
              'long extrusion overlay is visible as actual native pixels')
    finally:
        handle.close();view.window.Render()


def run(app, window, path):
    path.parent.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    def check(ok,title):
        if not ok:raise AssertionError(title)
        checks.append(title)
    try:
        app.setQuitOnLastWindowClosed(False)
        window.show_error=lambda message:errors.append(message)
        window.resize(1280,900);window.activateWindow();app.processEvents();QTest.qWait(100)
        view=window.viewport;view.show_axes(False);view.show_grid(False);view.show_edges=False
        for case in (hidden_face_checks,profile_checks,focus_checks,framing_checks,overlay_checks):
            case(view,check)
            _capture(view,path.with_name(case.__name__+'-viewport.png'))
        check(not errors,'native depth checks complete without UI errors')
        path.write_text(json.dumps(dict(success=True,checks=checks),ensure_ascii=False,indent=2),encoding='utf-8')
        window.document.dirty=False;window.close();app.quit()
    except Exception:
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc(),ui_errors=errors),ensure_ascii=False,indent=2),encoding='utf-8')
        window.document.dirty=False;window.close();app.exit(1)
