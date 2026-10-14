"""Independent readonly viewport; replay never mutates Document or its actors."""
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QDialog,QHBoxLayout,QLabel,QSlider,QVBoxLayout
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from ..firmware_motion import checked_motion,pose_at,actor_matrices
from ..preview_metadata import geometry_key
from ..program_drive_adapter import fingerprint
from .viewport import CADViewport
from .widgets import button


class FirmwareMotionDialog(QDialog):
    def __init__(self,design,image,result,meshes,parent=None,language='ko',document_provider=None):
        super().__init__(parent)
        self.base,self.spec,self.trace=checked_motion(design,image,result)
        self.document_provider=document_provider;self.document_digest=None if document_provider is None else fingerprint(document_provider());self.invalidated=False
        self.en=language=='en'
        if meshes.get('_geometry_key')!=geometry_key(self.base):raise ValueError('Loaded viewport geometry differs from the ELF drive contract.')
        self.setWindowTitle(self.word('G474 가상 펌웨어 → 모터·나사·크로스헤드','G474 virtual firmware → motor, screw and crosshead'));self.resize(1100,760)
        layout=QVBoxLayout(self);self.note=QLabel(self.word('ARM 코드가 만든 위치·명령을 재생합니다. 선언한 가상 속도 서보·카운터 입력이며 실물 모터 검증이 아닙니다.','Replay positions and commands produced by ARM code. Declared virtual velocity servo and counter input; no physical motor validation.'));self.note.setWordWrap(True);layout.addWidget(self.note)
        self.viewport=CADViewport(self);self.viewport.load(meshes);layout.addWidget(self.viewport,1)
        self.label=QLabel();layout.addWidget(self.label)
        self.slider=QSlider(Qt.Orientation.Horizontal);self.slider.setRange(0,len(self.trace)-1);self.slider.valueChanged.connect(self.show_frame);layout.addWidget(self.slider)
        row=QHBoxLayout();self.play_button=button(self.word('재생 / 일시정지','Play / pause'),self.toggle);row.addWidget(self.play_button);row.addStretch();row.addWidget(button(self.word('닫기','Close'),self.reject));layout.addLayout(row)
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.advance);self.show_frame(0)
    def word(self,ko,en):return en if self.en else ko
    def invalidate(self,message):
        self.invalidated=True;self.timer.stop();self.play_button.setEnabled(False);self.slider.setEnabled(False);self.label.setText(message)
        for actors in self.viewport.actors.values():
            for actor in actors:actor.SetUserMatrix(None)
        self.viewport.render()
    def current_unchanged(self):
        if self.invalidated:return False
        try:valid=self.document_provider is None or fingerprint(self.document_provider())==self.document_digest
        except (TypeError,ValueError,AttributeError):valid=False
        if not valid:self.invalidate(self.word('현재 설계가 바뀌어 이전 펌웨어 재생을 중단했습니다.','Current design changed; old firmware replay stopped.'))
        return valid
    def show_frame(self,index):
        if not self.current_unchanged():return
        row=self.trace[index]
        try:pose=pose_at(self.base,self.spec,row)
        except (ValueError,TypeError) as exc:self.invalidate(str(exc));return
        for key,matrix in actor_matrices(self.base,pose).items():
            vtk_matrix=vtkMatrix4x4()
            for i in range(4):
                for j in range(4):vtk_matrix.SetElement(i,j,float(matrix[i,j]))
            for actor in self.viewport.actors.get(key,()):actor.SetUserMatrix(vtk_matrix)
        self.viewport.render()
        self.label.setText(f"{self.word('가상','Virtual')} {row['time_s']:.3f}s · {self.word('이동','Position')} {row['position_mm']:.4f} mm · {self.word('속도','Speed')} {row['speed_mm_s']:.4f} mm/s · {self.word('나사','Screw')} {row['screw_angle_deg']:.3f}° · {self.word('명령','Command')} {row['command_mm_s']:.3f} mm/s · virtual enable {row['virtual_enable']}")
    def toggle(self):
        if not self.current_unchanged():return
        if self.timer.isActive():self.timer.stop()
        else:
            if self.slider.value()==self.slider.maximum():self.slider.setValue(0)
            self.timer.start()
    def advance(self):
        if not self.current_unchanged():return
        if self.slider.value()>=self.slider.maximum():self.timer.stop();return
        step=max(1,round(.05/self.spec.sample_step_s));self.slider.setValue(min(self.slider.maximum(),self.slider.value()+step))
    def done(self,value):
        self.timer.stop();self.viewport.shutdown();super().done(value)
