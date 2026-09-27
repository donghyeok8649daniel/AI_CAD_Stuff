from copy import deepcopy
import math
import pytest
from cadstudio.models import Design,Part,PrintProfile
from cadstudio.kernel import local_shape,build
from cadstudio.electronics_mount import add_electronics_mount,MountSpec
from cadstudio.print_profile import print_targets


def host():
    part=Part(id='host',name='Battery case',geometry=dict(kind='plate',length=100,width=80,thickness=10,hole_count=0))
    d=Design(parts=[part]);face=next(i for i,f in enumerate(local_shape(d,part).Faces()) if f.normalAt().z>.99)
    return d.model_dump(),face


def test_editable_rectangular_seat_four_holes_exact_volume_and_persistence():
    raw,face=host();before=deepcopy(raw);spec=MountSpec()
    d,ids=add_electronics_mount(raw,'host',face,spec,prefix='test')
    expected=80000-(spec.width+.2)*(spec.length+.2)*3-4*math.pi*1.5**2*7
    assert build(d)[0].Volume()==pytest.approx(expected)
    assert raw==before and len(ids)==5 and len(d.parts)==1
    assert all(f.operation=='cut' for f in d.parts[0].features)
    assert build(Design.model_validate_json(d.model_dump_json()))[0].Volume()==pytest.approx(expected)


def test_circular_seat_and_wire_without_unspecified_bolt_pattern():
    raw,face=host();d,ids=add_electronics_mount(raw,'host',face,dict(shape='circle',width=20,depth=2,bolts=False,wire=True,wire_diameter=4),prefix='test')
    assert len(ids)==2
    assert build(d)[0].Volume()==pytest.approx(80000-math.pi*(10.1**2*2+2**2*8))


def test_profile_applies_to_real_mount_holes_once():
    raw,face=host();raw['print_profile']=PrintProfile().model_dump();d,ids=add_electronics_mount(raw,'host',face,dict(pocket=False),prefix='test')
    assert len(ids)==4
    assert build(d)[0].Volume()==pytest.approx(80000-4*math.pi*1.6**2*10)
    assert len([r for r in print_targets(d) if r['linked']])==4


@pytest.mark.parametrize('spec',[{'width':120},{'depth':20},{'x':200},{'pocket':False,'bolts':False,'wire':False}])
def test_invalid_or_outside_seat_preserves_original(spec):
    raw,face=host();before=deepcopy(raw)
    with pytest.raises(ValueError):add_electronics_mount(raw,'host',face,spec)
    assert raw==before
