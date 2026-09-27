from copy import deepcopy
import math
import numpy as np
import pytest
import cadquery as cq

from cadstudio.joint_hardware import add_revolute_hardware
from cadstudio.models import Design,Part
from cadstudio.kernel import preview,export
from cadstudio.constraints import transform_matrix
from cadstudio.assembly_motion import set_joint_motion
from cadstudio.native.document import Document,read_project


def test_hardware_clearance_motion_and_real_solids(tmp_path):
    design,ids=add_revolute_hardware(prefix='test-');result=preview(design)
    assert len(ids)==7 and result['stats']['valid'] and not result['stats']['collisions']
    assert result['stats']['assembly_constraints']['dof']==1
    parts={p.id:p for p in design.parts}
    assert parts['test-bush-a'].geometry.bore_diameter-parts['test-shaft'].geometry.diameter==pytest.approx(.15)
    assert len(parts['test-mount'].geometry.holes)==5
    raw=design.model_dump();set_joint_motion(raw,'test-rotation',{'rz':57});rotated=Design.model_validate(raw)
    assert preview(rotated)['stats']['volume']==pytest.approx(result['stats']['volume'])
    for part in rotated.parts:
        expected=57 if part.id in ('test-shaft','test-output','test-collar') else 0
        assert part.transform.rz==pytest.approx(expected)
    target=tmp_path/'hardware.step';export(rotated,target,'step');shape=cq.importers.importStep(str(target)).val()
    assert len(shape.Solids())==7 and shape.Volume()==pytest.approx(result['stats']['volume'],rel=1e-7)
    doc=Document();doc.commit(rotated,'hardware');doc.write(tmp_path/'joint.cad.json')
    saved=read_project(tmp_path/'joint.cad.json');assert len(saved.design.part_groups[0].part_ids)==7


def test_existing_joint_hardware_tracks_host_without_rewriting_it():
    original=Design(parts=[Part(id='a',name='stator',geometry=dict(kind='cylinder'),fixed=True,transform=dict(x=90,y=-20,rx=30,ry=25)),Part(id='b',name='rotor',geometry=dict(kind='cylinder'))],
                    mates=[dict(id='hinge',kind='revolute',parent='a',child='b',z=60,rz=20)]).model_dump()
    before=deepcopy(original);attached,ids=add_revolute_hardware(original,mate_id='hinge',prefix='add-')
    assert original==before and attached.model_dump()['mates'][:1]==before['mates']
    assert attached.model_dump()['parts'][:2]==before['parts']
    old={p.id:p for p in attached.parts};raw=attached.model_dump();set_joint_motion(raw,'hinge',{'rz':80})
    new={p.id:p for p in Design.model_validate(raw).parts}
    delta=transform_matrix(new['b'].transform)@transform_matrix(old['b'].transform).T
    for identifier in ids:
        if identifier in ('add-shaft','add-output','add-collar'):
            assert transform_matrix(new[identifier].transform)==pytest.approx(delta@transform_matrix(old[identifier].transform))
        else:assert new[identifier].transform==old[identifier].transform
    assert len(attached.mates)==8 and not any(p.fixed for p in attached.parts if p.id in ids)


@pytest.mark.parametrize('values',[{'clearance':0},{'shaft_diameter':float('nan')},{'length':1},{'bolt_diameter':30}])
def test_bad_dimensions_do_not_mutate(values):
    raw=Design(parts=[]).model_dump();before=deepcopy(raw)
    with pytest.raises(ValueError):add_revolute_hardware(raw,values)
    assert raw==before


def test_scaled_and_offset_hardware_has_no_interference():
    design,_=add_revolute_hardware(dimensions=dict(shaft_diameter=40,length=65,bushing_wall=4,housing_wall=6,bolt_diameter=8),origin=(120,50,10))
    assert not preview(design)['stats']['collisions']
    assert design.parts[0].transform.x==120
