"""Editable, exportable revolute hardware made from ordinary CAD parts."""
from copy import deepcopy
from uuid import uuid4
import warnings

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.spatial.transform import Rotation

from .constraints import anchors, transform_matrix
from .models import Design, Part


class RevoluteHardware(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    shaft_diameter: float = Field(default=12, ge=2, le=200)
    clearance: float = Field(default=.2, ge=.01, le=2)
    seat_clearance: float = Field(default=.2, ge=0, le=2)
    assembly_clearance: float = Field(default=.2, ge=0, le=2)
    length: float = Field(default=30, ge=10, le=400)
    bushing_wall: float = Field(default=2, ge=.5, le=30)
    housing_wall: float = Field(default=4, ge=1, le=50)
    flange_thickness: float = Field(default=6, ge=2, le=50)
    bolt_diameter: float = Field(default=5, ge=1, le=20)
    axial_gap: float = Field(default=.2, ge=.02, le=5)


def _pose(position, rotation):
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Gimbal lock detected.*')
        angles=Rotation.from_matrix(rotation).as_euler('xyz', degrees=True)
    return dict(zip(('x','y','z','rx','ry','rz'),map(float,[*position,*angles])))


def _mount_flange(width, thickness, bore, bolt):
    # A polygon with five analytic holes stays a normal editable sketch solid.
    pitch=width/2-bolt-1
    return dict(kind='extrusion',thickness=thickness,sketch_mode='polygon',
                points=[dict(x=x,y=y) for x,y in [(-width/2,-width/2),(width/2,-width/2),(width/2,width/2),(-width/2,width/2)]],
                holes=[dict(x=0,y=0,diameter=bore)]+[dict(x=x,y=y,diameter=bolt) for x in (-pitch,pitch) for y in (-pitch,pitch)])


def add_revolute_hardware(raw=None, dimensions=None, *, mate_id=None, origin=(0,0,0), prefix=None):
    """Append a seven-part physical joint; optionally follow an existing joint.

    Existing host geometry is not cut automatically. Interference against hosts
    must be reviewed in the preview. No existing mate/feature is rewritten.
    """
    spec=RevoluteHardware.model_validate(dimensions or {})
    data=Design.model_validate(deepcopy(raw or dict(name='회전 관절 구조',mode='robot',parts=[],mates=[]))).model_dump()
    prefix=prefix or 'joint-'+uuid4().hex[:8]+'-'
    root=np.asarray(origin,dtype=float);basis=np.eye(3);existing=None
    if root.shape!=(3,) or not np.isfinite(root).all():raise ValueError('배치 위치는 유한한 XYZ 값이어야 합니다.')
    original_parts={p.id:p for p in Design.model_validate(data).parts}
    if mate_id:
        existing=next((m for m in data['mates'] if m['id']==mate_id),None)
        if not existing or existing['kind']!='revolute':raise ValueError('실제 회전 구조를 넣을 회전 관절을 선택하세요.')
        parent=original_parts[existing['parent']];rotation=transform_matrix(parent.transform)
        binding=next((f for f in data.get('joint_frames',[]) if f['mate_id']==mate_id),None)
        if binding:
            frame=binding['parent'];normal=np.array(frame['normal']);x=np.array(frame['x_direction'])
            basis=rotation@np.column_stack((x,np.cross(normal,x),normal));anchor=np.array(frame['origin'])
        else:basis=rotation;anchor=np.array(anchors(parent.geometry)[existing['parent_anchor']])
        root=np.array([parent.transform.x,parent.transform.y,parent.transform.z])+rotation@anchor+basis@np.array([existing[k] for k in ('x','y','z')])
    d=spec.shaft_diameter;inside=d+spec.clearance;bush=inside+2*spec.bushing_wall;seat=bush+spec.seat_clearance;outside=seat+2*spec.housing_wall
    width=outside+4*spec.bolt_diameter+8;output_width=max(d+4*spec.bolt_diameter+8,outside+4)
    t=spec.flange_thickness;gap=spec.axial_gap;collar=4.;bottom=-t-gap-collar;top=spec.length+gap+t
    tube=lambda diameter,height,bore=0:dict(kind='cylinder',diameter=diameter,height=height,bore_diameter=bore)
    rows=[('mount','고정 장착 플랜지',_mount_flange(width,t,seat,spec.bolt_diameter),-t,'#657e91'),
          ('housing','관절 하우징',tube(outside,spec.length,seat),0,'#6ba8bc'),
          ('bush-a','하부 부시',tube(bush,spec.length/3,inside),0,'#c6a15d'),
          ('bush-b','상부 부시',tube(bush,spec.length/3,inside),spec.length*2/3,'#c6a15d'),
          ('shaft','회전 축',tube(d,top-bottom),bottom,'#cad2dc'),
          ('output','출력 장착 플랜지',_mount_flange(output_width,t,d+spec.assembly_clearance,spec.bolt_diameter),spec.length+gap,'#70c8b4'),
          ('collar','축 고정 칼라',tube(d+6,collar,d+spec.assembly_clearance),bottom,'#b8c3cd')]
    parts=[]
    from .part_roles import new_part_style
    for key,name,geometry,z,color in rows:
        parts.append(Part(id=prefix+key,name=name,geometry=geometry,**new_part_style(geometry['kind'],'structure' if key in ('mount','housing') else 'transmission'),
                          fixed=key=='mount' and not existing,transform=_pose(root+basis@np.array([0,0,z]),basis)).model_dump())
    by_id={p['id']:p for p in parts}
    if any(p['id'] in original_parts for p in parts):raise ValueError('관절 구조의 부품 ID가 중복됩니다.')
    def rigid(identifier,parent_id,child_id):
        parent=original_parts.get(parent_id) or Part.model_validate(by_id[parent_id]);child=Part.model_validate(by_id[child_id])
        rotation=transform_matrix(parent.transform);pos=np.array([parent.transform.x,parent.transform.y,parent.transform.z]);cp=np.array([child.transform.x,child.transform.y,child.transform.z])
        return dict(id=prefix+identifier,kind='rigid',parent=parent_id,child=child_id,**_pose(rotation.T@(cp-pos),rotation.T@transform_matrix(child.transform)))
    mates=[rigid('housing-mount',prefix+'mount',prefix+'housing'),
           rigid('bush-a-seat',prefix+'housing',prefix+'bush-a'),rigid('bush-b-seat',prefix+'housing',prefix+'bush-b'),
           rigid('output-shaft',prefix+'shaft',prefix+'output'),rigid('collar-shaft',prefix+'shaft',prefix+'collar')]
    if existing:
        mates.extend([rigid('host-stator',existing['parent'],prefix+'mount'),rigid('host-rotor',existing['child'],prefix+'shaft')])
    else:mates.append(dict(id=prefix+'rotation',kind='revolute',parent=prefix+'housing',child=prefix+'shaft',z=bottom,limits={'rz':[-180,180]}))
    data['parts'].extend(parts);data['mates'].extend(mates)
    data.setdefault('part_groups',[]).append(dict(id=prefix+'hardware',name='회전 관절 구조 · 7개 부품',part_ids=[p['id'] for p in parts]))
    from .print_profile import link_print_parts
    ids=[p['id'] for p in parts]
    return link_print_parts(data,ids),ids
