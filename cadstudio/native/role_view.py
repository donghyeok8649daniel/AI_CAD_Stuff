"""Temporary role views; never alter parts, groups, colors or circuit state."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup, QColor
from PySide6.QtWidgets import QToolBar, QWidget, QHBoxLayout, QSizePolicy
from ..part_roles import COLORS, LABELS


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

    def refresh_role_view(self):
        """Reapply after a real geometry edit, including newly created or deleted parts."""
        if self.role_view is None:
            return
        roles = part_display_roles(self.document.design or {})
        ids = [identifier for identifier in self.viewport.actors if roles.get(identifier) == self.role_view]
        color = QColor(COLORS[self.role_view])
        self.viewport.set_hidden_parts(set(self.viewport.actors) - set(ids), False)
        for identifier, (actor, _) in self.viewport.actors.items():
            if identifier in ids:
                actor.GetProperty().SetColor(color.redF(), color.greenF(), color.blueF())
        # Ordinary selection may retain a deleted/hidden member after an edit.
        self.selected_parts = [identifier for identifier in self.selected_parts if identifier in ids]
        self.selected = self.selected_parts[-1] if self.selected_parts else None
        self.viewport.select_many(self.selected_parts, False)
        self.viewport.window.Render()

    def show_part_role(self, role=None):
        if self.busy or self.sketching:
            self.actions['role_' + (self.role_view or 'all')].setChecked(True)
            return
        if role is None:
            self.reset_role_view()
            self.select_parts([i for i in self.selected_parts if i not in self.viewport.hidden])
            self.rebuild_tree()
            self.sync_tree_selection()
            self.viewport.window.Render()
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
        self.rebuild_tree()
        self.sync_tree_selection()
        message = LABELS[role] + f' · {len(ids)}개 부품 표시 / 선택'
        if not ids:
            message += ' · 부품 역할 / 기본색에서 역할을 지정하세요.'
        self.message(message)
