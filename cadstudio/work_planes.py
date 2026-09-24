"""Explicit sketch plane edits with dependent extrusion placement preserved."""
import numpy as np

from .models import Design,WorkPlane
from .sketch_frames import context_frame,work_plane_frame,frame_transform


def edit_sketch_plane(raw,sketch_id,plane,*,allow_grounded=False):
    from .placement import move_selection
    data=Design.model_validate(raw).model_dump();plane=WorkPlane.model_validate(plane)
    sketch=next((s for s in data['sketches'] if s['id']==sketch_id),None)
    if sketch is None:raise ValueError('작업 평면을 바꿀 스케치를 찾을 수 없습니다.')
    if sketch['context'].get('face') or sketch['context'].get('part_id'):
        raise ValueError('부품 면에 연결된 스케치입니다. 사용자 작업 평면은 독립 스케치에서 편집하세요.')
    old=context_frame(sketch['context']);new=work_plane_frame(plane)
    if not all(np.allclose(a,b,atol=1e-12,rtol=0) for a,b in zip(old,new)):
        def referenced(node):
            if isinstance(node,dict):return node.get('sketch_id')==sketch_id or any(referenced(v) for v in node.values())
            if isinstance(node,list):return any(referenced(v) for v in node)
            return False
        if any(referenced(p['geometry']) for p in data['parts']):
            raise ValueError('이 스케치를 회전·스윕·로프트가 참조합니다. 해당 모델링 도구에서 단면 위치를 편집하세요.')
        ids=[p['id'] for p in data['parts'] if p.get('profile_sketch_id')==sketch_id and not p.get('source_part_id')]
        if ids:
            origin,x,y=old;target,u,v=new
            delta=np.column_stack((u,v,np.cross(u,v)))@np.column_stack((x,y,np.cross(x,y))).T
            angles=frame_transform([0,0,0],delta[:,0],delta[:,1])
            data,_=move_selection(data,ids,translation=target-origin,rotation=[angles[k] for k in ('rx','ry','rz')],pivot=origin,
                                  connected=False,allow_grounded=allow_grounded)
    sketch=next(s for s in data['sketches'] if s['id']==sketch_id)
    sketch['context']['work_plane']=plane.model_dump()
    sketch['context']['title']=f"{sketch['name']} · {plane.plane} · 오프셋 {plane.offset:g} mm"
    return Design.model_validate(data).model_dump()


def plane_preview_sketch(plane):
    """Display-only 100 mm grid; never committed as user sketch geometry."""
    from .models import SavedSketch,Extrusion
    entities=[]
    for i in range(-50,51,10):
        for start,end in [((-50,i),(50,i)),((i,-50),(i,50))]:
            entities.append(dict(id='grid'+str(len(entities)),kind='line',construction=True,
                                 start=dict(x=start[0],y=start[1]),end=dict(x=end[0],y=end[1])))
    return SavedSketch(id='work-plane-preview',name='작업 평면 · 10 mm 격자',
                       geometry=Extrusion(sketch_mode='entities',entities=entities),context=dict(work_plane=plane))
