"""Reorder, insert, and suppress features with validated previews."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget,QListWidgetItem,QHBoxLayout,QCheckBox,QDialog
from .workflows import PreviewDialog
from .widgets import button,label


def reorder_features(raw,part_id,index,destination):
    raw=deepcopy(raw);part=next(p for p in raw['parts'] if p['id']==part_id);features=part['features']
    if not 0<=index<len(features) or not 0<=destination<len(features):raise ValueError('이동할 피처 위치가 잘못됐습니다.')
    features.insert(destination,features.pop(index));previous='base'
    for f in features:f['support_feature']=previous;previous=f['id']
    return raw


class FeatureManager(PreviewDialog):
    def __init__(self,parent,design,part_id):
        super().__init__(parent,'피처 순서 / 억제','순서를 바꾸거나 피처를 끄고 실제 결과를 확인하세요. 참조가 맞지 않으면 적용되지 않습니다.')
        self.raw=deepcopy(design);self.part_id=part_id;self.list=QListWidget();self.list.setMinimumHeight(230);self.controls.addWidget(self.list)
        row=QHBoxLayout();row.addWidget(button('↑ 앞으로',lambda:self.move(-1)));row.addWidget(button('↓ 뒤로',lambda:self.move(1)));self.controls.addLayout(row)
        self.following=QCheckBox('선택한 피처 뒤의 작업도 함께 억제 / 복원');self.following.setChecked(True);self.controls.addWidget(self.following)
        self.controls.addWidget(button('선택 피처 앞에 솔리드 작업 삽입',self.insert));self.controls.addWidget(label('체크한 피처를 계산합니다. 체크 해제는 임시 억제이며 입력값과 기록을 지우지 않습니다. 앞선 작업을 삭제·이동해 참조가 달라지면 면 재선택이 필요할 수 있습니다.',True));self.controls.addStretch();self.list.itemChanged.connect(self.toggle);self.refresh();self.schedule()

    def features(self):return next(p for p in self.raw['parts'] if p['id']==self.part_id)['features']
    def refresh(self,index=0):
        self.list.blockSignals(True);self.list.clear()
        for i,f in enumerate(self.features()):
            item=QListWidgetItem(f"{i+1:02d}. {f['name']}");item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Unchecked if f.get('suppressed') else Qt.CheckState.Checked);self.list.addItem(item)
        self.list.setCurrentRow(index);self.list.blockSignals(False)
    def move(self,offset):
        index=self.list.currentRow();destination=index+offset
        if not 0<=destination<len(self.features()):return
        self.raw=reorder_features(self.raw,self.part_id,index,destination);self.refresh(destination);self.schedule()
    def toggle(self,item):
        index=self.list.row(item);suppressed=item.checkState()!=Qt.CheckState.Checked
        for f in self.features()[index:index+1 if not self.following.isChecked() else None]:f['suppressed']=suppressed
        self.refresh(index);self.schedule()
    def insert(self):
        from .solid_dialog import SolidDialog
        index=self.list.currentRow();index=len(self.features()) if index<0 else index
        dialog=SolidDialog(self,self.raw,self.part_id,insert_index=index)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.raw=dialog.checked.model_dump();self.refresh(index);self.schedule()
    def candidate(self):return deepcopy(self.raw)
