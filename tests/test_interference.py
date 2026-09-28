from copy import deepcopy
import pytest

from cadstudio.models import Design, Part
from cadstudio.interference import (exact_collisions, assess, require_clear,
    check_joint_travel, validate_candidate, motion_changes)
from cadstudio.assembly_motion import set_joint_motion
from cadstudio.joint_hardware import add_revolute_hardware


def blocks(x=10):
    return Design(parts=[Part(id='a',name='A',geometry=dict(kind='plate',length=10,width=10,thickness=5,hole_count=0)),
                         Part(id='b',name='B',geometry=dict(kind='plate',length=10,width=10,thickness=5,hole_count=0),transform=dict(x=x))])


def swing(angle=-90):
    # An off-centre paddle hits the obstacle only halfway through -90 -> +90.
    return Design(parts=[Part(id='base',name='기준판',fixed=True,geometry=dict(kind='plate',length=5,width=5,thickness=2,hole_count=0)),
        Part(id='arm',name='회전 팔',geometry=dict(kind='extrusion',thickness=2,sketch_mode='polygon',
             points=[dict(x=x,y=y) for x,y in [(0,-1),(20,-1),(20,1),(0,1)]])),
        Part(id='stop',name='장애물',fixed=True,geometry=dict(kind='plate',length=4,width=4,thickness=2,hole_count=0),transform=dict(x=15,z=4))],
        mates=[dict(id='hinge',kind='revolute',parent='base',child='arm',z=4,rz=angle,limits={'rz':[-180,180]})])


def moved(design,angle):
    raw=design.model_dump();set_joint_motion(raw,'hinge',{'rz':angle});return Design.model_validate(raw)


def test_exact_touch_and_differential_collision_policy():
    assert not exact_collisions(blocks())
    old=blocks(8);same=blocks(8);repair=blocks(9);worse=blocks(7)
    assert exact_collisions(old)[0]['volume']==pytest.approx(100)
    assert not assess(same,old)['blocked'] and assess(same,old)['existing']
    assert not assess(repair,old)['blocked']
    with pytest.raises(ValueError,match='간섭'):require_clear(worse,old)
    with pytest.raises(ValueError,match='간섭'):require_clear(old)


def test_groups_cannot_hide_collision():
    raw=blocks(8).model_dump();raw['part_groups']=[dict(id='group',name='group',part_ids=['a','b'])]
    assert len(assess(Design.model_validate(raw))['blocked'])==1


def test_retained_boolean_tool_reported_separately_not_assembly_overlap():
    raw=blocks(5).model_dump();raw['parts'][0]['features']=[dict(id='join',kind='solid',operation='boolean',tool_part_id='b',boolean_mode='union')]
    d=Design.model_validate(raw);report=assess(d)
    assert report['references'] and not report['blocked']
    raw['parts'][0]['features'][0]['suppressed']=True
    assert assess(Design.model_validate(raw))['blocked']


def test_motion_catches_middle_with_clear_endpoints_and_suggests_stop():
    before=swing();after=moved(before,90);original=before.model_dump()
    assert not exact_collisions(before) and not exact_collisions(after)
    report=check_joint_travel(before,after)
    assert report['blocked'] and 0<report['fraction']<1
    safe=moved(before,report['last_clear'][0]['value'])
    assert not check_joint_travel(before,safe)['blocked']
    with pytest.raises(ValueError,match='관절 구동 중 간섭'):validate_candidate(after,before)
    assert before.model_dump()==original


def test_starting_overlap_and_full_rotation_cannot_bypass_check():
    assert check_joint_travel(swing(0),swing(90))['last_clear'] is None
    before=swing(-180);after=swing(180)
    assert check_joint_travel(before,after)['blocked']


def test_cooperative_cancellation_and_bounded_work():
    calls=[]
    def cancel():
        calls.append(1)
        if len(calls)>5:raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):check_joint_travel(swing(),swing(90),check=cancel)
    with pytest.raises(ValueError,match='이동을 나누어'):check_joint_travel(swing(),swing(90),max_samples=5)


def test_static_edit_is_not_misidentified_as_motion():
    before=swing();raw=before.model_dump();raw['parts'][1]['geometry']['thickness']=3
    assert not motion_changes(before,Design.model_validate(raw))


def test_hardware_has_separate_default_assembly_allowances_and_clear_motion():
    d,ids=add_revolute_hardware(prefix='h-');parts={p.id:p for p in d.parts}
    assert parts['h-bush-a'].geometry.bore_diameter-parts['h-shaft'].geometry.diameter==pytest.approx(.2)
    assert parts['h-housing'].geometry.bore_diameter-parts['h-bush-a'].geometry.diameter==pytest.approx(.2)
    assert parts['h-collar'].geometry.bore_diameter-parts['h-shaft'].geometry.diameter==pytest.approx(.2)
    raw=d.model_dump();set_joint_motion(raw,'h-rotation',{'rz':45})
    assert not check_joint_travel(d,Design.model_validate(raw))['blocked']
    assert not exact_collisions(d)
