"""Native OpenGL CAD viewport using VTK's Qt window and exact-kernel meshes."""
import math
import numpy as np
from PySide6.QtCore import Qt,Signal,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QToolButton,QSizePolicy,QComboBox
import vtkmodules.qt
vtkmodules.qt.PyQtImpl='PySide6'
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkCommonCore import vtkPoints,vtkIdList
from vtkmodules.vtkCommonDataModel import vtkPolyData,vtkCellArray
from vtkmodules.vtkRenderingCore import vtkRenderer,vtkActor,vtkPolyDataMapper,vtkCellPicker,vtkTextActor
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals,vtkFeatureEdges
from vtkmodules.util.numpy_support import numpy_to_vtk,numpy_to_vtkIdTypeArray
import vtkmodules.vtkRenderingOpenGL2
import vtkmodules.vtkInteractionStyle
import vtkmodules.vtkRenderingFreeType


def polydata(vertices,triangles):
    pts=vtkPoints();pts.SetData(numpy_to_vtk(np.asarray(vertices,dtype=np.float64).reshape(-1,3),deep=True))
    tris=np.asarray(triangles,dtype=np.int64).reshape(-1,3)
    cells=vtkCellArray();cells.SetCells(len(tris),numpy_to_vtkIdTypeArray(np.c_[np.full(len(tris),3,dtype=np.int64),tris].reshape(-1),deep=True))
    mesh=vtkPolyData();mesh.SetPoints(pts);mesh.SetPolys(cells);return mesh


from .interaction import SelectionTools


class CADStyle(vtkInteractorStyleTrackballCamera):
    def __init__(self,owner):
        self.owner=owner;self.down=None
        self.AddObserver('LeftButtonPressEvent',self.press)
        self.AddObserver('LeftButtonReleaseEvent',self.release)
        self.AddObserver('KeyPressEvent',self.key)
        self.AddObserver('MouseMoveEvent',self.move)
    def press(self,caller,event):
        self.down=self.GetInteractor().GetEventPosition()
        if self.owner.handle and self.owner.handle.press(self.down):return
        self.OnLeftButtonDown()
    def release(self,caller,event):
        pos=self.GetInteractor().GetEventPosition()
        if self.owner.handle and self.owner.handle.release():self.down=None;return
        self.OnLeftButtonUp()
        if self.down and math.dist(self.down,pos)<5:self.owner.pick(*pos)
        self.down=None
    def move(self,caller,event):
        pos=self.GetInteractor().GetEventPosition()
        if self.owner.handle and self.owner.handle.move(pos):return
        self.OnMouseMove()
        if self.down is None:self.owner.hover_profile(*pos)
    def key(self,caller,event):
        key=self.GetInteractor().GetKeySym()
        if key.lower()=='f':self.owner.fit()
        elif key in ['1','2','3','4']:self.owner.set_view(['iso','top','front','right'][int(key)-1])


