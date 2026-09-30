"""One keyboard search for model objects and CAD commands."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLineEdit,QListWidget,QListWidgetItem,QComboBox
from .widgets import label


def search_rows(window):
    raw=window.document.design or {};rows=[]
    for part in raw.get('parts',[]):
        rows.append(('part',part['id'],None,part['name']+' · '+part['id']))
        for feature in part.get('features',[]):
            rows.append(('feature',part['id'],feature['id'],part['name']+' / '+feature.get('name',feature['id'])+' · '+feature.get('kind',feature.get('operation',''))))
    for group in raw.get('part_groups',[]):rows.append(('group',group['id'],None,group['name']))
    for sketch in raw.get('sketches',[]):rows.append(('sketch',sketch['id'],None,sketch['name']))
    names={p['id']:p['name'] for p in raw.get('parts',[])}
    for joint in raw.get('mates',[]):rows.append(('joint',joint['id'],None,joint['kind']+' · '+names.get(joint['parent'],joint['parent'])+' → '+names.get(joint['child'],joint['child'])))
    for key,action in window.actions.items():
        if key not in ('search','find') and action.isEnabled():rows.append(('command',key,None,action.text().replace('&','')))
    return rows


class SearchDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent);self.setWindowTitle('부품 / 기능 검색 · Ctrl+F');self.resize(640,520);self.rows=search_rows(parent);self.result_row=None
        root=QVBoxLayout(self);self.query=QLineEdit();self.query.setPlaceholderText('부품 이름, 구멍, 측정, fillet…');root.addWidget(self.query)
        self.kind=QComboBox()
        for title,key in [('전체','all'),('부품','part'),('피처','feature'),('기능 / 명령','command'),('그룹','group'),('스케치','sketch'),('관절','joint')]:self.kind.addItem(title,key)
        root.addWidget(self.kind);self.items=QListWidget();root.addWidget(self.items,1);root.addWidget(label('↑↓로 선택 · Enter: 부품/피처 선택 또는 기능 실행 · Esc: 닫기',True))
        self.query.textChanged.connect(self.update_results);self.kind.currentIndexChanged.connect(self.update_results)
        self.query.returnPressed.connect(self.activate);self.items.itemActivated.connect(self.activate)
        self.update_results();self.query.setFocus()

    def update_results(self):
        self.items.clear();terms=self.query.text().casefold().split();kind=self.kind.currentData()
        for row in self.rows:
            haystack=(row[3]+' '+row[0]+' '+row[1]).casefold()
            if (kind=='all' or row[0]==kind) and all(t in haystack for t in terms):
                item=QListWidgetItem('['+{'part':'부품','feature':'피처','command':'기능','group':'그룹','sketch':'스케치','joint':'관절'}[row[0]]+'] '+row[3]);item.setData(Qt.ItemDataRole.UserRole,row);self.items.addItem(item)
        if self.items.count():self.items.setCurrentRow(0)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Down,Qt.Key.Key_Up):
            delta=1 if event.key()==Qt.Key.Key_Down else -1
            self.items.setCurrentRow(max(0,min(self.items.count()-1,self.items.currentRow()+delta)));return
        super().keyPressEvent(event)

    def activate(self,item=None):
        item=item or self.items.currentItem()
        if not item:return
        self.result_row=item.data(Qt.ItemDataRole.UserRole);self.accept()


def activate_result(window,row):
    kind,identifier,feature_id,_=row
    if kind=='command':
        action=window.actions.get(identifier)
        if action and action.isEnabled():QTimer.singleShot(0,action.trigger)
        return
    if window.busy or window.sketching:return
    if kind in ('part','feature'):
        window.leave_orbit();window.viewport.visibility(identifier,True);window.select_parts([identifier])
        if kind=='feature':window.show_feature(feature_id)
    elif kind=='group':
        group=next((g for g in window.document.design.get('part_groups',[]) if g['id']==identifier),None)
        if group:window.select_parts(group['part_ids'])
    elif kind=='sketch':window.select_sketch(identifier)
    elif kind=='joint':window.show_mate(identifier)
