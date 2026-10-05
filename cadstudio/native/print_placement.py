"""Direct manipulation of a checked print snapshot, never the design document."""
import numpy as np
from vtkmodules.vtkRenderingCore import vtkCellPicker
from .navigation import unproject


class PrintPlacementHandle:
    def __init__(self,dialog):
        self.dialog=dialog;self.view=dialog.viewport;self.drag=None;self.changed=False
        self.view.handle=self
    def plane(self,pos):
        a=unproject(self.view.renderer,*pos,0);b=unproject(self.view.renderer,*pos,1)
        if abs(b[2]-a[2])<1e-8:return None
        return a+(b-a)*(-a[2]/(b[2]-a[2]))
    def press(self,pos):
        d=self.dialog
        if d.running or d.checked is None or not d.drag_enabled.isChecked():return False
        picker=vtkCellPicker();picker.PickFromListOn();picker.SetTolerance(.003)
        for actor,_ in self.view.actors.values():picker.AddPickList(actor)
        if not picker.Pick(*pos,0,self.view.renderer):return False
        identifier=self.view.actor_ids.get(picker.GetActor());point=self.plane(pos)
        if identifier is None or point is None:return False
        d.active_part.setCurrentIndex(d.active_part.findData(identifier))
        self.drag=(identifier,point,dict(d.placements[identifier]));self.changed=False
        return True
    def move(self,pos):
        if self.drag is None:return False
        point=self.plane(pos)
        if point is None:return True
        identifier,start,pose=self.drag;delta=point-start
        if not self.changed and np.linalg.norm(delta)<1e-5:return True
        if not self.changed:
            self.dialog.schedule();self.dialog.timer.stop();self.changed=True
            self.dialog.status.setText('배치 중 · 마우스를 놓으면 간섭과 출력 영역을 다시 검사합니다.')
        for actor in self.view.actors[identifier]:actor.SetPosition(float(delta[0]),float(delta[1]),0)
        self.dialog.placements[identifier]={**pose,'x':pose['x']+float(delta[0]),'y':pose['y']+float(delta[1])}
        self.dialog.sync_pose();self.view.render();return True
    def release(self):
        if self.drag is None:return False
        self.drag=None
        if self.changed:self.dialog.schedule()
        self.changed=False;return True
    def close(self):
        self.drag=None;self.view.handle=None
