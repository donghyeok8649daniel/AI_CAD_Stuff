"""Conservative geometric face matching; ambiguous matches require reselection."""
import math
import cadquery as cq
from .models import FaceReference


def face_reference(shape,index,bounds=None,faces=None):
    from .kernel import exact_bounds
    face=(faces if faces is not None else shape.Faces())[index];b=bounds or exact_bounds(shape);center=face.Center().toTuple()
    low=(b.xmin,b.ymin,b.zmin);size=(b.xlen,b.ylen,b.zlen)
    return FaceReference(index=index,surface=face.geomType(),center=list(center),relative_center=[(v-a)/max(d,1e-9) for v,a,d in zip(center,low,size)],normal=list(face.normalAt().toTuple()) if face.geomType()=='PLANE' else [],area=face.Area())


def resolve_face(shape,reference):
    reference=FaceReference.model_validate(reference);candidates=[]
    from .kernel import exact_bounds
    faces=shape.Faces();bounds=exact_bounds(shape)
    for i,face in enumerate(faces):
        if face.geomType()!=reference.surface:continue
        current=face_reference(shape,i,bounds,faces)
        if reference.normal and (cq.Vector(*current.normal)-cq.Vector(*reference.normal)).Length>1e-5:continue
        exact=math.dist(current.center,reference.center)<1e-6 and abs(current.area-reference.area)<max(1e-6,reference.area*1e-7)
        score=math.dist(current.relative_center,reference.relative_center)
        if exact or score<.12:candidates.append((0 if exact else score+1e-5,i,face))
    candidates.sort(key=lambda row:row[0])
    if not candidates:raise ValueError('참조 면을 찾을 수 없습니다. 해당 피처에서 면을 다시 선택하세요.')
    if len(candidates)>1 and abs(candidates[1][0]-candidates[0][0])<1e-4:raise ValueError('참조 면 후보가 여러 개입니다. 잘못된 면에 적용하지 않도록 재선택이 필요합니다.')
    return candidates[0][1],candidates[0][2]


def resolve_edge(shape,reference):
    from .kernel import exact_bounds
    from .models import EdgeReference
    ref=EdgeReference.model_validate(reference);b=exact_bounds(shape);low=(b.xmin,b.ymin,b.zmin);sizes=(b.xlen,b.ylen,b.zlen);candidates=[]
    if len(ref.relative_center)!=3 or len(ref.tangent)!=3:raise ValueError('모서리 참조 좌표가 잘못됐습니다.')
    for i,edge in enumerate(shape.Edges()):
        if edge.geomType()!=ref.curve:continue
        tangent=edge.tangentAt(.5)
        if abs(tangent.dot(cq.Vector(*ref.tangent)))<.9999:continue
        center=list(edge.Center().toTuple());relative=[(v-a)/max(d,1e-9) for v,a,d in zip(center,low,sizes)];score=math.dist(relative,ref.relative_center)
        exact=math.dist(center,ref.center)<1e-6 and abs(edge.Length()-ref.length)<1e-6
        if exact or score<.08:candidates.append((0 if exact else score+1e-5,i,edge))
    candidates.sort(key=lambda item:item[0])
    if not candidates or len(candidates)>1 and abs(candidates[0][0]-candidates[1][0])<1e-4:raise ValueError('참조 모서리를 확실히 찾을 수 없습니다. 모서리를 다시 선택하세요.')
    return candidates[0][1],candidates[0][2]
