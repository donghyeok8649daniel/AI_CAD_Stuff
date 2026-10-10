"""Rotation compatibility without importing the native SciPy rotation extension."""
import builtins
import math
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from cadstudio.constraints import _xyz_angles, _xyz_matrix, anchors, solve_assembly, transform_matrix
from cadstudio.models import Design, Project
from cadstudio.native.document import Document, read_project


@pytest.fixture(autouse=True)
def no_native_rotation(monkeypatch):
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name.startswith('scipy.spatial.transform'):
            raise AssertionError('Assembly math must not import native SciPy Rotation')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)


def test_extrinsic_xyz_orders_axes_and_preserves_translation_contract():
    matrix=transform_matrix(SimpleNamespace(rx=90,ry=90,rz=90,x=999,y=888,z=777))
    assert np.allclose(matrix,[[0,0,1],[0,1,0],[-1,0,0]],atol=1e-15)
    assert np.allclose(matrix.T@matrix,np.eye(3),atol=1e-15)
    assert np.linalg.det(matrix)==pytest.approx(1,abs=5e-15)


@pytest.mark.parametrize('angles,expected',[
    ((20,30,40),(20,30,40)),((-45,72,135),(-45,72,135)),
    ((37,90,-23),(60,90,0)),((37,-90,-23),(14,-90,0)),
    ((20,120,40),(-160,60,-140)),((20,-120,40),(-160,-60,-140)),
])
def test_canonical_branches_and_both_gimbal_signs(angles,expected):
    actual=_xyz_angles(_xyz_matrix(*angles))
    assert actual==pytest.approx(expected,abs=1e-11)
    assert np.allclose(_xyz_matrix(*actual),_xyz_matrix(*angles),atol=1e-14)


def test_near_gimbal_retains_middle_angle_and_uses_prior_threshold():
    inside=_xyz_angles(_xyz_matrix(37,90-1e-6,-23))
    outside=_xyz_angles(_xyz_matrix(37,90-1e-4,-23))
    assert inside[1]==pytest.approx(90-1e-6,abs=1e-10)
    assert inside[2]==0
    assert outside==pytest.approx((37,90-1e-4,-23),abs=1e-8)


def test_retained_near_gimbal_matrix_preserves_legacy_scalar_tolerance():
    # Captured from the bounded compiled oracle: trace reassociation can amplify
    # a quaternion ULP enough to invalidate an otherwise unchanged saved state.
    matrix=[[-1.6065840469902875e-7,-.24192189559965932,-.9702957262759853],
            [6.819544680714852e-8,.970295726275993,-.24192189559967248],
            [.9999999999999848,-1.0503653639726585e-7,-1.3938819170693537e-7]]
    expected=(-142.99999998663813,-89.99999000000001,156.99999998663813)
    assert all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8) for a,b in zip(_xyz_angles(matrix),expected))


@pytest.mark.parametrize('angles,legacy_angles',[
    ((137.4,-89.99999421312627,-81.7),(137.39999996417868,-89.99999421312627,-81.69999996417866)),
    ((137.4,89.99999421312627,-81.7),(137.4000000243815,89.99999421312627,-81.69999997561848)),
])
def test_saved_legacy_near_gimbal_history_keeps_exact_entries_and_roundtrips(angles,legacy_angles,tmp_path):
    # These are old compiled results, not recomputed expected values. A direct
    # full-angle forward matrix rejected both journals at the existing tolerance.
    base=Design.model_validate(dict(parts=[
        dict(id='base',name='Base',fixed=True,geometry=dict(kind='plate',hole_count=0)),
        dict(id='child',name='Child',geometry=dict(kind='plate',hole_count=0))],
        mates=[dict(id='a',parent='base',child='child')])).model_dump()
    legacy=deepcopy(base)
    legacy['mates'][0].update(dict(zip(('rx','ry','rz'),angles)))
    legacy['parts'][1]['transform'].update(dict(zip(('rx','ry','rz'),legacy_angles)))
    document=Document();document.load(Project(design=base));document.commit(legacy,'Legacy near-gimbal result')
    old_journal=deepcopy(document.journal.data)
    project=document.project()
    assert project.history.model_dump()==old_journal
    assert document.journal.data==old_journal
    saved=tmp_path/'legacy.pcad'
    document.write(saved)
    assert read_project(saved).model_dump(mode='json')==project.model_dump(mode='json')
    assert document.journal.data==old_journal


