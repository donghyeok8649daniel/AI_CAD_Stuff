"""Dimension-driven seats and mounting holes built as editable sketch features."""
from copy import deepcopy
from uuid import uuid4
from typing import Literal
import cadquery as cq
from pydantic import Field,model_validator
from .models import StrictModel,Design,Extrusion
from .kernel import KERNEL_LOCK,local_shape,face_frame
from .topology import face_reference


class MountSpec(StrictModel):
    shape: Literal['rectangle','circle']='rectangle'
    pocket: bool=True
    width: float=Field(default=40,ge=.1,le=1000)
    length: float=Field(default=60,ge=.1,le=1000)
    depth: float=Field(default=3,ge=.01,le=1000)
    clearance: float=Field(default=.2,ge=0,le=5)
    x: float=Field(default=0,ge=-2000,le=2000)
    y: float=Field(default=0,ge=-2000,le=2000)
    bolts: bool=True
    spacing_x: float=Field(default=32,ge=.1,le=1000)
    spacing_y: float=Field(default=52,ge=.1,le=1000)
    bolt_diameter: float=Field(default=3,ge=.1,le=100)
    wire: bool=False
    wire_diameter: float=Field(default=6,ge=.1,le=100)
    wire_x: float=Field(default=0,ge=-2000,le=2000)
    wire_y: float=Field(default=0,ge=-2000,le=2000)
    @model_validator(mode='after')
    def nonempty(self):
        if not (self.pocket or self.bolts or self.wire):raise ValueError('자리 파기, 체결 구멍, 전선 구멍 중 하나를 선택하세요.')
        return self


def add_electronics_mount(raw,part_id,face_index,spec,prefix=None):
    spec=MountSpec.model_validate(spec);data=Design.model_validate(deepcopy(raw)).model_dump();prefix=prefix or 'mount-'+uuid4().hex[:8]
    with KERNEL_LOCK:
        d=Design.model_validate(data);part=next((p for p in d.parts if p.id==part_id),None)
        if part is None or part.source_part_id:raise ValueError('독립 부품의 평면을 선택하세요.')
        shape=local_shape(d,part);faces=shape.Faces()
        if face_index<0 or face_index>=len(faces):raise ValueError('장착 면을 다시 선택하세요.')
        original=face_frame(faces[face_index]);host=next(p for p in data['parts'] if p['id']==part_id);created=[]
        operations=[]
        if spec.pocket:operations.append(('seat','전장부품 자리',spec.x,spec.y,spec.width+spec.clearance,spec.length+spec.clearance,False))
        if spec.bolts:
            for i,(x,y) in enumerate([(x,y) for x in (-spec.spacing_x/2,spec.spacing_x/2) for y in (-spec.spacing_y/2,spec.spacing_y/2)]):operations.append(('bolt'+str(i),'체결 구멍',spec.x+x,spec.y+y,spec.bolt_diameter,0,True))
        if spec.wire:operations.append(('wire','전선 통과 구멍',spec.x+spec.wire_x,spec.y+spec.wire_y,spec.wire_diameter,0,True))
        for key,title,x,y,width,length,through in operations:
            faces=shape.Faces();candidates=[(i,f) for i,f in enumerate(faces) if f.geomType()=='PLANE' and (f.normalAt()-original.zDir).Length<1e-6 and abs((f.Center()-original.origin).dot(original.zDir))<1e-5]
            if not candidates:raise ValueError('장착 기준 면이 사라졌습니다. 자리 깊이와 크기를 줄이세요.')
            index,face=max(candidates,key=lambda row:row[1].Area());plane=face_frame(face)
            center=plane.toLocalCoords(original.toWorldCoords(cq.Vector(x,y,0)))
            circle=through or spec.shape=='circle'
            if circle:g=Extrusion(sketch_mode='entities',thickness=spec.depth,entities=[dict(id='circle',kind='circle',center=dict(x=center.x,y=center.y),radius=width/2)])
            else:g=Extrusion(sketch_mode='polygon',thickness=spec.depth,points=[dict(x=center.x+dx,y=center.y+dy) for dx,dy in [(-width/2,-length/2),(width/2,-length/2),(width/2,length/2),(-width/2,length/2)]])
            if not through:
                tool=cq.Workplane(plane).center(center.x,center.y)
                tool=(tool.circle(width/2) if circle else tool.rect(width,length)).extrude(-spec.depth).val()
                if shape.intersect(tool).Volume()<tool.Volume()*(1-1e-6):raise ValueError('부품 자리의 전체 크기·깊이가 재료 안에 들어가야 합니다. 위치·크기·깊이를 줄이세요.')
            identifier=prefix+'-'+key
            feature=dict(id=identifier,name=title,face=index,support_face_count=len(faces),support_feature=host['features'][-1]['id'] if host['features'] else 'base',normal=list(plane.zDir.toTuple()),origin=list(plane.origin.toTuple()),x_direction=list(plane.xDir.toTuple()),reference=face_reference(shape,index).model_dump(),operation='cut',through_all=through,sketch=g.model_dump())
            host['features'].append(feature);created.append(identifier)
            d=Design.model_validate(data);shape=local_shape(d,next(p for p in d.parts if p.id==part_id))
        # Standard numeric links make the fastener/wire circles track the same
        # global printer setting; the pocket uses the explicit seat clearance.
        if data.get('print_profile'):
            from .print_profile import apply_print_profile,print_targets
            rows=print_targets(data);selected=[r['path'] for r in rows if r['linked'] or (r['part']==part_id and len(r['path'])>3 and r['path'][2]=='features' and r['path'][3] in created and not r['path'][3].endswith('-seat'))]
            d=apply_print_profile(data,data['print_profile'],selected)
            local_shape(d,next(p for p in d.parts if p.id==part_id))
        return d,created
