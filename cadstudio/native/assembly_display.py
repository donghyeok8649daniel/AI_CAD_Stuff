"""Cached world-space joint glyphs; selection overlays do not alter the design."""
import math
import numpy as np
from vtkmodules.vtkRenderingCore import vtkRenderer,vtkCellPicker,vtkBillboardTextActor3D
from ..models import Design
from ..constraints import anchors,transform_matrix
from ..assembly_motion import JOINT_TITLES
from .interaction import line_actor

JOINT_NAMES={**JOINT_TITLES,'closure':'폐루프'}


def assembly_markers(raw):
    if not raw:return []
    design=raw if isinstance(raw,Design) else Design.model_validate(raw)
    parts={p.id:p for p in design.parts};frames={f.mate_id:f for f in design.joint_frames};rows=[]
    def world(p,point):return np.array([p.transform.x,p.transform.y,p.transform.z])+transform_matrix(p.transform)@np.array(point)
    for index,m in enumerate(design.mates,1):
        parent,child=parts[m.parent],parts[m.child];rotation=transform_matrix(parent.transform);frame=frames.get(m.id)
        if frame:
            basis=rotation@np.column_stack([frame.parent.x_direction,np.cross(frame.parent.normal,frame.parent.x_direction),frame.parent.normal])
            a=world(parent,frame.parent.origin);b=world(child,frame.child.origin)
        else:
            basis=rotation;a=world(parent,anchors(parent.geometry)[m.parent_anchor]);b=world(child,anchors(child.geometry)[m.child_anchor])
        origin=a+basis@np.array([m.x,m.y,m.z])
        rows.append(dict(id=m.id,type='mate',kind=m.kind,label=f'J{index}',parent=m.parent,child=m.child,parent_name=parent.name,child_name=child.name,origin=origin.tolist(),a=a.tolist(),b=b.tolist(),basis=basis.tolist()))
    for index,c in enumerate(design.loops,1):
        parent,child=parts[c.parent],parts[c.child];rotation=transform_matrix(parent.transform)
        a=world(parent,np.array(anchors(parent.geometry)[c.parent_anchor])+c.offset);b=world(child,anchors(child.geometry)[c.child_anchor])
        rows.append(dict(id=c.id,type='loop',kind='closure',label=f'L{index}',parent=c.parent,child=c.child,parent_name=parent.name,child_name=child.name,origin=a.tolist(),a=a.tolist(),b=b.tolist(),basis=rotation.tolist()))
    return rows


class AssemblyDisplay:
    def __init__(self,view):
        self.view=view;self.records=[];self.enabled=False;self.pickables={};self.actors=[]
        self.renderer=vtkRenderer();self.renderer.SetLayer(1);self.renderer.SetInteractive(False);self.renderer.SetPreserveDepthBuffer(False);self.renderer.SetActiveCamera(view.renderer.GetActiveCamera())
        view.window.SetNumberOfLayers(max(3,view.window.GetNumberOfLayers()));view.window.AddRenderer(self.renderer)

    def set_design(self,raw,enabled=None):
        if enabled is not None:self.enabled=enabled
        self.records=assembly_markers(raw) if raw else [];self.rebuild()

    def rebuild(self):
        self.renderer.RemoveAllViewProps();self.actors=[];self.pickables={}
        if self.enabled:
            size=max(2,min(10,max((self.view.result or {}).get('stats',{}).get('bounds',[50]))*.045))
            for row in self.records:
                color=(1,.64,.23) if row['type']=='loop' else (.25,.95,.85)
                p=np.array(row['origin']);basis=np.array(row['basis']);x,y,z=basis.T
                paths=[[row['a'],row['b']],[p-z*size,p+z*size]]
                if row['kind'] in ('revolute','cylindrical','pin_slot','ball'):
                    paths.append([p+size*.65*(x*math.cos(t)+y*math.sin(t)) for t in np.linspace(0,2*math.pi,33)])
                else:paths.extend([[p-x*size*.6,p+x*size*.6],[p-y*size*.6,p+y*size*.6]])
                glyph=line_actor(paths,color,3);dot=line_actor([[p]],color,points=True);dot.GetProperty().SetPointSize(13)
                for actor in (glyph,dot):
                    actor.GetProperty().SetLighting(False);self.renderer.AddActor(actor);self.actors.append(actor);self.pickables[actor]=(row['type'],row['id'])
                text=vtkBillboardTextActor3D();text.SetInput(row['label']+' '+row['kind']);text.SetPosition(*(p+x*size));text.GetTextProperty().SetFontSize(13);text.GetTextProperty().SetColor(*color);text.GetTextProperty().SetBackgroundColor(.04,.08,.12);text.GetTextProperty().SetBackgroundOpacity(.8);text.PickableOff();self.renderer.AddActor(text);self.actors.append(text)
        self.view.window.Render()

    def pick(self,x,y):
        if not self.enabled:return False
        picker=vtkCellPicker();picker.SetTolerance(.008);picker.PickFromListOn()
        for actor in self.pickables:picker.AddPickList(actor)
        if picker.Pick(x,y,0,self.renderer):
            data=self.pickables.get(picker.GetActor())
            if data:self.view.joint_selected.emit(*data);return True
        return False

    def close(self):self.renderer.RemoveAllViewProps();self.view.window.RemoveRenderer(self.renderer)
