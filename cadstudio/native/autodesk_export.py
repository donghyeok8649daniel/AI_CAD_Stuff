"""Native export entry points with an explicit official-app conversion boundary."""
import os
from pathlib import Path
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QFileDialog
from .widgets import label,button,Worker
from .workflows import choice
from ..native_export import inventor_installed,prepare_native_export,convert_ipt_job


class AutodeskExportDialog(QDialog):
    def __init__(self,parent,project,fmt,selected=None):
        super().__init__(parent);self.setWindowTitle(fmt.upper()+' 내보내기');self.resize(660,420);self.project=project;self.fmt=fmt;self.running=False;self.folder=None;self.has_inventor=inventor_installed()
        v=QVBoxLayout(self);v.addWidget(label('Inventor 부품 · IPT' if fmt=='ipt' else 'Fusion 아카이브 · F3D'));self.part=choice([(p.id,p.name) for p in project.design.parts]);self.part.setVisible(fmt=='ipt');v.addWidget(self.part)
        if selected:self.part.setCurrentIndex(max(0,self.part.findData(selected)))
        info=('설치된 Inventor로 선택 부품을 변환합니다.' if self.has_inventor else 'Inventor가 감지되지 않았습니다. 변환 준비 파일을 만든 뒤 Inventor가 설치된 PC에서 변환할 수 있습니다.') if fmt=='ipt' else 'Fusion에서 실행할 변환 스크립트와 STEP을 함께 준비합니다. Fusion의 스크립트 및 애드인에서 폴더를 등록하고 실행하면 지정한 F3D로 저장합니다.'
        v.addWidget(label(info,True));v.addWidget(label('실제 파일은 Autodesk 앱이 생성합니다. 원본 스케치·구속·피처 기록은 함께 저장하는 CAD 프로젝트에 보존하며 Autodesk 타임라인으로 재구성하지 않습니다.',True))
        row=QHBoxLayout();self.path=QLineEdit();self.path.setPlaceholderText('새 파일로 저장할 경로');row.addWidget(self.path,1);row.addWidget(button('저장 위치',self.browse));v.addLayout(row)
        self.status=label('저장 위치를 선택하세요.');v.addWidget(self.status,1);row=QHBoxLayout();self.start=button('IPT 변환' if fmt=='ipt' and self.has_inventor else '변환 준비',self.prepare,True);row.addWidget(self.start);self.open_folder=button('준비 폴더 열기',self.open_prepared);self.open_folder.setEnabled(False);row.addWidget(self.open_folder);row.addWidget(button('닫기',self.reject));v.addLayout(row)
    def browse(self):
        path,_=QFileDialog.getSaveFileName(self,'새 '+self.fmt.upper()+' 경로',str(Path.home()/'Documents'/('design.'+self.fmt)),self.fmt.upper()+' (*.'+self.fmt+')')
        if path:self.path.setText(path if path.lower().endswith('.'+self.fmt) else path+'.'+self.fmt)
    def prepare(self):
        if self.running:return
        target=Path(self.path.text())
        if not target.is_absolute() or target.suffix.lower()!='.'+self.fmt:self.status.setText('저장 위치 버튼으로 올바른 경로를 선택하세요.');return
        self.running=True;self.start.setEnabled(False);self.status.setText('정확한 CAD 형상으로 변환 준비 중…');part=self.part.currentData()
        def work():
            folder=prepare_native_export(self.project,target,part)
            error=None;converted=None
            if self.fmt=='ipt' and self.has_inventor:
                try:converted=convert_ipt_job(folder)
                except Exception as exc:error=str(exc)
            return folder,converted,error
        self.worker=Worker(work);self.worker.signals.done.connect(self.prepared);self.worker.signals.failed.connect(self.failed);QThreadPool.globalInstance().start(self.worker)
    def prepared(self,result):
        self.running=False;self.start.setEnabled(True);self.folder,converted,error=result;self.open_folder.setEnabled(True)
        self.status.setText(error or ('IPT 저장 완료: '+str(converted) if converted else '준비 완료: '+str(self.folder)+('\nFusion → 스크립트 및 애드인 → PromptCADImport 폴더 추가 → 실행' if self.fmt=='f3d' else '\nInventor PC에서 ConvertSingleToIpt.ps1을 실행하세요.')))
    def failed(self,error):self.running=False;self.start.setEnabled(True);self.status.setText(error)
    def open_prepared(self):
        if self.folder:os.startfile(self.folder)
    def reject(self):
        if self.running:self.status.setText('현재 변환 작업이 끝난 뒤 닫아주세요.');return
        super().reject()
