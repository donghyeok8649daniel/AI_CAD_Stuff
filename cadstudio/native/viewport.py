"""Native OpenGL CAD viewport using VTK's Qt window and exact-kernel meshes."""
import math
import os
import numpy as np
from PySide6.QtCore import Qt,Signal,QTimer,QPoint,QRect,QEvent
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QToolButton,QSizePolicy,QComboBox,QRubberBand,QMessageBox
import vtkmodules.qt
vtkmodules.qt.PyQtImpl='PySide6'
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkCommonCore import vtkPoints,vtkIdList
from vtkmodules.vtkCommonDataModel import vtkPolyData,vtkCellArray
from vtkmodules.vtkRenderingCore import vtkRenderer,vtkActor,vtkPolyDataMapper,vtkCellPicker,vtkTextActor,vtkLightKit
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
from .render_depth import reset_clipping,surface_offset,line_offset


class ViewportCaption(QLabel):
    """Keep model statistics readable without taking space from a small viewport."""
    def __init__(self,text):
        super().__init__();self._full_text='';self.setText(text)
    def setText(self,text):
        self._full_text=text;self.setToolTip(text);self._refresh_text()
    def text(self):
        return self._full_text
    def _refresh_text(self):
        super().setText(self.fontMetrics().elidedText(self._full_text,Qt.TextElideMode.ElideRight,max(0,self.contentsRect().width())))
    def resizeEvent(self,event):
        super().resizeEvent(event);self._refresh_text()


class CursorInteractor(QVTKRenderWindowInteractor):
    # The upstream Qt adapter renders/configures unconditionally. A parent may
    # hide its native child only after our viewport has released the WGL
    # context, and already queued events can still arrive during that interval.
    _vtk_events=frozenset((QEvent.Type.Paint,QEvent.Type.Resize,QEvent.Type.UpdateRequest,
        QEvent.Type.Timer,QEvent.Type.Enter,QEvent.Type.Leave,QEvent.Type.Wheel,
        QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,QEvent.Type.MouseMove,
        QEvent.Type.KeyPress,QEvent.Type.KeyRelease))

    def __init__(self,parent=None,**kwargs):
        self._finalized=False
        super().__init__(parent,**kwargs)

    def event(self,event):
        if self._finalized and event.type() in self._vtk_events:
            event.accept();return True
        return super().event(event)

    def Finalize(self):
        if self._finalized:return
        # Set the guard first: disabling the interactor can itself emit events.
        self._finalized=True;self._Timer.stop();self.setUpdatesEnabled(False)
        self._Iren.Disable()
        self._Iren.RemoveObservers('CreateTimerEvent');self._Iren.RemoveObservers('DestroyTimerEvent')
        self._RenderWindow.RemoveObservers('CursorChangedEvent')
        super().Finalize()

    def closeEvent(self,event):
        self.Finalize();event.accept()

    def paintEvent(self,event):
        if self._finalized:event.accept();return
        super().paintEvent(event)

    def resizeEvent(self,event):
        if self._finalized:event.accept();return
        super().resizeEvent(event)

    def Render(self):
        if not self._finalized:super().Render()

    def CreateTimer(self,obj,event):
        if not self._finalized:super().CreateTimer(obj,event)

    def TimerEvent(self):
        if not self._finalized:super().TimerEvent()

    def CursorChangedEvent(self,obj,event):
        if not self._finalized:super().CursorChangedEvent(obj,event)

    def ShowCursor(self):
        if not self._finalized:super().ShowCursor()

    def wheelEvent(self,event):
        if self._finalized:event.accept();return
        # VTK's Qt adapter otherwise uses the last mouse-move coordinates,
        # which can be stale after a resize, touchpad event or focus change.
        p=event.position();ctrl,shift=self._GetCtrlShift(event)
        self._setEventInformation(p.x(),p.y(),ctrl,shift,chr(0),0,None)
        super().wheelEvent(event);event.accept()


