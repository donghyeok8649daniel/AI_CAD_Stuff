"""View-only isolation/explosion and independent component export."""
from copy import deepcopy
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,QToolBar,QFileDialog
from .viewport import CADViewport
from .widgets import label,button,number
from .role_view import RoleViewUI


def exploded_preview(result,distance,axis='z'):
    data=deepcopy(result);meshes=data['meshes']
    if not meshes:return data
    coordinate='xyz'.index(axis);ordered=sorted(meshes,key=lambda m:np.asarray(m['vertices']).reshape(-1,3)[:,coordinate].mean())
    lows=[];highs=[]
    for rank,mesh in enumerate(ordered):
        offset=np.zeros(3);offset[coordinate]=(rank-(len(ordered)-1)/2)*distance
        points=np.asarray(mesh['vertices'],dtype=float).reshape(-1,3)+offset
        mesh['vertices']=points.tolist();lows.append(points.min(axis=0));highs.append(points.max(axis=0))
    low=np.min(lows,axis=0);high=np.max(highs,axis=0)
    data['stats'].update(min=low.tolist(),max=high.tolist(),bounds=(high-low).tolist())
    data['sketches']=[]
    return data


class ExplodedViewDialog(QDialog):
    def __init__(self,parent,result):
        super().__init__(parent);self.setWindowTitle('분해 보기 · 원래 조립 위치 유지');self.resize(1000,740);self.setMinimumSize(820,600);self.base=deepcopy(result)
        layout=QVBoxLayout(self);layout.addWidget(label('보기 전용 · 조립 구속과 저장된 위치는 바뀌지 않습니다. 닫으면 원래 설계로 돌아갑니다.',True))
        row=QHBoxLayout();self.axis=QComboBox()
        for key in 'xyz':self.axis.addItem(key.upper()+' 방향으로 펼치기',key)
        self.axis.setCurrentIndex(2);row.addWidget(self.axis);self.distance=number(30,0,2000,' mm');row.addWidget(label('부품 간 추가 간격'));row.addWidget(self.distance);row.addWidget(button('조립 상태',lambda:self.distance.setValue(0)));layout.addLayout(row)
        self.viewport=CADViewport();self.viewport.setMinimumHeight(300);self.viewport.filter.setEnabled(False);layout.addWidget(self.viewport,1)
        row=QHBoxLayout();row.addStretch();row.addWidget(button('닫기',self.accept,True));layout.addLayout(row)
        self.axis.currentIndexChanged.connect(self.refresh);self.distance.valueChanged.connect(self.refresh);QTimer.singleShot(0,self.refresh)

    def refresh(self):
        if self.viewport.closed:return
        self.viewport.load(exploded_preview(self.base,self.distance.value(),self.axis.currentData()))
        self.viewport.orbit_mode=True;self.viewport.caption.setText(f"분해 미리보기 · {len(self.base['meshes'])}개 부품 · 원본 변경 없음")
        self.viewport.footer.setText('보기 전용 · 드래그: 회전 · 휠: 확대 · XYZ: 시점 변경 · 닫기: 원래 조립으로 돌아가기')

    def done(self,result):self.viewport.shutdown();super().done(result)


class PartInspectionUI(RoleViewUI):
    def make_inspection_tools(self,edit,assembly):
        self.isolation_hidden=None
        bar=QToolBar('부품 보기 / 내보내기',self.viewport);bar.setObjectName('partInspectionToolbar');bar.setMovable(False)
        for key,title,fn in [('isolate','선택만 보기',self.isolate_parts),('show_all','모두 보기',self.show_all_parts),('explode','분해 보기',self.explode_parts),('export_parts','부품별 내보내기',self.export_selected_parts)]:
            action=self.action(key,title,fn);bar.addAction(action);assembly.addAction(action)
        self.actions['isolate'].setCheckable(True);self.actions['isolate'].setToolTip('선택 부품만 표시 · 다시 누르면 이전 표시 상태로 복귀')
        self.viewport.layout().insertWidget(3,bar);self.inspection_toolbar=bar
        self.make_role_view_tools(assembly)

    def isolate_parts(self):
        self.reset_role_view()
        if self.isolation_hidden is not None:
            hidden=self.isolation_hidden;self.isolation_hidden=None;self.actions['isolate'].setChecked(False)
        else:
            ids=self.selected_ids()
            if not ids:self.actions['isolate'].setChecked(False);self.message('따로 볼 부품을 먼저 선택하세요. 그룹 선택을 끄면 한 부품만 고를 수 있습니다.');return
            self.isolation_hidden=set(self.viewport.hidden);hidden=set(self.viewport.actors)-set(ids);self.actions['isolate'].setChecked(True)
        self.viewport.set_hidden_parts(hidden,False)
        self.viewport.window.Render();self.rebuild_tree();self.sync_tree_selection()

    def show_all_parts(self):
        self.reset_role_view()
        self.isolation_hidden=None;self.actions['isolate'].setChecked(False)
        self.viewport.set_hidden_parts(set(),False)
        self.viewport.window.Render();self.rebuild_tree();self.sync_tree_selection()

    def explode_parts(self):
        if self.busy or not self.result or not self.result['meshes']:self.message('먼저 입체 부품을 만드세요.');return
        data=deepcopy(self.result);ids=self.selected_ids()
        if ids:data['meshes']=[m for m in data['meshes'] if m['id'] in ids]
        ExplodedViewDialog(self,data).exec()

    def export_selected_parts(self):
        if self.busy or not self.document.design:return
        ids=self.selected_ids()
        if not ids:self.message('내보낼 부품을 먼저 선택하세요. Ctrl+A로 전체 부품을 선택할 수 있습니다.');return
        dialog=QDialog(self);dialog.setWindowTitle('선택 부품별 내보내기');layout=QVBoxLayout(dialog)
        layout.addWidget(label(f'{len(ids)}개 부품을 각각 파일로 만들어 ZIP으로 저장합니다.\n3D 프린팅은 STL, CAD 교환은 STEP을 선택하세요.',True));form=QFormLayout();layout.addLayout(form)
        fmt=QComboBox();fmt.addItem('STEP + STL',('step','stl'));fmt.addItem('STEP',('step',));fmt.addItem('STL',('stl',));form.addRow('파일 형식',fmt)
        placement=QComboBox();placement.addItem('부품별 원점 · XY 중심 / 바닥 Z=0','local');placement.addItem('현재 조립 위치 유지','assembly');form.addRow('배치',placement)
        row=QHBoxLayout();row.addWidget(button('취소',dialog.reject));row.addWidget(button('저장 위치 선택',dialog.accept,True));layout.addLayout(row)
        if not dialog.exec():return
        path,_=QFileDialog.getSaveFileName(self,'부품 파일 ZIP 저장',str(Path.home()/'Documents'/'CAD-parts.zip'),'ZIP (*.zip)')
        if not path:return
        target=Path(path if path.lower().endswith('.zip') else path+'.zip');raw=deepcopy(self.document.design);formats=fmt.currentData();where=placement.currentData()
        from ..part_export import export_parts
        self.run(lambda:export_parts(raw,ids,target,formats,where),lambda result:self.message(f"{len(result['parts'])}개 부품 내보내기 완료: {target}"),'부품별 형상 내보내는 중…')
