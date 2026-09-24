"""Visible selection tools and focus-aware native clipboard operations."""
import json
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QAction
from PySide6.QtWidgets import QApplication,QAbstractItemView,QToolBar,QMenu,QTreeWidgetItemIterator,QLineEdit,QColorDialog
from ..part_operations import group_parts,ungroup_parts,part_clipboard,paste_parts,delete_parts
from .widgets import label,button,clear_layout
from . import clipboard

PART_MIME='application/x-promptcad-parts-v1'
CLIPBOARD_LIMIT=32_000_000


class PartSelectionUI:
    def make_selection_tools(self,edit,assembly):
        edit.addAction(self.action('move_parts','이동 / 회전 · M',self.move_parts))
        for key,title,fn in [('copy','복사 · Ctrl+C',self.copy_parts),('cut','잘라내기 · Ctrl+X',self.cut_parts),('paste','붙여넣기 · Ctrl+V',self.paste_parts),('select_all','모든 부품 선택 · Ctrl+A',self.select_all_parts),('group','그룹 · Ctrl+G',self.group_parts),('ungroup','그룹 해제 · Ctrl+Shift+G',self.ungroup_parts)]:
            edit.addAction(self.action(key,title,fn))
        assembly.addAction(self.action('joints','관절 표시 · J',self.toggle_joints));self.actions['joints'].setCheckable(True)
        self.action('box_select','범위 선택 · B',lambda:self.viewport.set_box_mode(self.actions['box_select'].isChecked()));self.actions['box_select'].setCheckable(True)
        self.action('group_select','그룹 단위 선택',lambda:None);self.actions['group_select'].setCheckable(True);self.actions['group_select'].setChecked(True)
        edit.addAction(self.actions['group_select'])
        bar=QToolBar('선택 / 조립 표시',self.viewport);bar.setObjectName('selectionToolbar');bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly);bar.setMovable(False)
        for key,title in [('move_parts','이동 M'),('joints','관절 J'),('box_select','범위 B'),('group','그룹'),('ungroup','해제'),('group_select','그룹 선택')]:
            source=self.actions[key];compact=QAction(title,bar);compact.setCheckable(source.isCheckable());compact.setChecked(source.isChecked());compact.setToolTip(source.text());compact.triggered.connect(source.trigger)
            def sync(a=source,b=compact):b.setEnabled(a.isEnabled());b.setChecked(a.isChecked())
            source.changed.connect(sync);bar.addAction(compact)
            if key=='joints':self.joint_toolbar_action=compact
        self.viewport.layout().insertWidget(2,bar);self.selection_toolbar=bar
        self.viewport.parts_selected.connect(self.select_clicked_parts)
        self.viewport.joint_selected.connect(self.inspect_connection)

    def prepare_tree_selection(self):
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self.tree_selection_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.selection_menu)
        self.viewport.widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewport.widget.customContextMenuRequested.connect(lambda pos:self.selection_menu(pos,self.viewport.widget))

    def selection_menu(self,pos,widget=None):
        menu=QMenu(self)
        for key in ('move_parts','copy','cut','paste','group','ungroup','group_select','color','delete'):menu.addAction(self.actions[key])
        menu.exec((widget or self.tree).mapToGlobal(pos))

    def selected_ids(self):
        return [p['id'] for p in (self.document.design or {}).get('parts',[]) if p['id'] in self.selected_parts]

    def move_parts(self):
        if self.busy or self.sketching:return
        ids=self.selected_ids()
        if not ids:self.message('이동할 부품을 선택하세요. Shift+클릭으로 여러 부품을 선택할 수 있습니다.');return
        from .placement_dialog import PlacementDialog
        dialog=PlacementDialog(self,self.document.design,ids)
        if dialog.exec() and dialog.checked:
            payload=dialog.candidate();payload.pop('raw')
            self.apply_design(dialog.checked.model_dump(),'부품 이동 / 회전',payload,
                              after=lambda:self.select_parts(dialog.moved_ids))

    def expand_groups(self,ids):
        chosen=set(ids)
        if self.actions['group_select'].isChecked():
            for g in (self.document.design or {}).get('part_groups',[]):
                if chosen.intersection(g['part_ids']):chosen.update(i for i in g['part_ids'] if i not in self.viewport.hidden)
        return [p['id'] for p in (self.document.design or {}).get('parts',[]) if p['id'] in chosen]

    def select_parts(self,ids,mode='replace',sync=True):
        if self.busy:return
        ids=[i for i in dict.fromkeys(ids) if any(p['id']==i for p in (self.document.design or {}).get('parts',[]))]
        current=list(self.selected_parts)
        if mode=='toggle':ids=[i for i in current if i not in ids] if ids and set(ids)<=set(current) else list(dict.fromkeys([*current,*ids]))
        elif mode=='add':ids=list(dict.fromkeys([*current,*ids]))
        self.selected_parts=ids;self.selected=ids[-1] if ids else None;self.selected_sketch=None;self.selected_profile=None
        self.viewport.clear_face();self.viewport.select_many(ids)
        if sync:self.sync_tree_selection()
        self.show_properties()
        if ids and not self.sketching:self.property_dock.show();self.property_dock.raise_()
        self.message(f'{len(ids)}개 부품 선택 · Shift+클릭: 추가/해제 · Shift+드래그: 범위 추가 · Ctrl+G: 그룹')

    def select_clicked_parts(self,ids,mode='replace'):
        exact=self.joint_picks is not None or self.viewport.selection_mode in ('point','edge','face')
        self.select_parts(ids if exact else self.expand_groups(ids),mode)

    def select_all_parts(self):
        self.select_parts([p['id'] for p in (self.document.design or {}).get('parts',[]) if p['id'] not in self.viewport.hidden])

    def sync_tree_selection(self):
        self.tree.blockSignals(True);it=QTreeWidgetItemIterator(self.tree)
        while it.value():
            item=it.value();data=item.data(0,Qt.ItemDataRole.UserRole)
            item.setSelected(bool(data and data[0]=='part' and data[1] in self.selected_parts));it+=1
        self.tree.blockSignals(False)

    def tree_selection_changed(self):
        ids=[];groups={g['id']:g['part_ids'] for g in (self.document.design or {}).get('part_groups',[])}
        for item in self.tree.selectedItems():
            data=item.data(0,Qt.ItemDataRole.UserRole)
            if not data:continue
            if data[0] in ('part','base','feature'):ids.append(data[1])
            elif data[0]=='group':ids.extend(groups.get(data[1],[]))
        self.select_parts(ids,sync=False)

    def group_parts(self):
        if self.busy or self.sketching:return
        try:data,gid=group_parts(self.document.design or {},self.selected_ids())
        except (ValueError,KeyError) as exc:self.message(str(exc));return
        ids=self.selected_ids();self.apply_design(data,'부품 그룹 생성',{'group_id':gid,'part_ids':ids},after=lambda:self.select_parts(ids))

    def ungroup_parts(self):
        if self.busy or not self.document.design:return
        ids=self.selected_ids();data=ungroup_parts(self.document.design,ids)
        if data.get('part_groups',[])==self.document.design.get('part_groups',[]):self.message('그룹에 속한 부품 또는 브라우저의 그룹을 선택하세요.');return
        self.apply_design(data,'부품 그룹 해제',{'part_ids':ids},after=lambda:self.select_parts(ids))

    def selection_properties(self):
        ids=self.selected_ids();groups=[g for g in self.document.design.get('part_groups',[]) if set(ids).intersection(g['part_ids'])]
        self.property_layout.addWidget(label(f'{len(ids)}개 부품 선택'))
        self.property_layout.addWidget(label('\n'.join(p['name'] for p in self.document.design['parts'] if p['id'] in ids),True))
        self.property_layout.addWidget(button('이동 / 회전 · M',self.move_parts,True))
        self.property_layout.addWidget(button('● 선택 부품 색상',self.color_selection,True))
        self.property_layout.addWidget(button('선택 부품 그룹 · Ctrl+G',self.group_parts))
        for group in groups:
            name=QLineEdit(group['name']);name.setMaxLength(80);name.setToolTip('그룹 이름 · Enter로 적용');self.property_layout.addWidget(name)
            def rename(gid=group['id'],field=name):
                if not field.text().strip():return
                data=deepcopy(self.document.design);g=next(g for g in data['part_groups'] if g['id']==gid);g['name']=field.text().strip();self.apply_design(data,'그룹 이름 변경',{'group_id':gid})
            name.returnPressed.connect(rename)
            self.property_layout.addWidget(button('그룹 전체 선택',lambda _,members=group['part_ids']:self.select_parts(members)))
        if groups:self.property_layout.addWidget(button('그룹 해제 · Ctrl+Shift+G',self.ungroup_parts))
        for title,fn in [('복사 · Ctrl+C',self.copy_parts),('잘라내기 · Ctrl+X',self.cut_parts),('삭제 · Delete',self.delete_selection)]:self.property_layout.addWidget(button(title,fn))
        self.property_layout.addWidget(label('그룹은 선택용 묶음입니다. 부품 간 움직임을 고정하려면 조립 구속을 사용하세요.',True));self.property_layout.addStretch()

    def color_selection(self):
        ids=self.selected_ids()
        if not ids:return
        color=QColorDialog.getColor(QColor(self.part()['color']),self,'선택 부품 색상')
        if not color.isValid():return
        data=deepcopy(self.document.design)
        for p in data['parts']:
            if p['id'] in ids:p['color']=color.name()
        self.apply_design(data,'선택 부품 색상 변경',{'part_ids':ids},after=lambda:self.select_parts(ids))

    def write_part_clipboard(self,payload):
        encoded=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        if len(encoded)>CLIPBOARD_LIMIT:raise ValueError('복사 데이터가 32 MB를 넘습니다. 부품 수를 줄이거나 프로젝트로 저장하세요.')
        clipboard.write(PART_MIME,encoded,'Prompt CAD Studio · '+str(len(payload['parts']))+'개 부품');self.paste_count=0

    def copy_parts(self):
        if self.busy or not self.document.design:return
        try:self.write_part_clipboard(part_clipboard(self.document.design,self.selected_ids()));self.message('부품 복사 완료 · Ctrl+V로 독립 복사본 붙여넣기 · 선택 내부의 관절과 그룹 유지')
        except Exception as exc:self.show_error(str(exc))

    def paste_parts(self):
        if self.busy or self.sketching:return
        encoded=clipboard.read(PART_MIME)
        if encoded is None:self.message('복사한 CAD 부품이 없습니다. 부품 선택 후 Ctrl+C를 누르세요.');return
        try:
            if len(encoded)>CLIPBOARD_LIMIT:raise ValueError('복사 데이터가 너무 큽니다.')
            count=getattr(self,'paste_count',0)+1;data,ids=paste_parts(self.document.design,json.loads(encoded),30*count)
        except Exception as exc:self.show_error(str(exc));return
        def done():self.paste_count=count;self.select_parts(ids)
        self.apply_design(data,'부품 붙여넣기',{'part_ids':ids,'clipboard':'independent snapshot'},fit=True,after=done)

    def cut_parts(self):self.delete_selection(cut=True)

    def delete_selection(self,cut=False):
        ids=self.selected_ids()
        if self.busy or not ids:return
        try:
            payload=part_clipboard(self.document.design,ids) if cut else None
            if payload and len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))>CLIPBOARD_LIMIT:raise ValueError('복사 데이터가 32 MB를 넘습니다.')
            data=delete_parts(self.document.design,ids)
        except Exception as exc:self.show_error(str(exc));return
        def done():
            if payload:self.write_part_clipboard(payload)
            self.select_parts([])
        self.apply_design(data,'부품 잘라내기' if cut else '선택 부품 삭제',{'part_ids':ids},after=done)

    def toggle_joints(self):
        enabled=self.actions['joints'].isChecked();self.viewport.joints.enabled=enabled;self.viewport.joints.rebuild()
        if enabled:self.connection_overview()

    def connection_overview(self):
        from .assembly_display import JOINT_NAMES
        clear_layout(self.property_layout);rows=self.viewport.joints.records
        self.property_layout.addWidget(label(f'조립 연결 {len(rows)}개'))
        self.property_layout.addWidget(label('청록: 관절 / 강체 연결 · 주황: 폐루프\n표식은 부품에 가려져도 표시됩니다. 표식이나 목록을 눌러 연결된 부품을 확인하세요.',True))
        for row in rows:
            title=f"{row['label']} · {JOINT_NAMES.get(row['kind'],row['kind'])}\n{row['parent_name']} ↔ {row['child_name']}"
            self.property_layout.addWidget(button(title,lambda _,r=row:self.inspect_connection(r['type'],r['id'])))
        if not rows:self.property_layout.addWidget(label('연결이 없습니다. 조립 메뉴에서 면 조인트 또는 기준점 연결을 추가하세요.',True))
        self.property_layout.addStretch();self.property_dock.show();self.property_dock.raise_()

    def inspect_connection(self,kind,identifier):
        row=next((r for r in self.viewport.joints.records if r['type']==kind and r['id']==identifier),None)
        if not row:return
        self.select_parts([row['parent'],row['child']])
        if kind=='mate':self.show_mate(identifier)
        else:self.show_loop(identifier)
        self.property_layout.insertWidget(0,button('← 모든 조립 연결',self.connection_overview))