class CADStyle(vtkInteractorStyleTrackballCamera):
    def __init__(self,owner):
        self.owner=owner;self.down=None
        self.AddObserver('LeftButtonPressEvent',self.press)
        self.AddObserver('LeftButtonReleaseEvent',self.release)
        self.AddObserver('KeyPressEvent',self.key)
        self.AddObserver('MouseMoveEvent',self.move)
        self.AddObserver('MouseWheelForwardEvent',lambda *_:self.wheel(1.18))
        self.AddObserver('MouseWheelBackwardEvent',lambda *_:self.wheel(1/1.18))
    def wheel(self,factor):
        self.owner.zoom_at_cursor(self.GetInteractor().GetEventPosition(),factor)
    def press(self,caller,event):
        self.down=self.GetInteractor().GetEventPosition()
        self.axis_drag=self.owner.axis_at(self.down);self.axis_last=self.down
        if self.axis_drag is not None:return
        self.additive=bool(self.GetInteractor().GetShiftKey() or self.GetInteractor().GetControlKey())
        self.box=bool(not self.owner.orbit_mode and (self.owner.box_mode or self.additive))
        if self.owner.handle and self.owner.handle.press(self.down):self.box=False;return
        if self.box:return
        self.OnLeftButtonDown()
    def release(self,caller,event):
        pos=self.GetInteractor().GetEventPosition()
        if getattr(self,'axis_drag',None) is not None:
            if self.down and math.dist(self.down,pos)<5:self.owner.orient_axis(self.axis_drag)
            self.down=None;self.axis_drag=None;return
        if getattr(self,'box',False):
            self.owner.rubber.hide()
            if self.down:
                if math.dist(self.down,pos)<5:self.owner.pick(*pos,additive=self.additive,body=True)
                else:self.owner.box_pick(self.down,pos,self.additive)
            self.down=None;self.box=False;return
        if self.owner.handle and self.owner.handle.release():self.down=None;return
        self.OnLeftButtonUp()
        if self.down and math.dist(self.down,pos)<5 and not self.owner.orbit_mode:self.owner.pick(*pos)
        self.down=None
    def move(self,caller,event):
        pos=self.GetInteractor().GetEventPosition()
        if self.down is not None and getattr(self,'axis_drag',None) is not None:
            if math.dist(self.down,pos)>=5:
                camera=self.owner.renderer.GetActiveCamera();camera.Azimuth((self.axis_last[0]-pos[0])*.6);camera.Elevation((self.axis_last[1]-pos[1])*.6);camera.OrthogonalizeViewUp();self.owner.renderer.ResetCameraClippingRange();self.owner.window.Render()
            self.axis_last=pos;return
        if self.down is not None and getattr(self,'box',False):self.owner.show_rubber(self.down,pos);return
        if self.owner.handle and self.owner.handle.move(pos):return
        self.OnMouseMove()
        if self.down is None and not self.owner.orbit_mode:self.owner.hover_profile(*pos)
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
    parts_selected=Signal(object,str)
    joint_selected=Signal(str,str)
    face_selected=Signal(str,object)
    message=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('cadViewport');self.meshes={};self.actors={};self.actor_ids={};self.hidden=set();self.selected=None;self.selected_ids=[];self.face=None;self.box_mode=False;self.orbit_mode=False
        self.closed=False;self.show_edges=True;self.face_pick=False;self.result=None;self.grid_actor=None;self.highlight=None;self.sketch_actors={};self.edge_candidates={};self.pick_objects={};self.selection_mode='auto';self.profile_actors={};self.hovered_profile=None;self.handle=None;self.grid_visible=True;self.axes_visible=True;self.initialized=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        bar=QHBoxLayout();bar.setContentsMargins(12,8,12,8);self.caption=ViewportCaption('새 설계 · XY 원점');self.caption.setStyleSheet('font-weight:600;color:#afc7d6;');self.caption.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);layout.addWidget(self.caption);self.caption.setContentsMargins(12,7,12,0);bar.addStretch()
        layout.removeWidget(self.caption);caption_row=QHBoxLayout();caption_row.setContentsMargins(0,0,10,0);caption_row.addWidget(self.caption,1);self.grid_label=QLabel();caption_row.addWidget(self.grid_label);layout.insertLayout(0,caption_row)
        self.collision_button=QToolButton();self.collision_button.setStyleSheet('QToolButton {background:#713824;color:#ffe0bd;border:1px solid #e49064;padding:4px 7px;font-weight:600;}');self.collision_button.clicked.connect(self.show_collisions);self.collision_button.hide();caption_row.addWidget(self.collision_button)
        self.filter=QComboBox();self.filter.setObjectName('selectionFilter');self.filter.setToolTip('선택 대상 · Shift+1~6');
        for key,name in [('auto','자동 선택'),('point','점 선택'),('edge','선 / 모서리'),('face','면 선택'),('body','체적 / 부품'),('sketch','스케치 영역')]:self.filter.addItem(name,key)
        self.filter.currentIndexChanged.connect(lambda:self.set_selection_mode(self.filter.currentData()));bar.insertWidget(0,self.filter)
        for key,name in [('iso','등각 1'),('top','상면 2'),('front','정면 3'),('right','측면 4')]:
            b=QToolButton();b.setText(name);b.clicked.connect(lambda _,k=key:self.set_view(k));bar.addWidget(b)
        self.caption.setMinimumHeight(38);layout.addLayout(bar)
        if os.name=='nt':
            # Use exactly the backend tested by the isolated graphics probe.
            # VTK's automatic OSMesa fallback may itself crash on Windows.
            from vtkmodules.vtkRenderingOpenGL2 import vtkWin32OpenGLRenderWindow
            self.widget=CursorInteractor(self,rw=vtkWin32OpenGLRenderWindow())
        else:self.widget=CursorInteractor(self)
        self.widget.setObjectName('nativeOpenGLViewport');self.widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus);layout.addWidget(self.widget,1)
        self.renderer=vtkRenderer();self.renderer.SetBackground(.07,.105,.15);self.renderer.SetBackground2(.16,.22,.28);self.renderer.GradientBackgroundOn()
        # A single headlight gives perpendicular faces the same brightness in
        # an isometric view, hiding pockets and hollow interiors. Camera-relative
        # key/fill lights preserve depth cues through orbiting without shadows.
        self.renderer.AutomaticLightCreationOff();self.light_kit=vtkLightKit()
        for role in ('Key','Fill','Back','Head'):getattr(self.light_kit,'Set'+role+'LightWarmth')(.5)
        self.light_kit.SetKeyLightIntensity(.8);self.light_kit.AddLightsToRenderer(self.renderer)
        self.window=self.widget.GetRenderWindow();self.window.AddRenderer(self.renderer);self.window.SetMultiSamples(0)
        # Cover every render path, including VTK's native trackball orbit and
        # focusing a small part while the rest of the assembly remains visible.
        self.renderer.AddObserver('StartEvent',self.prepare_render_depth)
        from .assembly_display import AssemblyDisplay
        self.joints=AssemblyDisplay(self);self.rubber=QRubberBand(QRubberBand.Shape.Rectangle,self.widget)
        self.interactor=self.window.GetInteractor();self.style=CADStyle(self);self.style.SetDefaultRenderer(self.renderer);self.interactor.SetInteractorStyle(self.style)
        self.axes=vtkAxesActor();self.axes.SetShaftTypeToLine();self.axes_widget=vtkOrientationMarkerWidget();self.axes_widget.SetOrientationMarker(self.axes);self.axes_widget.SetInteractor(self.interactor);self.axes_widget.SetViewport(0,0,.13,.19)
        self.footer=QLabel('드래그: 회전 · Shift: 추가 선택 · Esc: 선택 해제 / 회전 · 아래 XYZ: 클릭 / 드래그로 시점 변경');self.footer.setWordWrap(True)
        self.footer.setStyleSheet('padding:7px 12px;background:#17232e;color:#92aabd;font-size:11px;');layout.addWidget(self.footer)
        from .display_style import preferences
        self.display_prefs=preferences();self.display_prefs.changed.connect(self.apply_display_style)
        self.make_grid(100);self.set_view('iso',render=False);QTimer.singleShot(0,self.initialize)

    def apply_display_style(self):
        if self.closed:return
        from PySide6.QtGui import QColor
        s=self.display_prefs.style
        if self.grid_actor:
            c=QColor(s.grid_color);p=self.grid_actor.GetProperty();p.SetColor(c.redF(),c.greenF(),c.blueF());p.SetOpacity(s.grid_brightness/100);p.SetLineWidth(s.grid_width)
        for axis in 'XYZ':
            c=QColor(getattr(s,axis.lower()+'_color'));rgb=(c.redF(),c.greenF(),c.blueF())
            for role in ('Shaft','Tip'):
                p=getattr(self.axes,'Get'+axis+'Axis'+role+'Property')();p.SetColor(*rgb);p.SetOpacity(s.axes_brightness/100);p.SetLineWidth(s.axes_width)
            p=getattr(self.axes,'Get'+axis+'AxisCaptionActor2D')().GetCaptionTextProperty();p.SetColor(*rgb);p.SetOpacity(s.axes_brightness/100)
        if self.initialized and self.isVisible():self.window.Render()

    def prepare_render_depth(self,*_):
        if self.closed:return
        extra=[]
        if self.handle and hasattr(self.handle,'overlay'):extra.append(self.handle.overlay.ComputeVisiblePropBounds())
        if hasattr(self,'joints'):extra.append(self.joints.renderer.ComputeVisiblePropBounds())
        reset_clipping(self.renderer,extra)

    def initialize(self):
        if self.closed:return
        self.widget.Initialize();self.initialized=True;self.axes_widget.SetEnabled(int(self.axes_visible));self.axes_widget.InteractiveOff();self.window.Render()

    def show_grid(self,visible):
        self.grid_visible=bool(visible)
        if self.grid_actor:self.grid_actor.SetVisibility(self.grid_visible)
        self.grid_label.setVisible(self.grid_visible)
        if self.initialized and not self.closed:self.window.Render()

    def show_axes(self,visible):
        self.axes_visible=bool(visible)
        if self.initialized and not self.closed:self.axes_widget.SetEnabled(int(visible));self.window.Render()

    def make_grid(self,extent):
        if self.grid_actor:self.renderer.RemoveActor(self.grid_actor)
        extent=max(50,float(extent));target=extent/10;power=10**math.floor(math.log10(target));step=next(n*power for n in (1,2,5,10) if n*power>=target);extent=math.ceil(extent/step)*step
        self.grid_spacing=step;self.grid_label.setText(f'1 grid = {step:g} mm');self.grid_label.setToolTip('격자 한 칸의 실제 길이 · mm');self.grid_label.setVisible(self.grid_visible)
        pts=vtkPoints();lines=vtkCellArray()
        for i in range(-int(extent/step),int(extent/step)+1):
            v=i*step
            for a,b in [((-extent,v,-.02),(extent,v,-.02)),((v,-extent,-.02),(v,extent,-.02))]:
                start=pts.InsertNextPoint(*a);end=pts.InsertNextPoint(*b);lines.InsertNextCell(2);lines.InsertCellPoint(start);lines.InsertCellPoint(end)
        mesh=vtkPolyData();mesh.SetPoints(pts);mesh.SetLines(lines);mapper=vtkPolyDataMapper();mapper.SetInputData(mesh);self.grid_actor=vtkActor();self.grid_actor.SetMapper(mapper);self.grid_actor.GetProperty().SetColor(.35,.49,.56);self.grid_actor.GetProperty().SetOpacity(.15);self.grid_actor.PickableOff();self.renderer.AddActor(self.grid_actor)
        self.grid_actor.SetVisibility(self.grid_visible)
        self.apply_display_style()

    def show_collisions(self):
        hits=(self.result or {}).get('stats',{}).get('collisions',[])
        if not hits:return
        names={m['id']:m.get('name',m['id']) for m in self.result['meshes']}
        ids={c[k] for c in hits for k in ('a','b')}
        for identifier in ids:
            self.visibility(identifier,True)
        self.select_many(list(ids))
        for identifier in ids:
            if identifier in self.actors:self.actors[identifier][0].GetProperty().SetColor(.9,.25,.16)
        self.window.Render()
        text='\n'.join(f"{names.get(c['a'],c['a'])} ↔ {names.get(c['b'],c['b'])}: {c['volume']:.4g} mm³" for c in hits[:30])
        QMessageBox.warning(self,'부품 간섭 경고',text+'\n\n빨간색 부품의 장착 위치·구멍·조립 여유를 확인하세요. 그룹화는 간섭을 없애지 않습니다. 불리언 연산의 보관된 도구 몸체는 의도된 중첩일 수 있습니다.')
    def update_metadata(self,result,fit=False):
        """Preserve VTK geometry and pick actors after a verified metadata edit."""
        if set(self.actors) != {mesh['id'] for mesh in result['meshes']}:
            raise ValueError('Metadata preview does not match the displayed geometry.')
        self.result=result
        self.meshes={mesh['id']:mesh for mesh in result['meshes']}
        for identifier,(actor,_) in self.actors.items():
            value=self.meshes[identifier]['color']
            actor.GetProperty().SetColor(*(int(value[i:i+2],16)/255 for i in (1,3,5)))
        self.select_many(self.selected_ids,False)
        if fit:self.fit()
        else:self.window.Render()

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
                    mapper=vtkPolyDataMapper();mapper.SetInputData(polydata(region['vertices'],region['triangles']));surface_offset(mapper)
                    actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.2,.85,.72);actor.GetProperty().SetOpacity(.07);self.renderer.AddActor(actor);self.profile_actors[actor]=(sketch['id'],region['index'])
            self.make_grid(max(result['stats']['bounds'])*1.2)
            s=result['stats'];self.caption.setText(f"{s['parts']}개 부품   ·   {' × '.join(f'{n:.2f}' for n in s['bounds'])} mm   ·   {s['volume']:,.2f} mm³")
            if result.get('sketches'):self.caption.setText(self.caption.text()+f"   ·   스케치 {len(result['sketches'])}개")
            if s['assembly_constraints']['mates']:self.caption.setText(self.caption.text()+f"   ·   조립 자유도 {s['assembly_constraints']['dof']}")
            if s['collisions']:self.caption.setText(self.caption.text()+f"   ·   간섭 {len(s['collisions'])}건")
        else:self.caption.setText('새 설계 · 스케치를 시작하거나 부품을 추가하세요.')
        hits=(result or {}).get('stats',{}).get('collisions',[])
        self.collision_button.setVisible(bool(hits));self.collision_button.setText(f'간섭 {len(hits)} · 확인')
        self.collision_button.setToolTip('부품 체적이 겹칩니다. 눌러 부품 이름·체적과 위치를 확인하세요. 그룹·숨김 상태와 관계없이 검사합니다.')
        self.rebuild_pick_objects()
        for key in self.hidden:self.visibility(key,False,False)
        self.select_many([i for i in self.selected_ids if i in self.actors],False)
        if fit:self.fit()
        else:self.window.Render()

    def clear_face(self):
        if self.highlight:self.renderer.RemoveActor(self.highlight);self.highlight=None
        self.face=None

    def pick(self,x,y,additive=False,body=False):
        if additive or body:
            picker=vtkCellPicker();picker.SetTolerance(.004);picker.PickFromListOn()
            for actor,identifier in self.actor_ids.items():
                if identifier not in self.hidden:picker.AddPickList(actor)
            identifier=self.actor_ids.get(picker.GetActor()) if picker.Pick(x,y,0,self.renderer) else None
            if identifier:self.parts_selected.emit([identifier],'toggle' if additive else 'replace')
            elif not additive:self.parts_selected.emit([],'replace')
            return
        if self.joints.pick(x,y):return
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
        if not picker.Pick(x,y,0,self.renderer):self.clear_face();self.parts_selected.emit([],'replace');self.window.Render();return
        if picker.GetActor() in self.sketch_actors:
            self.sketch_selected.emit(self.sketch_actors[picker.GetActor()]);return
        identifier=self.actor_ids.get(picker.GetActor())
        if not identifier:return
        mesh=self.meshes[identifier];index=picker.GetCellId()
        if index<0 or index>=len(mesh['triangle_faces']):return
        face_index=mesh['triangle_faces'][index];face=next((f for f in mesh['faces'] if f['index']==face_index),None)
        self.select(identifier,False);self.part_selected.emit(identifier)
        if self.selection_mode=='body' or len(self.selected_ids)>1:self.clear_face();self.window.Render();self.message.emit(mesh['name']+' · 부품 선택');return
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
            mapper=vtkPolyDataMapper();mapper.SetInputData(mesh);line_offset(mapper)
            actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.55,.7,.76);actor.GetProperty().SetLineWidth(2);actor.GetProperty().SetPointSize(10);actor.GetProperty().RenderPointsAsSpheresOn();self.renderer.AddActor(actor);self.edge_candidates[actor]=ref['index']
        self.footer.setText('모서리 클릭: 선택 / 해제 · 드래그: 회전 · 휠: 확대');self.window.Render()

    def highlight_edges(self,selected):
        for actor,index in self.edge_candidates.items():
            actor.GetProperty().SetColor(*((.35,.95,.7) if index in selected else (.55,.7,.76)));actor.GetProperty().SetLineWidth(4 if index in selected else 2)
        self.window.Render()

    def highlight_face(self,identifier,face_index):
        self.clear_face();mesh=self.meshes[identifier];triangles=np.asarray(mesh['triangles']).reshape(-1,3);mask=np.asarray(mesh['triangle_faces'])==face_index
        data=polydata(mesh['vertices'],triangles[mask]);mapper=vtkPolyDataMapper();mapper.SetInputData(data);surface_offset(mapper,-1)
        actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.95,.68,.22);actor.GetProperty().SetOpacity(.45);actor.PickableOff();self.highlight=actor;self.renderer.AddActor(actor);self.window.Render()

    def select(self,identifier,render=True):
        self.select_many([identifier] if identifier else [],render)

    def select_many(self,identifiers,render=True):
        self.selected_ids=list(identifiers);self.selected=identifiers[-1] if identifiers else None
        for key,(actor,edge) in self.actors.items():
            selected=key in identifiers;edge.GetProperty().SetColor(*((1,.67,.22) if selected else (.22,.35,.40)));edge.GetProperty().SetLineWidth(2.5 if selected else 1)
            edge.SetVisibility(key not in self.hidden and (self.show_edges or selected))
            actor.GetProperty().SetAmbient(.4 if selected else .24)
        if render:self.window.Render()

    def set_box_mode(self,enabled):
        self.box_mode=enabled;self.widget.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.message.emit('범위 선택: 왼쪽→오른쪽 완전 포함 · 오른쪽→왼쪽 닿는 부품 · Shift: 추가' if enabled else '드래그: 회전 · Shift+드래그: 범위 추가')

    def show_rubber(self,start,end):
        scale=self.widget.devicePixelRatioF();height=self.window.GetSize()[1]
        points=[QPoint(round(p[0]/scale),round((height-1-p[1])/scale)) for p in (start,end)]
        self.rubber.setGeometry(QRect(*points).normalized());self.rubber.show()

    def box_pick(self,start,end,additive=False):
        from .box_selection import projected_selection
        camera=self.renderer.GetActiveCamera();m=camera.GetCompositeProjectionTransformMatrix(self.renderer.GetTiledAspectRatio(),0,1)
        matrix=np.array([[m.GetElement(i,j) for j in range(4)] for i in range(4)])
        ids=projected_selection(self.meshes,self.hidden,matrix,self.window.GetSize(),start,end)
        self.parts_selected.emit(ids,'add' if additive else 'replace');return ids

    def visibility(self,identifier,visible,render=True):
        if visible:self.hidden.discard(identifier)
        else:self.hidden.add(identifier)
        if identifier in self.actors:
            actor,edge=self.actors[identifier];actor.SetVisibility(visible);edge.SetVisibility(visible and self.show_edges)
        self.rebuild_pick_objects()
        if render:self.window.Render()

    def set_hidden_parts(self,identifiers,render=True):
        """Batch visibility changes so a role view rebuilds picking just once."""
        self.hidden=set(identifiers)
        for identifier,(actor,edge) in self.actors.items():
            visible=identifier not in self.hidden
            actor.SetVisibility(visible)
            edge.SetVisibility(visible and (self.show_edges or identifier in self.selected_ids))
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

    def zoom_at_cursor(self,position,factor):
        from .navigation import zoom_camera
        picker=vtkCellPicker();picker.SetTolerance(.002);picker.PickFromListOn()
        for identifier,(actor,_) in self.actors.items():
            if identifier not in self.hidden:picker.AddPickList(actor)
        anchor=picker.GetPickPosition() if picker.Pick(*position,0,self.renderer) else None
        zoom_camera(self.renderer,position,factor,anchor)
        self.window.Render()

    def set_view(self,name,render=True):
        camera=self.renderer.GetActiveCamera();camera.ParallelProjectionOn()
        directions={'iso':((1,-1,1), (0,0,1)),'top':((0,0,1),(0,1,0)),'front':((0,-1,0),(0,0,1)),'right':((1,0,0),(0,0,1))}
        position,up=directions[name];camera.SetPosition(*[v*200 for v in position]);camera.SetFocalPoint(0,0,0);camera.SetViewUp(*up)
        if render:self.fit()

    def axis_points(self):
        renderer=self.axes_widget.GetRenderer();points={}
        for name,p in [('origin',(0,0,0)),('x',(1,0,0)),('y',(0,1,0)),('z',(0,0,1))]:
            renderer.SetWorldPoint(*p,1);renderer.WorldToDisplay();points[name]=np.array(renderer.GetDisplayPoint()[:2])
        return points

    def axis_at(self,pos):
        if not self.axes_visible:return None
        width,height=self.window.GetSize();left,bottom,right,top=self.axes_widget.GetViewport()
        if not (left*width<=pos[0]<=right*width and bottom*height<=pos[1]<=top*height):return None
        points=self.axis_points();p=np.array(pos);origin=points['origin'];tolerance=12*self.widget.devicePixelRatioF()
        if np.linalg.norm(p-origin)<tolerance*.55:
            camera=self.renderer.GetActiveCamera();direction=np.array(camera.GetPosition())-camera.GetFocalPoint();direction/=max(np.linalg.norm(direction),1e-9)
            return 'xyz'[int(np.argmax(np.abs(direction)))] if max(np.abs(direction))>.999 else 'origin'
        hits=[]
        for key in ('x','y','z'):
            v=points[key]-origin;length=float(v@v)
            if length<1:continue
            t=np.clip(float((p-origin)@v/length),0,1.25);distance=np.linalg.norm(p-(origin+t*v))
            if distance<=tolerance:hits.append((distance,key))
        return min(hits)[1] if hits else None

    def orient_axis(self,axis):
        camera=self.renderer.GetActiveCamera();focus=np.array(camera.GetFocalPoint());distance=max(camera.GetDistance(),1)
        if axis=='origin':direction=np.array([1.,-1.,1.]);direction/=np.linalg.norm(direction);up=(0,0,1)
        else:
            direction=np.eye(3)['xyz'.index(axis)];current=np.array(camera.GetPosition())-focus;current/=max(np.linalg.norm(current),1e-9)
            if np.dot(current,direction)>.999:direction=-direction
            up=(0,1,0) if axis=='z' else (0,0,1)
        camera.SetPosition(*(focus+direction*distance));camera.SetViewUp(*up);camera.OrthogonalizeViewUp();self.renderer.ResetCameraClippingRange();self.window.Render()
        self.message.emit('등각 시점' if axis=='origin' else axis.upper()+'축 시점 · 다시 누르면 반대 방향')

    def shutdown(self):
        if self.closed:return
        self.closed=True
        if self.handle:self.handle.close()
        self.joints.close()
        # Disconnect the VTK -> Python -> QWidget cycle while the Qt window
        # still exists. Otherwise later garbage collection may release an
        # OpenGL interactor after Qt has destroyed its native HWND.
        self.axes_widget.SetEnabled(0);self.axes_widget.SetInteractor(None)
        self.style.RemoveAllObservers();self.style.owner=None;self.interactor.SetInteractorStyle(None);self.interactor.Disable()
        self.widget._Timer.stop();self.interactor.RemoveAllObservers();self.window.RemoveAllObservers();self.renderer.RemoveObservers('StartEvent');self.renderer.RemoveAllViewProps();self.widget.Finalize()
