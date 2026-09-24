"""Screen-space triangle/rectangle selection, including holes and occluded parts."""
import numpy as np


def rectangle_hit(points,triangles,lo,hi,contain):
    if contain:return bool(np.all((points>=lo)&(points<=hi)))
    tri=points[np.asarray(triangles).reshape(-1,3)]
    tri=tri[np.all(tri.max(axis=1)>=lo,axis=1)&np.all(tri.min(axis=1)<=hi,axis=1)]
    if not len(tri):return False
    # Separating axis theorem: rectangle X/Y already checked, then triangle normals.
    edges=np.roll(tri,-1,axis=1)-tri;axes=np.stack([-edges[:,:,1],edges[:,:,0]],axis=2)
    projected=np.einsum('nvi,nai->nav',tri,axes)
    center=(lo+hi)/2;radius=(hi-lo)/2
    middle=np.einsum('nai,i->na',axes,center);extent=np.einsum('nai,i->na',np.abs(axes),radius)
    return bool(np.any(np.all((projected.max(axis=2)>=middle-extent)&(projected.min(axis=2)<=middle+extent),axis=1)))


def projected_selection(meshes,hidden,matrix,size,start,end):
    lo=np.minimum(start,end);hi=np.maximum(start,end);contain=end[0]>=start[0];selected=[]
    for identifier,mesh in meshes.items():
        if identifier in hidden:continue
        vertices=np.asarray(mesh['vertices']).reshape(-1,3);clip=np.c_[vertices,np.ones(len(vertices))]@matrix.T
        if not len(clip) or np.any(clip[:,3]<=0):continue
        ndc=clip[:,:3]/clip[:,3,None]
        if np.all(ndc[:,2]<0) or np.all(ndc[:,2]>1):continue
        points=(ndc[:,:2]+1)*np.asarray(size)/2
        if rectangle_hit(points,mesh['triangles'],lo,hi,contain):selected.append(identifier)
    return selected
