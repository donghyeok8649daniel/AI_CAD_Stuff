"""Saved sketch display frames; geometry and support context remain in history."""
import numpy as np
from ..sketch_engine import sketch_preview,profile_regions
from ..sketch_frames import context_frame


def sketch_frame(design,sketch):
    return context_frame(sketch.context,design)


def preview_sketches(design):
    result=[]
    for sketch in design.sketches:
        origin,x,y=sketch_frame(design,sketch)
        def world(p):return (origin+x*p[0]+y*p[1]).tolist()
        lines=[]
        for entity in sketch_preview(sketch.geometry)['entities']:
            lines.extend([[world(p) for p in row] for row in entity['lines']])
        for entity in sketch.geometry.entities:
            if entity.kind=='point':
                p=entity.position;lines.append([world([p.x-.3,p.y]),world([p.x+.3,p.y])]);lines.append([world([p.x,p.y-.3]),world([p.x,p.y+.3])])
        regions=[]
        for index,face in enumerate(profile_regions(sketch.geometry)):
            vertices,triangles=face.tessellate(.08,.1)
            outline=[]
            for edge in face.Edges():
                samples,_=edge.sample(30)
                if edge.IsClosed() and samples:samples.append(samples[0])
                outline.append([world(p.toTuple()) for p in samples])
            regions.append(dict(index=index,vertices=[world(v.toTuple()) for v in vertices],triangles=triangles,outline=outline,area=face.Area(),center=world(face.Center().toTuple())))
        result.append(dict(id=sketch.id,name=sketch.name,lines=lines,regions=regions,origin=origin.tolist(),normal=np.cross(x,y).tolist(),x_direction=x.tolist()))
    return result
