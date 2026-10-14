"""Selection-scoped temporary visibility/opacity controls. Never commit CAD."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QSpinBox,QDialogButtonBox,QPushButton,QToolButton,QMenu,QListWidget,QAbstractItemView


class PartDisplayControls:
    def make_display_strip(self):
        """Always visible near the selection tools, independent of toolbar overflow."""
        strip=QWidget(self.viewport);strip.setObjectName('selectedPartDisplayStrip')
        row=QHBoxLayout(strip);row.setContentsMargins(6,2,6,2);row.setSpacing(5)
        self.display_selection_label=QLabel('선택 0');row.addWidget(self.display_selection_label)
        self.display_strip_buttons=[]
        def push(title,name,fn):
            b=QPushButton(title);b.setObjectName(name);b.clicked.connect(fn);row.addWidget(b);self.display_strip_buttons.append(b);return b
        push('숨김','selectedPartHide',self.hide_selected_temporarily)
        opacity=QToolButton();opacity.setObjectName('selectedPartOpacity');opacity.setText('반투명');opacity.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        opacity.clicked.connect(lambda:self.set_selected_opacity(.35));menu=QMenu(opacity)
        for title,value in [('반투명 35%',.35),('반투명 60%',.6),('불투명 100%',1.)]:
            menu.addAction(title,lambda checked=False,n=value:self.set_selected_opacity(n))
        menu.addAction('직접 조절…',self.selected_opacity_dialog);opacity.setMenu(menu);row.addWidget(opacity);self.display_strip_buttons.append(opacity)
        restore=QToolButton();restore.setObjectName('selectedPartRestore');restore.setText('복원');restore.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        restore.clicked.connect(self.restore_selected_part_display);menu=QMenu(restore)
        menu.addAction('선택 부품 복원',self.restore_selected_part_display);menu.addAction('임시 변경 전체 복원',self.restore_temporary_part_display)
        restore.setMenu(menu);row.addWidget(restore);self.display_restore_button=restore
        self.display_hidden_button=push('숨긴 부품…','hiddenPartsPicker',self.hidden_parts_dialog)
        for b in [*self.display_strip_buttons,restore]:b.setToolTip('선택 부품의 보기만 변경 · 파일/치수/조립/작업 기록 유지')
        row.addStretch();self.display_strip=strip;self.viewport.layout().insertWidget(5,strip)
        self.update_display_strip()

    def update_display_strip(self):
        if not hasattr(self,'display_strip'):return
        ids=set(self.selected_ids())&set(self.viewport.actors);available=not getattr(self,'busy',False) and not getattr(self,'sketching',False)
        self.display_selection_label.setText(f'선택 {len(ids)}')
        for b in self.display_strip_buttons:b.setEnabled(bool(ids) and available)
        saved=getattr(self,'_temporary_part_display',None)
        self.display_restore_button.setEnabled(bool(saved) and available)
        hidden=set(self.viewport.hidden)&set(self.viewport.actors)
        self.display_hidden_button.setEnabled(bool(hidden) and available)
        self.display_hidden_button.setText(f'숨긴 부품 {len(hidden)}' if hidden else '숨긴 부품…')

    def set_selected_opacity(self,value):
        from .display_overrides import checked_opacity
        value=checked_opacity(value);ids=set(self.selected_ids())&set(self.viewport.actors)
        if not ids:return
        self.reset_role_view();self._remember_part_display()
        self.viewport.set_part_opacity(ids,value);self.update_display_strip()

    def restore_selected_part_display(self):
        saved=getattr(self,'_temporary_part_display',None)
        ids=set(self.selected_ids())&set(self.viewport.actors)
        if not saved:return
        if not ids:self.restore_temporary_part_display();return
        self.reset_role_view();hidden=set(self.viewport.hidden)
        for pid in ids:
            if pid in saved['hidden']:hidden.add(pid)
            else:hidden.discard(pid)
            self.viewport.set_part_opacity([pid],saved['opacity'].get(pid,1.),render=False)
        saved['touched'].difference_update(ids)
        if not saved['touched']:self._temporary_part_display=None
        self.viewport.set_hidden_parts(hidden);self.sync_tree_visibility();self.sync_tree_selection();self.update_display_strip()

    def hidden_parts_dialog(self):
        ids=set(self.viewport.hidden)&set(self.viewport.actors)
        if not ids:return
        dialog=QDialog(self);dialog.setWindowTitle('숨긴 부품 다시 표시');dialog.resize(380,400)
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel('표시할 부품 선택 · Shift/Ctrl로 여러 부품 선택'))
        items=QListWidget();items.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);layout.addWidget(items)
        for p in (self.document.design or {}).get('parts',[]):
            if p['id'] in ids:
                items.addItem(p['name']);items.item(items.count()-1).setData(Qt.ItemDataRole.UserRole,p['id'])
        row=QHBoxLayout();layout.addLayout(row);b=QPushButton('전체 선택');b.clicked.connect(items.selectAll);row.addWidget(b)
        b=QPushButton('선택 부품 표시');b.clicked.connect(dialog.accept);row.addWidget(b)
        b=QPushButton('닫기');b.clicked.connect(dialog.reject);row.addWidget(b)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:
                chosen={i.data(Qt.ItemDataRole.UserRole) for i in items.selectedItems()}
                if chosen:
                    self.reset_role_view();self._remember_part_display(chosen)
                    self.viewport.set_hidden_parts(set(self.viewport.hidden)-chosen)
                    self.sync_tree_visibility();self.select_parts(list(chosen));self.update_display_strip()
        finally:dialog.deleteLater()

    def add_part_display_buttons(self,layout):
        row=QHBoxLayout();layout.addLayout(row)
        for title,name,callback in [('숨김','partTemporaryHide',self.hide_selected_temporarily),
                                    ('표시','partTemporaryShow',self.show_selected_temporarily),
                                    ('반투명…','partTemporaryOpacity',self.selected_opacity_dialog),
                                    ('복원','partTemporaryRestore',self.restore_selected_part_display)]:
            b=QPushButton(title);b.setObjectName(name);b.setToolTip('선택 부품의 화면 표시만 바꿉니다. 설계 파일과 작업 기록은 유지합니다.')
            b.clicked.connect(callback);row.addWidget(b)

    def _remember_part_display(self,ids=None):
        if getattr(self,'_temporary_part_display',None) is None:
            self._temporary_part_display={'hidden':set(self.viewport.hidden),'opacity':dict(getattr(self.viewport,'part_opacities',{})),'touched':set()}
        self._temporary_part_display['touched'].update(ids if ids is not None else self.selected_ids())

    def hide_selected_temporarily(self):
        ids=set(self.selected_ids())&set(self.viewport.actors)
        if not ids:self.message('표시를 바꿀 부품을 선택하세요.');return
        self.reset_role_view();self._remember_part_display()
        self.viewport.set_hidden_parts(set(self.viewport.hidden)|ids)
        self.sync_tree_visibility();self.sync_tree_selection();self.update_display_strip()

    def show_selected_temporarily(self):
        ids=set(self.selected_ids())&set(self.viewport.actors)
        if not ids:self.message('표시를 바꿀 부품을 선택하세요.');return
        self.reset_role_view();self._remember_part_display()
        self.viewport.set_hidden_parts(set(self.viewport.hidden)-ids)
        self.sync_tree_visibility();self.sync_tree_selection();self.update_display_strip()

    def restore_temporary_part_display(self):
        saved=getattr(self,'_temporary_part_display',None)
        if saved is None:return
        self.reset_role_view();hidden=set(self.viewport.hidden)
        for pid in saved['touched']&set(self.viewport.actors):
            self.viewport.set_part_opacity([pid],saved['opacity'].get(pid,1.),render=False)
            if pid in saved['hidden']:hidden.add(pid)
            else:hidden.discard(pid)
        self.viewport.set_hidden_parts(hidden)
        self._temporary_part_display=None;self.sync_tree_visibility();self.sync_tree_selection();self.update_display_strip()

    def selected_opacity_dialog(self):
        ids=set(self.selected_ids())&set(self.viewport.actors)
        if not ids:self.message('표시를 바꿀 부품을 선택하세요.');return
        self._remember_part_display()
        before={pid:getattr(self.viewport,'part_opacities',{}).get(pid,1.) for pid in ids}
        dialog=QDialog(self);dialog.setWindowTitle('선택 부품 반투명 · 보기 전용')
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel('형상·색상·작업 기록은 그대로 유지합니다. 취소하면 이전 불투명도로 돌아갑니다.'))
        value=QSpinBox();value.setRange(10,100);value.setSingleStep(5);value.setSuffix(' %')
        value.setValue(round(next(iter(before.values()))*100) if len(set(before.values()))==1 else 100)
        layout.addWidget(value);presets=QHBoxLayout();layout.addLayout(presets)
        for title,amount in [('반투명 35%',35),('불투명 100%',100)]:
            b=QPushButton(title);b.clicked.connect(lambda checked=False,n=amount:value.setValue(n));presets.addWidget(b)
        def preview(amount):
            current=ids&set(self.viewport.actors)
            if current:self.viewport.set_part_opacity(current,amount/100)
        value.valueChanged.connect(preview)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:
                for pid,opacity in before.items():
                    if pid in self.viewport.actors:self.viewport.set_part_opacity([pid],opacity,render=False)
                self.viewport.render()
        finally:dialog.deleteLater();self.update_display_strip()
