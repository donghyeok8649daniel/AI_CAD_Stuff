"""Cached picking and extrusion handles: no CAD kernel calls in mouse events."""
import math
import numpy as np
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkPolyData,vtkCellArray
from vtkmodules.vtkRenderingCore import vtkActor,vtkPolyDataMapper,vtkCellPicker,vtkRenderer
from vtkmodules.vtkFiltersSources import vtkConeSource


def line_actor(rows,color=(.35,.85,.8),width=2,points=False):
    pts=vtkPoints();cells=vtkCellArray()
    for row in rows:
        if len(row)==0:continue
        cells.InsertNextCell(len(row))
        for p in row:cells.InsertCellPoint(pts.InsertNextPoint(*p))
    data=vtkPolyData();data.SetPoints(pts)
    if points:data.SetVerts(cells)
    else:data.SetLines(cells)
    mapper=vtkPolyDataMapper();mapper.SetInputData(data);mapper.SetResolveCoincidentTopologyToPolygonOffset();mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-2,-2)
    actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(*color);actor.GetProperty().SetLineWidth(width);actor.GetProperty().SetPointSize(9);actor.GetProperty().RenderPointsAsSpheresOn();return actor


class ExtrusionHandle:
    def __init__(self,viewport,center,normal,outlines,changed):
        self.view=viewport;self.center=np.array(center,float);self.normal=np.array(normal,float);self.rows=outlines;self.changed=changed;self.actors=[];self.drag=None;self.depth=8.
        # A cut handle may be inside the solid: draw controls in an overlay so
        # depth testing never hides the only way to drag it back out.
        self.overlay=vtkRenderer();self.overlay.SetLayer(2);self.overlay.SetInteractive(False);self.overlay.SetPreserveDepthBuffer(False);self.overlay.SetActiveCamera(viewport.renderer.GetActiveCamera());viewport.window.SetNumberOfLayers(max(3,viewport.window.GetNumberOfLayers()));viewport.window.AddRenderer(self.overlay)
        viewport.handle=self;self.update(8.)
    def display(self,p):
        r=self.view.renderer;r.SetWorldPoint(*p,1);r.WorldToDisplay();return np.array(r.GetDisplayPoint()[:2])
    def pixel_scale(self):return 2*self.view.renderer.GetActiveCamera().GetParallelScale()/max(1,self.view.window.GetSize()[1])
    def update(self,depth):
        self.depth=float(depth)
        for actor in self.actors:self.view.renderer.RemoveActor(actor);self.overlay.RemoveActor(actor)
        offset=self.normal*depth;end=self.center+offset;size=self.pixel_scale()*self.view.widget.devicePixelRatioF();direction=self.normal*(1 if depth>=0 else -1)
        cone=vtkConeSource();cone.SetCenter(*(end+direction*size*48));cone.SetDirection(*direction);cone.SetHeight(size*24);cone.SetRadius(size*9);cone.SetResolution(20)
        mapper=vtkPolyDataMapper();mapper.SetInputConnection(cone.GetOutputPort());tip=vtkActor();tip.SetMapper(mapper);tip.GetProperty().SetColor(1,.72,.25)
        tip.GetProperty().SetAmbient(1);tip.GetProperty().SetDiffuse(0)
        axis=line_actor([[self.center,end+direction*size*48]],(1,.72,.25),4);ghost=[]
        for row in self.rows:
            points=np.asarray(row);ghost.extend([points,(points+offset)])
            if len(points):ghost.extend([[points[0],points[0]+offset],[points[-1],points[-1]+offset]])
        outline=line_actor(ghost,(.33,.93,.8),1.5);outline.PickableOff();self.pickable=[tip,axis];self.actors=[outline,axis,tip]
        self.view.renderer.AddActor(outline);self.overlay.AddActor(axis);self.overlay.AddActor(tip)
        bounds=self.view.renderer.ComputeVisiblePropBounds();extra=self.overlay.ComputeVisiblePropBounds();combined=[min(bounds[i],extra[i]) if i%2==0 else max(bounds[i],extra[i]) for i in range(6)]
        self.view.renderer.ResetCameraClippingRange(combined);self.view.window.Render()
    def press(self,pos):
        picker=vtkCellPicker();picker.SetTolerance(.012);picker.PickFromListOn()
        for actor in self.pickable:picker.AddPickList(actor)
        if not picker.Pick(*pos,0,self.overlay):return False
        axis=self.display(self.center+self.normal)-self.display(self.center)
        self.drag=(np.array(pos,float),self.depth,axis,self.pixel_scale());return True
    def move(self,pos):
        if self.drag is None:return False
        start,depth,axis,scale=self.drag;delta=np.array(pos)-start
        # A top view points along the extrusion axis: use vertical movement.
        value=depth+(float(delta@axis/(axis@axis)) if np.linalg.norm(axis)>.15 else float(delta[1])*scale)
        value=max(-2000,min(2000,value));value=round(value,2)
        if abs(value)<.01:value=.01 if value>=0 else -.01
        self.update(value);self.changed(value);return True
    def release(self):
        active=self.drag is not None;self.drag=None;return active
    def close(self):
        for actor in self.actors:self.view.renderer.RemoveActor(actor)
        self.overlay.RemoveAllViewProps();self.view.window.RemoveRenderer(self.overlay);self.actors=[];self.view.handle=None


