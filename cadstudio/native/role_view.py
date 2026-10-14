"""Temporary role views; never alter parts, groups, colors or circuit state."""
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtGui import QActionGroup, QColor
from PySide6.QtWidgets import QToolBar, QWidget, QHBoxLayout, QSizePolicy,QLabel
from ..part_roles import COLORS, LABELS
from ..role_memberships import role_memberships,role_membership_data
from ..role_colors import ROLE_TITLES,normalize_colors,request_colors,load_settings,save_colors

NEUTRAL_COLOR='#8D98A4'


def confirmed_display_roles(design):
    """Use declared roles / actual saved circuit links, never guess from color/name."""
    linked={c.get('part_id') for c in (design.get('electrical') or {}).get('components',[])}
    membership_data=role_membership_data(design)
    result={}
    for part in design.get('parts',[]):
        role=part.get('role','unspecified')
        if part['id'] in linked:
            role=('electrical' if role in ('unspecified','electrical') else role
                  if role=='transmission' and membership_data.get(part['id'],{}).get('electric_motor') else 'unspecified')
        result[part['id']]=role if role in COLORS else 'unspecified'
    return result


def part_display_roles(design):
    """Explicit roles win. Only exact old role colors and circuit links migrate in view."""
    linked = {c.get('part_id') for c in (design.get('electrical') or {}).get('components', [])}
    old_colors = {color.lower(): role for role, color in COLORS.items()}
    roles = {}
    for part in design.get('parts', []):
        role = part.get('role', 'unspecified')
        if role == 'unspecified':
            role = 'electrical' if part['id'] in linked else old_colors.get(part.get('color', '').lower(), role)
        roles[part['id']] = role
    return roles


