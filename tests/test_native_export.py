from io import BytesIO
from zipfile import ZipFile
import cadquery as cq
import pytest
from cadstudio.catalog import preset
from cadstudio.kernel import build
from cadstudio.models import Project
from cadstudio.native_export import conversion_package


def test_autodesk_package_has_real_solids_and_editable_source(tmp_path):
    design=preset('robot_arm');shapes=build(design)
    with ZipFile(BytesIO(conversion_package(design))) as archive:
        assert 'design.step' in archive.namelist()
        assert 'Fusion/PromptCADImport/PromptCADImport.py' in archive.namelist()
        assert 'ConvertToIpt.ps1' in archive.namelist()
        assert not any(n.endswith(('.f3d','.ipt')) for n in archive.namelist())
        saved=Project.model_validate_json(archive.read('design.cad.json'))
        assert len(saved.design.mates)==4
        for part,shape in zip(design.parts,shapes):
            path=tmp_path/f'{part.id}.step';path.write_bytes(archive.read(f'parts/{part.id}.step'))
            solids=cq.importers.importStep(str(path)).solids().vals()
            assert len(solids)==1
            assert solids[0].Volume()==pytest.approx(shape.Volume(),rel=1e-7)
