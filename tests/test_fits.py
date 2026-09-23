import pytest
from cadstudio.models import Design
from cadstudio.catalog import preset
from cadstudio.fits import FitSettings,calculate_fit
from cadstudio.drawings import DrawingSettings,sheet
from cadstudio.native.document import Document,read_project


def design():
    d=preset('cylinder');d.parts[0].id='shaft';d.parts[0].geometry.diameter=10
    hole=preset('plate').parts[0];hole.id='hole';hole.geometry.hole_diameter=10;hole.transform.x=100;d.parts.append(hole)
    return d


def test_limits_follow_geometry_and_history(tmp_path):
    d=design();s=FitSettings(shaft_ref='shaft/diameter',hole_ref='hole/hole_diameter')
    r=calculate_fit(d,s);assert r['minimum']==pytest.approx(0);assert r['maximum']==pytest.approx(.04)
    d.studies=[dict(id='fit-test',kind='fit',name='Fit',settings=s.model_dump())];d=Design.model_validate(d.model_dump());doc=Document();doc.commit(d,'Fit');path=tmp_path/'fit.cad.json';doc.write(path);loaded=read_project(path)
    assert loaded.design.studies[0].settings['shaft_ref']=='shaft/diameter'
    d.parts[0].geometry.diameter=10.03;r=calculate_fit(d,s);assert r['kind']=='중간 끼워맞춤';assert r['minimum']==pytest.approx(-.03)
    d.parts[0].geometry.diameter=10.06;assert calculate_fit(d,s)['kind']=='억지 끼워맞춤'
    texts=[t['text'] for t in sheet(d,DrawingSettings())['texts']];assert any('10.0400 / 10.0600' in t for t in texts)


def test_stale_reference_and_invalid_limits_fail():
    d=design()
    with pytest.raises(ValueError):FitSettings(shaft_lower=.1,shaft_upper=0)
    with pytest.raises(ValueError):calculate_fit(d,FitSettings(shaft_nominal=.01,shaft_lower=-.02))
    with pytest.raises(ValueError):calculate_fit(d,FitSettings(hole_ref='deleted/hole'))
    r=calculate_fit(d,FitSettings(shaft_lower=.03,shaft_upper=.04,hole_lower=-.02,hole_upper=-.01));assert r['maximum']<0
