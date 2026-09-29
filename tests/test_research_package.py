import hashlib,json,math
from zipfile import ZipFile
import cadquery as cq
import pytest
from cadstudio.catalog import preset
from cadstudio.research_package import TestProtocol,manifest,export_package,HEADERS


def test_round_specimen_handoff_preserves_geometry_units_and_unknown_ratings(tmp_path):
    design=preset('round_specimen');before=design.model_dump();protocol=TestProtocol(batch='Al batch 01')
    target=export_package(design,'part-1',protocol,tmp_path/'test.zip')
    assert design.model_dump()==before
    with ZipFile(target) as z:
        assert set(z.namelist())=={'protocol.json','README.txt','specimen.step','measurements-template.csv'}
        info=json.loads(z.read('protocol.json'));assert info['protocol']['max_force_N'] is None
        assert info['model_time_mapping'] is None and not info['solver_integration']
        assert info['nominal_base_areas_mm2']['gauge']==pytest.approx(math.pi*design.parts[0].geometry.gauge_diameter**2/4)
        assert info['step_sha256']==hashlib.sha256(z.read('specimen.step')).hexdigest()
        assert z.read('measurements-template.csv').decode()==HEADERS
        step=tmp_path/'specimen.step';step.write_bytes(z.read('specimen.step'))
        assert cq.importers.importStep(str(step)).val().isValid()


def test_wafer_protocol_is_separate_and_unconfirmed():
    design=preset('wafer')
    with pytest.raises(ValueError,match='재료'):manifest(design,'part-1',TestProtocol())
    with pytest.raises(ValueError,match='고정구'):manifest(design,'part-1',TestProtocol(material_id='silicon_wafer'))
    value=manifest(design,'part-1',TestProtocol(material_id='silicon_wafer',method='undecided'))
    assert value['area_status']=='not_available' and value['protocol_status']=='operator_plan_unverified'


@pytest.mark.parametrize('value',[-1,0,float('nan'),float('inf')])
def test_bad_test_conditions_never_become_ratings(value):
    with pytest.raises(ValueError):TestProtocol(max_force_N=value)


def test_failed_export_keeps_previous_package(tmp_path):
    path=tmp_path/'keep.zip';path.write_bytes(b'existing')
    with pytest.raises(ValueError):export_package(preset('round_specimen'),'missing',TestProtocol(),path)
    assert path.read_bytes()==b'existing'


def test_dialog_default_unknown_and_wafer_mode(app):
    from cadstudio.native.research_dialog import ResearchDialog
    from PySide6.QtWidgets import QDialog
    d=ResearchDialog(None,preset('round_specimen').model_dump());d.show();app.processEvents()
    try:
        assert all(not field.text() for field in d.fields.values())
        d.fields['max_force_N'].setText('nan');d.accept();assert d.result()!=QDialog.DialogCode.Accepted
        d.fields['max_force_N'].clear();d.accept();assert d.protocol.max_force_N is None
    finally:d.reject();d.deleteLater();app.processEvents()
    w=ResearchDialog(None,preset('wafer').model_dump())
    assert w.material.currentData()=='silicon_wafer' and w.method.currentData()=='undecided'
    w.reject();w.deleteLater();app.processEvents()


from test_placement_native import app
