import math
from copy import deepcopy
from zipfile import ZipFile
import json
import pytest
import cadquery as cq
from cadstudio.models import Design,Part,PrintProfile,Project
from cadstudio.print_profile import print_targets,apply_print_profile
from cadstudio.kernel import build
from cadstudio.part_export import export_parts
from cadstudio.joint_hardware import add_revolute_hardware


def sample():
    return Design(parts=[Part(id='shaft',name='shaft',geometry=dict(kind='cylinder',diameter=10,height=12)),Part(id='housing',name='housing',geometry=dict(kind='cylinder',diameter=20,bore_diameter=10,height=8),transform={'x':35})]).model_dump()


def paths(raw):return [r['path'] for r in print_targets(raw) if r['label']!='housing · 외경']


def test_defaults_and_nonaccumulating_global_update_restore_and_persistence(tmp_path):
    raw=sample();original=deepcopy(raw);d=apply_print_profile(raw,PrintProfile(),paths(raw))
    assert raw==original and d.parts[0].geometry.diameter==10 and d.parts[1].geometry.bore_diameter==10.2
    for _ in range(3):d=Design.model_validate_json(d.model_dump_json())
    assert d.parts[1].geometry.bore_diameter==10.2
    p=PrintProfile(hole_expansion=.4,shaft_reduction=.1);d=apply_print_profile(d.model_dump(),p,paths(d))
    assert d.parts[0].geometry.diameter==9.9 and d.parts[1].geometry.bore_diameter==10.4
    p.enabled=False;d=apply_print_profile(d.model_dump(),p,paths(d))
    assert d.parts[0].geometry.diameter==10 and d.parts[1].geometry.bore_diameter==10
    p.enabled=True;d=apply_print_profile(d.model_dump(),p,paths(d));d=apply_print_profile(d.model_dump(),p,[])
    assert d.parts[0].geometry.diameter==10 and d.parts[1].geometry.bore_diameter==10
    assert not any(r['linked'] for r in print_targets(d))
    assert Project.model_validate_json(Project(design=d).model_dump_json()).design==d


def test_preserve_existing_variable_and_disallow_name_collision():
    raw=sample();raw['parameters']={'diam':'10'};raw['dimension_bindings']=[{'path':['parts','shaft','geometry','diameter'],'expression':'diam'}]
    for _ in range(10):
        raw=apply_print_profile(raw,PrintProfile(shaft_reduction=.2),paths(raw)).model_dump()
        raw=apply_print_profile(raw,PrintProfile(),[]).model_dump()
    assert next(b['expression'] for b in raw['dimension_bindings'] if b['path'][1]=='shaft')=='diam'
    raw['parameters']['diam']='14';assert Design.model_validate(raw).parts[0].geometry.diameter==14
    raw=sample();raw['parameters']={'printer_hole':'12'}
    with pytest.raises(ValueError,match='변수'):apply_print_profile(raw,PrintProfile(),paths(raw))


def test_invalid_compensation_is_rejected_without_mutation():
    raw=sample();raw['parts'][1]['geometry']['bore_diameter']=19.9;before=deepcopy(raw)
    with pytest.raises(ValueError):apply_print_profile(raw,PrintProfile(hole_expansion=5),paths(raw))
    assert raw==before
    for field in ('hole_expansion','shaft_reduction','gap','uncertainty'):
        with pytest.raises(ValueError):PrintProfile(**{field:float('nan')})


def test_actual_export_bore_volume_and_profile_manifest(tmp_path):
    raw=sample();d=apply_print_profile(raw,PrintProfile(),paths(raw));expected=math.pi*(20**2-10.2**2)/4*8
    assert build(d)[1].Volume()==pytest.approx(expected)
    target=tmp_path/'print.zip';result=export_parts(d.model_dump(),['housing'],target,('step','stl'))
    with ZipFile(target) as z:
        manifest=json.loads(z.read('parts.json'));assert manifest['print_profile']['hole_expansion']==.2
        name=next(n for n in z.namelist() if n.endswith('.step'));step=tmp_path/name;step.write_bytes(z.read(name))
    assert cq.importers.importStep(str(step)).val().Volume()==pytest.approx(expected,rel=1e-7)


def test_new_joint_hardware_inherits_profile_and_retains_mates():
    d,ids=add_revolute_hardware(Design(print_profile=PrintProfile()).model_dump(),prefix='p-')
    by_id={p.id:p for p in d.parts}
    assert by_id['p-bush-a'].geometry.bore_diameter==pytest.approx(12.35)
    assert len(d.mates)==6 and any(r['linked'] for r in print_targets(d))
    assert all(s.isValid() for s in build(d))