def test_nonorthogonal_frame_uses_nearest_polar_rotation():
    expected=_xyz_matrix(20,30,40)
    stretch=np.array([[1+2e-6,3e-6,0],[3e-6,1-2e-6,0],[0,0,1]])
    actual=_xyz_angles(expected@stretch)
    assert actual==pytest.approx((20,30,40),abs=1e-9)
    with pytest.raises(ValueError,match='오른손'):
        _xyz_angles(np.diag([-1,1,1]))


@pytest.mark.parametrize('use_frames',[False,True])
def test_two_link_assembly_and_rotated_face_frames_preserve_world_anchors(use_frames):
    raw=dict(parts=[
        dict(id='base',name='Base',fixed=True,geometry=dict(kind='plate',length=10,width=12,thickness=8,hole_count=0),transform=dict(x=20,y=-5,z=7,rx=20,ry=30,rz=40)),
        dict(id='child',name='Child',geometry=dict(kind='plate',length=3,width=4,thickness=5,hole_count=0)),
        dict(id='tip',name='Tip',geometry=dict(kind='plate',length=2,width=2,thickness=2,hole_count=0)),
    ],mates=[dict(id='a',parent='base',child='child',parent_anchor='top',child_anchor='bottom',x=1,y=2,z=3,rx=10,ry=-20,rz=35),
             dict(id='b',parent='child',child='tip',parent_anchor='top',child_anchor='bottom',rz=-25)])
    if use_frames:
        raw['joint_frames']=[dict(mate_id='a',flipped=True,
            parent=dict(face=0,face_count=6,origin=[2,1,8],normal=[0,1,0],x_direction=[1,0,0]),
            child=dict(face=0,face_count=6,origin=[1,2,0],normal=[0,0,1],x_direction=[0,1,0]))]
    design=Design.model_validate(raw)
    solve_assembly(design)
    base,child,tip=design.parts
    def point(part,key):
        return np.array([part.transform.x,part.transform.y,part.transform.z])+transform_matrix(part.transform)@np.array(anchors(part.geometry)[key])
    if use_frames:
        frame=design.joint_frames[0]
        basis=lambda f:np.column_stack([f.x_direction,np.cross(f.normal,f.x_direction),f.normal])
        parent_frame=transform_matrix(base.transform)@basis(frame.parent)
        base_pos=np.array([base.transform.x,base.transform.y,base.transform.z])
        child_pos=np.array([child.transform.x,child.transform.y,child.transform.z])
        assert np.allclose(child_pos+transform_matrix(child.transform)@frame.child.origin,
            base_pos+transform_matrix(base.transform)@frame.parent.origin+parent_frame@np.array([1,2,3]),atol=1e-12)
        assert np.allclose(transform_matrix(child.transform)@basis(frame.child),
            parent_frame@_xyz_matrix(10,-20,35)@np.diag([1,-1,-1]),atol=1e-12)
    else:
        assert np.allclose(point(child,'bottom'),point(base,'top')+transform_matrix(base.transform)@np.array([1,2,3]),atol=1e-12)
    assert np.allclose(point(tip,'bottom'),point(child,'top'),atol=1e-12)
    before=design.model_dump()
    repeated=Design.model_validate(before).model_dump()
    for old,new in zip(before['parts'],repeated['parts']):
        assert new['transform']==pytest.approx(old['transform'],abs=1e-10)
