from xml.etree import ElementTree as ET
import ezdxf
import pytest
from cadstudio.catalog import preset
from cadstudio.drawings import DrawingSettings,sheet,svg,export_sheet
from cadstudio.native.document import Document,read_project


def test_three_views_export_and_recompute(tmp_path):
    d=preset('plate');s=DrawingSettings(part_id=d.parts[0].id,title='치수 <검사>');a=sheet(d,s);root=ET.fromstring(svg(a));assert root.attrib['width']=='297mm'
    assert len(a['paths'])>20 and any(p['hidden'] for p in a['paths'])
    assert any(t['text']=='80.000' for t in a['texts'])
    for extension in ('svg','dxf'):
        path=tmp_path/('drawing.'+extension);export_sheet(a,path);assert path.stat().st_size>1000
    doc=ezdxf.readfile(tmp_path/'drawing.dxf');assert doc.units==4 and len(doc.modelspace().query('LWPOLYLINE'))>20
    d.parts[0].geometry.length=100;b=sheet(d,s);assert any(t['text']=='100.000' for t in b['texts'])
    with pytest.raises(ValueError,match='축척'):sheet(d,s.model_copy(update={'scale':100}))


def test_study_history_roundtrip(tmp_path):
    d=preset('plate');doc=Document();doc.commit(d,'plate');d.studies=[];raw=d.model_dump();raw['studies']=[dict(id='drawing',kind='drawing',name='drawing',settings=DrawingSettings().model_dump())];doc.commit(raw,'drawing');path=tmp_path/'study.cad.json';doc.write(path);project=read_project(path)
    assert project.design.studies[0].kind=='drawing' and len(project.history.entries)==2
