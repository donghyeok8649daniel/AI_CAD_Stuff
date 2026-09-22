"""Saved sketch display frames; geometry and support context remain in history."""
import numpy as np
from ..sketch_engine import sketch_preview
from ..constraints import transform_matrix


def preview_sketches(design):
    result=[]
    for sketch in design.sketches:
        context=sketch.context.model_dump()
        face=context.get('face')
        if face:
            origin=np.array(face['origin']);x=np.array(face['x_direction']);normal=np.array(face['normal']);y=np.cross(normal,x)
        else:
            origin=np.zeros(3);plane=context.get('plane','XY')
            x=np.array([0,1,0] if plane=='YZ' else [1,0,0]);y=np.array([0,0,1] if plane in ('YZ','XZ') else [0,1,0])
        part=next((p for p in design.parts if p.id==context.get('part_id')),None)
        rotation=transform_matrix(part.transform) if part else np.eye(3)
        translation=np.array([part.transform.x,part.transform.y,part.transform.z]) if part else np.zeros(3)
        def world(p):return (rotation@(origin+x*p[0]+y*p[1])+translation).tolist()
        lines=[]
        for entity in sketch_preview(sketch.geometry)['entities']:
            lines.extend([[world(p) for p in row] for row in entity['lines']])
        for entity in sketch.geometry.entities:
            if entity.kind=='point':
                p=entity.position;lines.append([world([p.x-.3,p.y]),world([p.x+.3,p.y])]);lines.append([world([p.x,p.y-.3]),world([p.x,p.y+.3])])
        result.append(dict(id=sketch.id,name=sketch.name,lines=lines))
    return result