class RoleViewUI:
    def load_role_color_settings(self):
        self.role_color_error=''
        try:self.role_colors,self.role_colors_enabled=load_settings(self.data_dir/'role-colors.json')
        except (OSError,ValueError,TypeError):
            self.role_colors=normalize_colors();self.role_colors_enabled=False;self.role_color_error='Invalid saved settings'

    def role_color_settings_dialog(self):
        from .role_color_settings import RoleColorSettings
        dialog=RoleColorSettings(self,self.role_colors,self.role_color_error,self.role_colors_enabled)
        if not dialog.exec():return
        try:colors=save_colors(self.data_dir/'role-colors.json',dialog.selected_colors(),view_enabled=dialog.role_view.isChecked())
        except (OSError,ValueError) as exc:self.show_error(str(exc));return
        self.role_colors=colors;self.role_color_error='';self.role_colors_enabled=dialog.role_view.isChecked()
        with QSignalBlocker(self.actions['role_colors_view']):self.actions['role_colors_view'].setChecked(self.role_colors_enabled)
        self.update_role_legend();self._restore_role_colors();self.refresh_role_view()
        if not self.role_colors_enabled:self.viewport.render()
        self.message('역할 기본색 설정을 저장했습니다. 부품별 색상과 프로젝트 기록은 유지됩니다.')

    def toggle_role_colors_view(self,enabled):
        self.role_colors_enabled=enabled
        if not self.role_color_error:
            try:save_colors(self.data_dir/'role-colors.json',request_colors(self.role_colors),view_enabled=enabled)
            except OSError as exc:self.message('색상 보기 설정 저장 실패: '+str(exc))
        self._restore_role_colors();self.update_role_legend();self.refresh_role_view()
        if not enabled:self.viewport.render()

    def update_role_legend(self):
        pieces=[f'<span style="color:{self.role_colors[r]}">■</span> {ROLE_TITLES[r]} {self.role_colors[r]}' for r in ROLE_TITLES]
        pieces += [f'■ 시편 {COLORS["specimen"]}',f'■ 미지정 / 역할 충돌 {NEUTRAL_COLOR}']
        self.role_legend.setText(' · '.join(pieces));self.role_legend.setVisible(self.role_colors_enabled)
        for role in ROLE_TITLES:self.actions['role_'+role].setToolTip(ROLE_TITLES[role]+'만 보기 / 선택 · '+self.role_colors[role])

    def make_role_view_tools(self, menu):
        self.role_view = None
        self.role_view_hidden = None
        self.role_view_isolation = None
        self.role_action_group = QActionGroup(self)
        self.role_action_group.setExclusive(True)
        bar = QToolBar('부품 역할 보기', self.viewport)
        bar.setObjectName('roleViewToolbar')
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.role_toolbar = bar
        for role, key, title, tooltip in [
            (None, 'role_all', '전체', '역할 보기 해제 · 이전 표시 상태와 색상으로 돌아오기'),
            ('electrical', 'role_electrical', '전장만', '전장만 보기 / 선택 · 노란색'),
            ('structure', 'role_structure', '구조만', '구조만 보기 / 선택 · 흰색'),
            ('transmission', 'role_transmission', '동력만', '동력만 보기 / 선택 · 초록색'),
        ]:
            action = self.action(key, title, lambda checked=False, r=role: self.show_part_role(r))
            action.setCheckable(True)
            action.setToolTip(tooltip)
            action.setChecked(role is None)
            self.role_action_group.addAction(action)
            bar.addAction(action)
            menu.addAction(action)
        colors=self.action('role_colors_view','역할 색상으로 보기',lambda:None);colors.setCheckable(True);colors.setChecked(self.role_colors_enabled)
        colors.toggled.connect(self.toggle_role_colors_view);menu.addAction(colors);bar.addAction(colors)
        # Share one row with inspection tools. A fourth full toolbar row took
        # 32 px away from the model on 820 x 560 screens. Keep all role buttons
        # visible; Qt's native overflow menu holds less frequent inspection tools.
        inspection = self.inspection_toolbar
        layout = self.viewport.layout()
        layout.removeWidget(inspection)
        row = QWidget(self.viewport)
        horizontal = QHBoxLayout(row)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        inspection.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        horizontal.addWidget(bar)
        horizontal.addWidget(inspection, 1)
        layout.insertWidget(3, row)
        self.role_legend=QLabel(self.viewport);self.role_legend.setObjectName('roleColorLegend');self.role_legend.setWordWrap(True)
        layout.insertWidget(4,self.role_legend);self.update_role_legend()

    def _restore_role_colors(self):
        for identifier, (actor, _) in self.viewport.actors.items():
            color = QColor(self.viewport.meshes[identifier]['color'])
            actor.GetProperty().SetColor(color.redF(), color.greenF(), color.blueF())

    def reset_role_view(self, restore=True):
        if self.role_view is not None and restore:
            hidden = self.role_view_hidden or set()
            self.viewport.set_hidden_parts(hidden, False)
            self._restore_role_colors()
            self.isolation_hidden = self.role_view_isolation
            self.actions['isolate'].setChecked(self.isolation_hidden is not None)
        self.role_view = None
        self.role_view_hidden = None
        self.role_view_isolation = None
        self.actions['role_all'].setChecked(True)
        self.refresh_role_view()

    def refresh_role_view(self):
        """Reapply after a real geometry edit, including newly created or deleted parts."""
        if self.role_view is None:
            if getattr(self,'role_colors_enabled',False):
                roles=confirmed_display_roles(self.document.design or {})
                for identifier,(actor,_) in self.viewport.actors.items():
                    color=QColor(self.role_colors.get(roles.get(identifier),NEUTRAL_COLOR))
                    actor.GetProperty().SetColor(color.redF(),color.greenF(),color.blueF())
                self.viewport.render()
            return
        design=self.document.design or {}
        roles = part_display_roles(design)
        memberships=role_memberships(design)
        ids = [identifier for identifier in self.viewport.actors
               if self.role_view in memberships.get(identifier,set()) or roles.get(identifier) == self.role_view]
        color = QColor(self.role_colors[self.role_view])
        self.viewport.set_hidden_parts(set(self.viewport.actors) - set(ids), False)
        for identifier, (actor, _) in self.viewport.actors.items():
            if identifier in ids:
                actor.GetProperty().SetColor(color.redF(), color.greenF(), color.blueF())
        # Ordinary selection may retain a deleted/hidden member after an edit.
        self.selected_parts = [identifier for identifier in self.selected_parts if identifier in ids]
        self.selected = self.selected_parts[-1] if self.selected_parts else None
        self.viewport.select_many(self.selected_parts, False)
        self.viewport.render()

    def show_part_role(self, role=None):
        if self.busy or self.sketching:
            self.actions['role_' + (self.role_view or 'all')].setChecked(True)
            return
        if role is None:
            self.reset_role_view()
            self.select_parts([i for i in self.selected_parts if i not in self.viewport.hidden])
            self.sync_tree_visibility()
            self.sync_tree_selection()
            self.viewport.render()
            self.message('역할 보기 해제 · 원래 표시 상태와 부품 색상을 복원했습니다.')
            return
        if role not in ('electrical', 'structure', 'transmission'):
            raise ValueError('알 수 없는 부품 역할입니다.')
        if self.role_view is None:
            self.role_view_hidden = set(self.viewport.hidden)
            self.role_view_isolation = self.isolation_hidden
        self.isolation_hidden = None
        self.actions['isolate'].setChecked(False)
        self.role_view = role
        self.actions['role_' + role].setChecked(True)
        self.leave_orbit()
        self._restore_role_colors()
        self.refresh_role_view()
        ids = [i for i in self.viewport.actors if i not in self.viewport.hidden]
        self.select_parts(ids)  # Deliberately do not expand mixed-role groups.
        self.sync_tree_visibility()
        self.sync_tree_selection()
        message = ROLE_TITLES[role] + f' · {len(ids)}개 부품 표시 / 선택'
        if not ids:
            message += ' · 부품 역할 / 기본색에서 역할을 지정하세요.'
        self.message(message)