class SelectionTools:
    def set_selection_mode(self,mode):
        self.selection_mode=mode;self.clear_face();self.rebuild_pick_objects();self.window.Render()
    def rebuild_pick_objects(self):
        for actor in self.pick_objects:self.renderer.RemoveActor(actor)
        self.pick_objects={}
        if self.selection_mode not in ('point','edge'):return
        for identifier,mesh in self.meshes.items():
            if identifier in self.hidden:continue
            records=[dict(index=i,points=[p]) for i,p in enumerate(mesh.get('pick_vertices',[]))] if self.selection_mode=='point' else mesh.get('pick_edges',[])
            for record in records:
                actor=line_actor([record['points']],width=2,points=self.selection_mode=='point');self.renderer.AddActor(actor);self.pick_objects[actor]=(identifier,record)
    def pick_filtered(self,x,y):
        if self.selection_mode not in ('point','edge'):return False
        picker=vtkCellPicker();picker.SetTolerance(.01);picker.PickFromListOn()
        for actor in self.pick_objects:picker.AddPickList(actor)
        if picker.Pick(x,y,0,self.renderer) and picker.GetActor() in self.pick_objects:
            identifier,record=self.pick_objects[picker.GetActor()];self.select(identifier,False);self.part_selected.emit(identifier);self.clear_face()
            for actor in self.pick_objects:actor.GetProperty().SetColor(*((1,.72,.25) if actor==picker.GetActor() else (.35,.85,.8)))
            if self.selection_mode=='point':self.point_selected.emit(identifier,record['points'][0]);text='점 '+str(record['index']+1)+' · '+', '.join(f'{v:.3f}' for v in record['points'][0])+' mm'
            else:text=f"모서리 {record['index']+1} · 길이 {record['length']:.3f} mm"
            self.geometry_selected.emit(identifier,self.selection_mode,record);self.message.emit(text);self.footer.setText(text);self.window.Render()
        return True
    def profile_at(self,x,y):
        picker=vtkCellPicker();picker.SetTolerance(.004);picker.PickFromListOn()
        for actor in self.profile_actors:picker.AddPickList(actor)
        if picker.Pick(x,y,0,self.renderer):return picker.GetActor()
        return None
    def hover_profile(self,x,y):
        if self.selection_mode not in ('auto','sketch'):return
        actor=self.profile_at(x,y)
        if actor==self.hovered_profile:return
        if self.hovered_profile in self.profile_actors:self.hovered_profile.GetProperty().SetOpacity(.07)
        self.hovered_profile=actor
        if actor in self.profile_actors:
            actor.GetProperty().SetOpacity(.35);sid,index=self.profile_actors[actor];self.footer.setText(f'스케치 영역 {index+1} · 클릭 선택 → E 돌출 · 드래그: 회전')
        self.window.Render()
