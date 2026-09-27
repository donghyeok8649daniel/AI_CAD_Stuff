from copy import deepcopy
from zipfile import ZipFile
import json
import cadquery as cq
import pytest
from cadstudio.models import Design,Part
from cadstudio.part_export import export_parts
from cadstudio.kernel import preview,exact_bounds
from cadstudio.joint_hardware import add_revolute_hardware
from cadstudio.native.part_inspection import exploded_preview


def test_selected_parts_export_independent_local_step_stl(tmp_path):
    design,ids=add_revolute_hardware(origin=(110,-50,35));before=design.model_dump()
    archive=tmp_path/'selected.zip';result=export_parts(before,ids[2:5],archive)
    assert len(result['parts'])==3 and before==design.model_dump()
    with ZipFile(archive) as z:
        assert z.testzip() is None and len(z.namelist())==7
        assert json.loads(z.read('parts.json'))['units']=='mm'
        for row in result['parts']:
            name=next(n for n in row['files'] if n.endswith('.step'));file=tmp_path/name;file.write_bytes(z.read(name))
            shape=cq.importers.importStep(str(file)).val();bounds=exact_bounds(shape)
            assert bounds.zmin==pytest.approx(0,abs=1e-6)
            assert bounds.xmin+bounds.xmax==pytest.approx(0,abs=1e-6)
            assert shape.Volume()==pytest.approx(row['volume_mm3'],rel=1e-7)


def test_export_preserves_dependencies_but_omits_tool_and_sanitizes_names(tmp_path):
    design=Design(parts=[Part(id='tool',name='cutter',geometry=dict(kind='cylinder',diameter=4,height=10)),Part(id='body',name='../한글:부품',geometry=dict(kind='plate',length=20,width=20,thickness=10,hole_count=0),features=[dict(id='cut',kind='solid',operation='boolean',tool_part_id='tool',boolean_mode='cut')])])
    result=export_parts(design.model_dump(),['body'],tmp_path/'part.zip',('step',),'assembly')
    assert len(result['parts'])==1 and result['parts'][0]['volume_mm3']==pytest.approx(4000-40*3.141592653589793)
    assert all('/' not in n and '\\' not in n and ':' not in n for n in result['parts'][0]['files'])


def test_export_failure_preserves_existing_archive(tmp_path,monkeypatch):
    design,_=add_revolute_hardware();target=tmp_path/'parts.zip';target.write_bytes(b'original')
    monkeypatch.setattr(cq.exporters,'export',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('disk failure')))
    with pytest.raises(RuntimeError):export_parts(design.model_dump(),[design.parts[0].id],target,('stl',))
    assert target.read_bytes()==b'original' and not list(tmp_path.glob('*.tmp'))


def test_explosion_view_never_changes_original_meshes_or_design():
    design,_=add_revolute_hardware();raw=preview(design);before=deepcopy(raw)
    exploded=exploded_preview(raw,35,'z');assert raw==before
    assert exploded['stats']['bounds'][2]>raw['stats']['bounds'][2]+100
    restored=exploded_preview(raw,0,'z');assert restored['stats']['bounds']==pytest.approx(raw['stats']['bounds'])
