from copy import deepcopy
import json
import pytest
from cadstudio.models import Design,Part,DraftRequest
from cadstudio.catalog import part_default
from cadstudio.part_roles import COLORS,assign_role
from cadstudio.native.cad_tools import execute_plan,context
from cadstudio.native.cad_scope import Scope


def test_old_project_roundtrip_keeps_custom_colors_and_no_new_history_fields():
    part=Part(id='old',name='old',geometry=dict(kind='cylinder'),color='#abc123')
    raw=part.model_dump();assert 'role' not in raw
    assert Part.model_validate_json(part.model_dump_json()).model_dump()==raw
    assign_role(raw,'electrical',False)
    updated=Part.model_validate(raw)
    assert updated.role=='electrical' and updated.color=='#abc123'
    assert Part.model_validate_json(updated.model_dump_json()).color=='#abc123'


@pytest.mark.parametrize('kind,role',[('plate','structure'),('link','transmission'),('spur_gear','transmission'),('round_specimen','specimen'),('wafer','specimen')])
def test_new_defaults_follow_roles(kind,role):
    p=part_default(kind);assert p.role==role and p.color==COLORS[role]


def test_ai_role_defaults_and_explicit_color_preserved_in_context():
    actions=[dict(tool='create',target='p',args=dict(name='motor',geometry=dict(kind='cylinder'),role='electrical'))]
    req=DraftRequest(prompt='새 전장 부품을 만들어줘')
    result=execute_plan(json.dumps(dict(summary='motor',actions=actions)),req)
    assert result.design.parts[0].color==COLORS['electrical']
    p=context(result.design)['parts'][0];assert p['role']=='electrical' and p['color']==COLORS['electrical']
    actions[0]['args']['color']='#112233'
    result=execute_plan(json.dumps(dict(summary='custom',actions=actions)),req)
    assert result.design.parts[0].color=='#112233'
    updated=execute_plan(json.dumps(dict(summary='role only',actions=[dict(tool='appearance',target='p',args=dict(role='transmission'))])),DraftRequest(prompt='역할만 변경',current=result.design))
    assert updated.design.parts[0].color=='#112233' and updated.design.parts[0].role=='transmission'
    assert '#FFD400' in Scope(tools=('create',),shapes=('cylinder',)).plan_messages(req)[0]['content']


def test_native_bulk_role_apply_is_undoable_and_keeps_custom_color_when_unchecked(app,monkeypatch,tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    from cadstudio.native.part_role_dialog import PartRoleDialog
    from PySide6.QtWidgets import QDialog
    from test_placement_native import wait
    monkeypatch.setattr(window,'DATA_DIR',tmp_path);monkeypatch.setattr(LocalModelPicker,'refresh',lambda _:None)
    w=window.MainWindow();w.show()
    raw=Design(parts=[Part(id='a',name='A',geometry=dict(kind='cylinder'),color='#123456'),Part(id='b',name='B',geometry=dict(kind='cylinder'),transform=dict(x=100),color='#654321')]).model_dump()
    try:
        w.apply_design(raw,'seed');wait(app,lambda:not w.busy);w.select_parts(['a','b'])
        before=deepcopy(w.document.design)
        def choose(d):
            d.role.setCurrentIndex(d.role.findData('electrical'));d.use_color.setChecked(False);return QDialog.DialogCode.Accepted
        monkeypatch.setattr(PartRoleDialog,'exec',choose);w.role_selection();wait(app,lambda:not w.busy)
        assert all(p['role']=='electrical' for p in w.document.design['parts'])
        assert [p['color'] for p in w.document.design['parts']]==['#123456','#654321']
        w.undo();wait(app,lambda:not w.busy);assert w.document.design==before
    finally:w.document.dirty=False;w.close();app.processEvents()


from test_placement_native import app
