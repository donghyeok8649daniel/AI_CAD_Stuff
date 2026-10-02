from copy import deepcopy

import pytest
from PySide6.QtCore import Qt

from cadstudio.models import Design, Part
from cadstudio.part_roles import COLORS
from cadstudio.native.role_view import part_display_roles
from test_placement_native import app, wait


def role_design():
    parts = [Part(id=role, name=role, role=role, color='#123456',
                  geometry=dict(kind='cylinder'), transform=dict(x=i*50))
             for i, role in enumerate(('electrical', 'structure', 'transmission', 'specimen'))]
    return Design(parts=parts, part_groups=[dict(id='mixed', name='Mixed roles',
                  part_ids=['electrical', 'structure'])]).model_dump()


@pytest.fixture
def role_window(app, monkeypatch, tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(LocalModelPicker, 'refresh', lambda _: None)
    w = window.MainWindow()
    w.show_error = lambda message: pytest.fail(message)
    w.show()
    w.apply_design(role_design(), 'fixture')
    wait(app, lambda: not w.busy)
    yield w
    w.document.dirty = False
    w.close()
    app.processEvents()


def test_roles_use_metadata_then_link_or_exact_legacy_color():
    d = dict(parts=[dict(id='a', role='structure', color=COLORS['electrical']),
                   dict(id='b', color=COLORS['transmission'].lower()),
                   dict(id='c', color='#fcdd00'), dict(id='d', color='#123456')],
             electrical=dict(components=[dict(part_id='d')]))
    assert part_display_roles(d) == dict(a='structure', b='transmission',
                                       c='unspecified', d='electrical')


def test_role_buttons_select_only_matching_role_and_restore_without_history(role_window, app, monkeypatch):
    w = role_window
    original = deepcopy(w.document.design)
    cursor = w.document.journal.data['cursor']
    w.viewport.visibility('specimen', False)
    calls = []
    rebuild = w.viewport.rebuild_pick_objects
    monkeypatch.setattr(w.viewport, 'rebuild_pick_objects', lambda: (calls.append(True), rebuild())[1])
    for role in ('electrical', 'structure', 'transmission'):
        before = len(calls)
        w.actions['role_' + role].trigger()
        assert len(calls) == before+1  # One picking rebuild regardless of part count.
        assert w.role_view == role and w.selected_parts == [role]
        assert {i for i, actors in w.viewport.actors.items() if actors[0].GetVisibility()} == {role}
        assert w.expand_groups([role]) == [role]
        rgb = tuple(int(COLORS[role][i:i+2], 16)/255 for i in (1, 3, 5))
        assert w.viewport.actors[role][0].GetProperty().GetColor() == pytest.approx(rgb)
        w.select_parts(['specimen', role])
        assert w.selected_parts == [role]
    w.actions['role_all'].trigger()
    assert w.role_view is None and w.viewport.hidden == {'specimen'}
    assert w.document.design == original and w.document.journal.data['cursor'] == cursor
    assert w.viewport.actors['transmission'][0].GetProperty().GetColor() == pytest.approx((18/255, 52/255, 86/255))


def test_role_filter_survives_edit_and_undo_and_empty_role(role_window, app):
    w = role_window
    w.show_part_role('electrical')
    data = deepcopy(w.document.design)
    data['parts'].append(Part(id='second', name='second', role='structure',
                             geometry=dict(kind='cylinder'), transform=dict(x=260)).model_dump())
    w.apply_design(data, 'add structure')
    wait(app, lambda: not w.busy)
    assert 'second' in w.viewport.hidden and w.selected_parts == ['electrical']
    data = deepcopy(w.document.design)
    data['parts'][0]['role'] = 'structure'
    w.apply_design(data, 'change role')
    wait(app, lambda: not w.busy)
    assert w.role_view == 'electrical' and not w.selected_parts
    assert all(not actor.GetVisibility() for actor, _ in w.viewport.actors.values())
    w.undo()
    wait(app, lambda: not w.busy)
    assert w.viewport.actors['electrical'][0].GetVisibility()
    w.show_all_parts()
    assert w.role_view is None and not w.viewport.hidden


def test_role_view_restores_existing_isolation_and_manual_tree_override(role_window, app):
    w = role_window
    w.select_parts(['structure'])
    w.isolate_parts()
    original = set(w.viewport.hidden)
    w.show_part_role('electrical')
    w.show_part_role()
    assert w.viewport.hidden == original and w.actions['isolate'].isChecked()
    w.isolate_parts()  # Return from the pre-existing isolation.
    assert not w.viewport.hidden
    w.show_part_role('electrical')
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(w.tree)
    while it.value():
        item = it.value()
        if item.data(0, Qt.ItemDataRole.UserRole) == ('part', 'structure'):
            item.setCheckState(0, Qt.CheckState.Checked)
            break
        it += 1
    assert w.role_view is None and w.viewport.actors['structure'][0].GetVisibility()
