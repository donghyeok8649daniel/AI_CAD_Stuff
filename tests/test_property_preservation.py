from copy import deepcopy

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QLineEdit,QPushButton

from cadstudio.models import Design,Part
from cadstudio.parameters import binding_for,set_binding
from cadstudio.native.parameters import ExpressionField
from test_placement_native import app,wait


def original():
    return Design(parts=[Part(id='p',name='Precision',geometry={'kind':'cylinder','diameter':20.123456789012345,'height':12.345678901234567},
        transform=dict(x=750.1234567890123,y=-32.1234567890123,z=13.4567891234567,rx=5.1234567891234,ry=-20.9876543210987,rz=35.1234567890123))]).model_dump()


def test_bindings_resolve_and_replace_same_dimension_by_id_or_index():
    raw=original();raw['parameters']={'d':'20','next':'30'}
    index=['parts',0,'geometry','diameter'];identifier=['parts','p','geometry','diameter']
    set_binding(raw,index,'d');assert binding_for(raw,identifier)=='d'
    set_binding(raw,identifier,'next')
    assert len(raw['dimension_bindings'])==1 and binding_for(raw,index)=='next'
    assert Design.model_validate(raw).parts[0].geometry.diameter==30
    set_binding(raw,index,'');assert 'dimension_bindings' not in raw


def test_two_paths_cannot_drive_same_dimension_with_conflicting_variables():
    raw=original();raw['parameters']={'a':'20','b':'30'}
    raw['dimension_bindings']=[dict(path=['parts',0,'geometry','diameter'],expression='a'),
                               dict(path=['parts','p','geometry','diameter'],expression='b')]
    before=deepcopy(raw)
    with pytest.raises(ValueError,match='두 번'):Design.model_validate(raw)
    assert raw==before


def test_missing_optional_binding_target_can_be_cleared_or_read_without_error():
    raw=original();missing=['parts','p','geometry','thin_wall']
    assert binding_for(raw,missing)==''
    raw['dimension_bindings']=[dict(path=missing,expression='2')]
    set_binding(raw,missing,'');assert 'dimension_bindings' not in raw
    before=deepcopy(raw)
    with pytest.raises(ValueError):set_binding(raw,missing,'3')
    assert raw==before


@pytest.fixture
def window(app,monkeypatch,tmp_path):
    from cadstudio.native import window as module
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None);monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    w=module.MainWindow();w.show();w.errors=[];w.show_error=w.errors.append
    yield w
    w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()


def load(app,w,raw):
    w.apply_design(raw,'fixture');wait(app,lambda:not w.busy);w.select_part('p');app.processEvents()


def apply(app,w):
    w.properties.findChild(QPushButton,'applyPartProperties').click();wait(app,lambda:not w.busy);assert not w.errors


def test_name_only_edit_preserves_exact_unedited_geometry_and_pose(app,window):
    w=window;load(app,w,original());before=deepcopy(w.document.design)
    w.properties.findChild(QLineEdit,'partName').setText('Renamed');apply(app,w)
    expected=deepcopy(before);expected['parts'][0]['name']='Renamed'
    assert w.document.design==expected
    w.undo();wait(app,lambda:not w.busy);assert w.document.design==before
    w.redo();wait(app,lambda:not w.busy);assert w.document.design==expected


def test_geometry_edit_preserves_exact_pose_and_unedited_dimensions(app,window):
    w=window;load(app,w,original());before=deepcopy(w.document.design)
    w.properties.findChild(ExpressionField,'partDimension_diameter').setExpression('24.987654321');apply(app,w)
    after=w.document.design['parts'][0]
    assert after['geometry']['diameter']==24.987654321
    assert after['geometry']['height']==before['parts'][0]['geometry']['height']
    assert after['transform']==before['parts'][0]['transform']


def test_index_bound_dimensions_stay_connected_on_name_edit_and_can_be_edited(app,window):
    raw=original();raw['parameters']={'d':'20'};set_binding(raw,['parts',0,'geometry','diameter'],'d')
    w=window;load(app,w,raw);before=deepcopy(w.document.design)
    field=w.properties.findChild(ExpressionField,'partDimension_diameter');assert field.expression()=='d'
    w.properties.findChild(QLineEdit,'partName').setText('Still bound');apply(app,w)
    assert w.document.design['dimension_bindings']==before['dimension_bindings']
    w.properties.findChild(ExpressionField,'partDimension_diameter').setExpression('d*2');apply(app,w)
    assert w.document.design['parts'][0]['geometry']['diameter']==40
    assert w.document.design['dimension_bindings']==[dict(path=['parts','p','geometry','diameter'],expression='d*2')]


def test_transform_expression_replaces_index_binding_without_touching_other_axes(app,window):
    raw=original();raw['parameters']={'offset':'750.1234567890123'};set_binding(raw,['parts',0,'transform','x'],'offset')
    w=window;load(app,w,raw);before=deepcopy(w.document.design)
    field=w.properties.findChild(ExpressionField,'partPlacement_x');assert field.expression()=='offset'
    field.setExpression('offset+5');apply(app,w)
    after=w.document.design['parts'][0]
    assert after['transform']=={**before['parts'][0]['transform'],'x':755.1234567890123}
    assert after['geometry']==before['parts'][0]['geometry']
    assert w.document.design['dimension_bindings']==[dict(path=['parts','p','transform','x'],expression='offset+5')]
    w.properties.findChild(ExpressionField,'partPlacement_x').setExpression('100.123456789');apply(app,w)
    assert 'dimension_bindings' not in w.document.design and w.document.design['parts'][0]['transform']['x']==100.123456789


def test_invalid_expression_does_not_apply_other_pending_property_changes(app,window):
    w=window;load(app,w,original());before=deepcopy(w.document.design)
    w.properties.findChild(QLineEdit,'partName').setText('Do not apply')
    w.properties.findChild(ExpressionField,'partPlacement_rz').setExpression('9999')
    w.properties.findChild(QPushButton,'applyPartProperties').click();app.processEvents()
    assert w.errors and not w.busy and w.document.design==before
