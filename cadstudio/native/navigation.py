"""Cursor anchored camera zoom, also usable without a Qt window in tests."""
import math
import numpy as np


def unproject(renderer, x, y, depth):
    renderer.SetDisplayPoint(x,y,depth);renderer.DisplayToWorld()
    p=np.asarray(renderer.GetWorldPoint(),dtype=float)
    if not np.isfinite(p).all() or abs(p[3])<1e-12:raise ValueError('Invalid camera projection')
    return p[:3]/p[3]


def zoom_camera(renderer, position, factor, anchor=None):
    if not math.isfinite(factor) or factor<=0:return
    camera=renderer.GetActiveCamera();x,y=position
    if anchor is None:
        renderer.SetWorldPoint(*camera.GetFocalPoint(),1);renderer.WorldToDisplay()
        anchor=unproject(renderer,x,y,renderer.GetDisplayPoint()[2])
    anchor=np.asarray(anchor,dtype=float)
    if camera.GetParallelProjection():
        camera.SetParallelScale(max(.002,min(1e7,camera.GetParallelScale()/factor)))
    else:
        distance=camera.GetDistance();new_distance=max(.002,min(1e7,distance/factor))
        if distance<=0:return
        camera.Dolly(distance/new_distance)
    renderer.SetWorldPoint(*anchor,1);renderer.WorldToDisplay()
    delta=anchor-unproject(renderer,x,y,renderer.GetDisplayPoint()[2])
    camera.SetPosition(*(np.asarray(camera.GetPosition())+delta))
    camera.SetFocalPoint(*(np.asarray(camera.GetFocalPoint())+delta))
    renderer.ResetCameraClippingRange()
