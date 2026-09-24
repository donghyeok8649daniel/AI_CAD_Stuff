"""One coordinate frame for sketch display, projection and solid creation."""
import warnings
import numpy as np
from scipy.spatial.transform import Rotation


def base_rotation(plane):
    if plane=='XY':return np.eye(3)
    if plane=='XZ':return np.array([[1.,0,0],[0,0,-1],[0,1,0]])
    if plane=='YZ':return np.array([[0.,0,1],[1,0,0],[0,1,0]])
    raise ValueError('기준 평면은 XY, XZ, YZ 중에서 선택하세요.')


def work_plane_frame(plane):
    from .models import WorkPlane
    from .constraints import transform_matrix
    plane=WorkPlane.model_validate(plane);base=base_rotation(plane.plane);t=plane.placement
    origin=np.array([t.x,t.y,t.z])+base[:,2]*plane.offset
    matrix=base@transform_matrix(t)
    if np.any(np.abs(origin)>5000):raise ValueError('작업 평면 원점은 ±5,000 mm 범위여야 합니다.')
    return origin,matrix[:,0],matrix[:,1]


def context_frame(context,design=None):
    from .constraints import transform_matrix
    from .models import Transform
    if hasattr(context,'model_dump'):context=context.model_dump()
    face=context.get('face')
    if face:
        origin=np.asarray(face['origin'],dtype=float);x=np.asarray(face['x_direction'],dtype=float)
        y=np.cross(np.asarray(face['normal'],dtype=float),x)
    elif context.get('work_plane'):
        origin,x,y=work_plane_frame(context['work_plane'])
    else:
        origin=np.zeros(3);base=base_rotation(context.get('plane','XY'));x,y=base[:,0],base[:,1]
    parts=design.get('parts',[]) if isinstance(design,dict) else design.parts if design is not None else []
    parent=next((p for p in parts if (p['id'] if isinstance(p,dict) else p.id)==context.get('part_id')),None)
    if parent is not None:
        t=Transform.model_validate(parent['transform']) if isinstance(parent,dict) else parent.transform
        r=transform_matrix(t);origin=r@origin+[t.x,t.y,t.z];x=r@x;y=r@y
    return origin,x,y


def frame_transform(origin,x,y):
    from .models import Transform
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='Gimbal lock detected.*')
        angles=Rotation.from_matrix(np.column_stack((x,y,np.cross(x,y)))).as_euler('xyz',degrees=True)
    return Transform.model_validate(dict(zip(('x','y','z','rx','ry','rz'),map(float,[*origin,*angles])))).model_dump()


def extrusion_transform(context):
    if context.get('work_plane'):return frame_transform(*context_frame(context))
    plane=context.get('plane','XY')
    return {'rx':90} if plane=='XZ' else {'rx':90,'rz':90} if plane=='YZ' else {}