class CADViewport(QWidget,SelectionTools):
    profile_selected=Signal(str,int)
    geometry_selected=Signal(str,str,object)
    point_selected=Signal(str,object)
    edge_selected=Signal(int)
    sketch_selected=Signal(str)
    part_selected=Signal(str)
    face_selected=Signal(str,object)
    message=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('cadViewport');self.meshes={};self.actors={};self.actor_ids={};self.hidden=set();self.selected=None;self.face=None
        self.closed=False;self.show_edges=True;self.face_pick=False;self.result=None;self.grid_actor=None;self.highlight=None;self.sketch_actors={};self.edge_candidates={};self.pick_objects={};self.selection_mode='auto';self.profile_actors={};self.hovered_profile=None;self.handle=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        bar=QHBoxLayout();bar.setContentsMargins(12,8,12,8);self.caption=QLabel('새 설계 · XY 원점');self.caption.setStyleSheet('font-weight:600;color:#afc7d6;');self.caption.setWordWrap(True);self.caption.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);layout.addWidget(self.caption);self.caption.setContentsMargins(12,7,12,0);bar.addStretch()
        self.filter=QComboBox();self.filter.setObjectName('selectionFilter');self.filter.setToolTip('선택 대상 · Shift+1~6');
        for key,name in [('auto','자동 선택'),('point','점 선택'),('edge','선 / 모서리'),('face','면 선택'),('body','체적 / 부품'),('sketch','스케치 영역')]:self.filter.addItem(name,key)
        self.filter.currentIndexChanged.connect(lambda:self.set_selection_mode(self.filter.currentData()));bar.insertWidget(0,self.filter)
        for key,name in [('iso','등각 1'),('top','상면 2'),('front','정면 3'),('right','측면 4')]:
            b=QToolButton();b.setText(name);b.clicked.connect(lambda _,k=key:self.set_view(k));bar.addWidget(b)
        self.caption.setMinimumHeight(38);layout.addLayout(bar)
        self.widget=QVTKRenderWindowInteractor(self);self.widget.setObjectName('nativeOpenGLViewport');self.widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus);layout.addWidget(self.widget,1)
        self.renderer=vtkRenderer();self.renderer.SetBackground(.07,.105,.15);self.renderer.SetBackground2(.16,.22,.28);self.renderer.GradientBackgroundOn()
        self.window=self.widget.GetRenderWindow();self.window.AddRenderer(self.renderer);self.window.SetMultiSamples(4)
        self.interactor=self.window.GetInteractor();self.style=CADStyle(self);self.style.SetDefaultRenderer(self.renderer);self.interactor.SetInteractorStyle(self.style)
        self.axes=vtkAxesActor();self.axes.SetShaftTypeToCylinder();self.axes_widget=vtkOrientationMarkerWidget();self.axes_widget.SetOrientationMarker(self.axes);self.axes_widget.SetInteractor(self.interactor);self.axes_widget.SetViewport(0,0,.13,.19)
        self.footer=QLabel('드래그: 회전   ·   가운데 버튼: 이동   ·   휠: 확대   ·   클릭: 부품/면 선택   ·   F: 맞춤')
        self.footer.setStyleSheet('padding:7px 12px;background:#17232e;color:#92aabd;font-size:11px;');layout.addWidget(self.footer)
        self.make_grid(100);self.set_view('iso',render=False);QTimer.singleShot(0,self.initialize)

    def initialize(self):
        if self.closed:return
        self.widget.Initialize();self.axes_widget.SetEnabled(1);self.axes_widget.InteractiveOff();self.window.Render()

    def make_grid(self,extent):
        if self.grid_actor:self.renderer.RemoveActor(self.grid_actor)
        extent=max(50,float(extent));step=10**math.ceil(math.log10(extent/10));extent=math.ceil(extent/step)*step
        pts=vtkPoints();lines=vtkCellArray()
        for i in range(-int(extent/step),int(extent/step)+1):
            v=i*step
            for a,b in [((-extent,v,-.02),(extent,v,-.02)),((v,-extent,-.02),(v,extent,-.02))]:
                start=pts.InsertNextPoint(*a);end=pts.InsertNextPoint(*b);lines.InsertNextCell(2);lines.InsertCellPoint(start);lines.InsertCellPoint(end)
        mesh=vtkPolyData();mesh.SetPoints(pts);mesh.SetLines(lines);mapper=vtkPolyDataMapper();mapper.SetInputData(mesh);self.grid_actor=vtkActor();self.grid_actor.SetMapper(mapper);self.grid_actor.GetProperty().SetColor(.35,.49,.56);self.grid_actor.GetProperty().SetOpacity(.15);self.grid_actor.PickableOff();self.renderer.AddActor(self.grid_actor)

    def load(self,result,fit=True):
        for actor in self.edge_candidates:self.renderer.RemoveActor(actor)
        self.edge_candidates={}
        for data in self.actors.values():
            for actor in data:self.renderer.RemoveActor(actor)
        for actor in [*self.sketch_actors,*self.profile_actors,*self.pick_objects]:self.renderer.RemoveActor(actor)
        self.profile_actors={};self.pick_objects={};self.hovered_profile=None
        self.sketch_actors={};self.actors={};self.actor_ids={};self.meshes={};self.clear_face();self.result=result
        if result:
            for mesh in result['meshes']:
                self.meshes[mesh['id']]=mesh;data=polydata(mesh['vertices'],mesh['triangles'])
                normals=vtkPolyDataNormals();normals.SetInputData(data);normals.SetFeatureAngle(35);normals.SplittingOn();normals.ConsistencyOn();normals.AutoOrientNormalsOn()
                mapper=vtkPolyDataMapper();mapper.SetInputConnection(normals.GetOutputPort());mapper.ScalarVisibilityOff()
                actor=vtkActor();actor.SetMapper(mapper);color=tuple(int(mesh['color'][i:i+2],16)/255 for i in [1,3,5]);actor.GetProperty().SetColor(*color);actor.GetProperty().SetSpecular(.18);actor.GetProperty().SetSpecularPower(28);actor.GetProperty().SetAmbient(.24);actor.GetProperty().SetDiffuse(.76)
                edges=vtkFeatureEdges();edges.SetInputData(data);edges.BoundaryEdgesOn();edges.FeatureEdgesOn();edges.ManifoldEdgesOff();edges.NonManifoldEdgesOff();edges.SetFeatureAngle(28)
                edge_mapper=vtkPolyDataMapper();edge_mapper.SetInputConnection(edges.GetOutputPort());edge_mapper.ScalarVisibilityOff();edge_actor=vtkActor();edge_actor.SetMapper(edge_mapper);edge_actor.GetProperty().SetColor(.19,.29,.34);edge_actor.GetProperty().SetLineWidth(1);edge_actor.PickableOff();edge_actor.SetVisibility(self.show_edges)
                for a in [actor,edge_actor]:self.renderer.AddActor(a)
                self.actors[mesh['id']]=(actor,edge_actor);self.actor_ids[actor]=mesh['id']
            for sketch in result.get('sketches',[]):
                pts=vtkPoints();lines=vtkCellArray()
                for row in sketch['lines']:
                    if len(row)<2:continue
                    lines.InsertNextCell(len(row))
                    for point in row:lines.InsertCellPoint(pts.InsertNextPoint(*point))
                data=vtkPolyData();data.SetPoints(pts);data.SetLines(lines);mapper=vtkPolyDataMapper();mapper.SetInputData(data);actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.38,.81,.83);actor.GetProperty().SetLineWidth(2.5);self.renderer.AddActor(actor);self.sketch_actors[actor]=sketch['id']
            for sketch in result.get('sketches',[]):
                for region in sketch.get('regions',[]):
                    mapper=vtkPolyDataMapper();mapper.SetInputData(polydata(region['vertices'],region['triangles']));mapper.SetResolveCoincidentTopologyToPolygonOffset();mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2,-2)
                    actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.2,.85,.72);actor.GetProperty().SetOpacity(.07);self.renderer.AddActor(actor);self.profile_actors[actor]=(sketch['id'],region['index'])
            self.make_grid(max(result['stats']['bounds'])*1.2)
            s=result['stats'];self.caption.setText(f"{s['parts']}개 부품   ·   {' × '.join(f'{n:.2f}' for n in s['bounds'])} mm   ·   {s['volume']:,.2f} mm³")
            if result.get('sketches'):self.caption.setText(self.caption.text()+f"   ·   스케치 {len(result['sketches'])}개")
            if s['assembly_constraints']['mates']:self.caption.setText(self.caption.text()+f"   ·   조립 자유도 {s['assembly_constraints']['dof']}")
            if s['collisions']:self.caption.setText(self.caption.text()+f"   ·   간섭 {len(s['collisions'])}건")
        else:self.caption.setText('새 설계 · 스케치를 시작하거나 부품을 추가하세요.')
        self.rebuild_pick_objects()
        for key in self.hidden:self.visibility(key,False,False)
        if self.selected in self.actors:self.select(self.selected,False)
        if fit:self.fit()
        else:self.window.Render()

    def clear_face(self):
        if self.highlight:self.renderer.RemoveActor(self.highlight);self.highlight=None
        self.face=None

    def pick(self,x,y):
        if self.edge_candidates:
            picker=vtkCellPicker();picker.SetTolerance(.008);picker.PickFromListOn()
            for actor in self.edge_candidates:picker.AddPickList(actor)
            if picker.Pick(x,y,0,self.renderer) and picker.GetActor() in self.edge_candidates:self.edge_selected.emit(self.edge_candidates[picker.GetActor()])
            return
        if self.pick_filtered(x,y):return
        if self.selection_mode in ('auto','sketch'):
            actor=self.profile_at(x,y)
            if actor in self.profile_actors:
                sid,index=self.profile_actors[actor];self.clear_face();self.profile_selected.emit(sid,index);self.message.emit(f'스케치 영역 {index+1} 선택 · E: 3D 돌출');return
        picker=vtkCellPicker();picker.SetTolerance(.004);picker.PickFromListOn()
        for actor in (self.sketch_actors if self.selection_mode=='sketch' else self.actor_ids):picker.AddPickList(actor)
        if self.selection_mode=='auto':
            for actor in self.sketch_actors:picker.AddPickList(actor)
        if not picker.Pick(x,y,0,self.renderer):self.clear_face();self.window.Render();return
        if picker.GetActor() in self.sketch_actors:
            self.sketch_selected.emit(self.sketch_actors[picker.GetActor()]);return
        identifier=self.actor_ids.get(picker.GetActor())
        if not identifier:return
        mesh=self.meshes[identifier];index=picker.GetCellId()
        if index<0 or index>=len(mesh['triangle_faces']):return
        face_index=mesh['triangle_faces'][index];face=next((f for f in mesh['faces'] if f['index']==face_index),None)
        self.select(identifier,False);self.part_selected.emit(identifier)
        if self.selection_mode=='body':self.clear_face();self.window.Render();self.message.emit(mesh['name']+' · 부품 선택');return
        self.highlight_face(identifier,face_index)
        self.face=(identifier,face)
        self.face_selected.emit(identifier,face)
        self.point_selected.emit(identifier,list(picker.GetPickPosition()))
        self.message.emit(f"{mesh['name']} · 면 {face_index+1} · {'평면 스케치 가능' if face and face['planar'] else '곡면'}")

    def set_edge_candidates(self,records):
        for actor in self.edge_candidates:self.renderer.RemoveActor(actor)
        self.edge_candidates={}
        for ref in records:
            points=vtkPoints();cells=vtkCellArray();cells.InsertNextCell(len(ref['points']))
            for p in ref['points']:cells.InsertCellPoint(points.InsertNextPoint(*p))
            mesh=vtkPolyData();mesh.SetPoints(points)
            if len(ref['points'])==1:mesh.SetVerts(cells)
            else:mesh.SetLines(cells)
            mapper=vtkPolyDataMapper();mapper.SetInputData(mesh);mapper.SetResolveCoincidentTopologyToPolygonOffset();mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-2,-2)
            actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.55,.7,.76);actor.GetProperty().SetLineWidth(2);actor.GetProperty().SetPointSize(10);actor.GetProperty().RenderPointsAsSpheresOn();self.renderer.AddActor(actor);self.edge_candidates[actor]=ref['index']
        self.footer.setText('모서리 클릭: 선택 / 해제 · 드래그: 회전 · 휠: 확대');self.window.Render()

    def highlight_edges(self,selected):
        for actor,index in self.edge_candidates.items():
            actor.GetProperty().SetColor(*((.35,.95,.7) if index in selected else (.55,.7,.76)));actor.GetProperty().SetLineWidth(4 if index in selected else 2)
        self.window.Render()

    def highlight_face(self,identifier,face_index):
        self.clear_face();mesh=self.meshes[identifier];triangles=np.asarray(mesh['triangles']).reshape(-1,3);mask=np.asarray(mesh['triangle_faces'])==face_index
        data=polydata(mesh['vertices'],triangles[mask]);mapper=vtkPolyDataMapper();mapper.SetInputData(data);mapper.SetResolveCoincidentTopologyToPolygonOffset();mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-1,-1)
        actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.95,.68,.22);actor.GetProperty().SetOpacity(.45);actor.PickableOff();self.highlight=actor;self.renderer.AddActor(actor);self.window.Render()

    def select(self,identifier,render=True):
        self.selected=identifier
        for key,(_,edge) in self.actors.items():edge.GetProperty().SetColor(*((.86,.52,.16) if key==identifier else (.22,.35,.40)));edge.GetProperty().SetLineWidth(1.7 if key==identifier else 1)
        if render:self.window.Render()

    def visibility(self,identifier,visible,render=True):
        if visible:self.hidden.discard(identifier)
        else:self.hidden.add(identifier)
        if identifier in self.actors:
            actor,edge=self.actors[identifier];actor.SetVisibility(visible);edge.SetVisibility(visible and self.show_edges)
        self.rebuild_pick_objects()
        if render:self.window.Render()

    def edges(self,enabled):
        self.show_edges=enabled
        for key,(_,edge) in self.actors.items():edge.SetVisibility(enabled and key not in self.hidden)
        self.window.Render()

    def fit(self):
        if self.result:
            a=self.result['stats']['min'];b=self.result['stats']['max'];bounds=[v for pair in zip(a,b) for v in pair];self.renderer.ResetCamera(bounds if max(self.result['stats']['bounds'])>1e-6 else [-25,25,-25,25,0,0])
        else:self.renderer.ResetCamera(-50,50,-50,50,0,0)
        self.renderer.ResetCameraClippingRange();self.window.Render()

    def set_view(self,name,render=True):
        camera=self.renderer.GetActiveCamera();camera.ParallelProjectionOn()
        directions={'iso':((1,-1,1), (0,0,1)),'top':((0,0,1),(0,1,0)),'front':((0,-1,0),(0,0,1)),'right':((1,0,0),(0,0,1))}
        position,up=directions[name];camera.SetPosition(*[v*200 for v in position]);camera.SetFocalPoint(0,0,0);camera.SetViewUp(*up)
        if render:self.fit()

    def shutdown(self):
        if self.closed:return
        self.closed=True
        if self.handle:self.handle.close()
        # Disconnect the VTK -> Python -> QWidget cycle while the Qt window
        # still exists. Otherwise later garbage collection may release an
        # OpenGL interactor after Qt has destroyed its native HWND.
        self.axes_widget.SetEnabled(0);self.axes_widget.SetInteractor(None)
        self.style.RemoveAllObservers();self.style.owner=None;self.interactor.SetInteractorStyle(None);self.interactor.Disable()
        self.widget._Timer.stop();self.interactor.RemoveAllObservers();self.window.RemoveAllObservers();self.renderer.RemoveAllViewProps();self.widget.Finalize()
