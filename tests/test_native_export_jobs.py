import json
import pytest
import cadquery as cq
from cadstudio.models import Project
from cadstudio.catalog import preset
from cadstudio.native_export import prepare_native_export


@pytest.mark.parametrize('fmt',['ipt','f3d'])
def test_prepared_job_has_real_step_and_no_fake_native_file(tmp_path,fmt):
    project=Project(design=preset('cylinder'));target=tmp_path/('축 공차.'+fmt)
    folder=prepare_native_export(project,target,project.design.parts[0].id);job=json.loads((folder/'job.json').read_text(encoding='utf-8'))
    assert not target.exists();assert job['target']==str(target.resolve());assert cq.importers.importStep(job['source']).val().isValid()
    if fmt=='f3d':assert (folder/'PromptCADImport/PromptCADImport.py').is_file() and (folder/'PromptCADImport/job.json').is_file()
    else:assert (folder/'ConvertSingleToIpt.ps1').is_file()


def test_native_conversion_refuses_overwrite_and_cleans_failed_job(tmp_path):
    project=Project(design=preset('cylinder'));target=tmp_path/'already.ipt';target.write_bytes(b'existing')
    with pytest.raises(ValueError):prepare_native_export(project,target,project.design.parts[0].id)
    assert target.read_bytes()==b'existing'
    with pytest.raises(ValueError):prepare_native_export(project,tmp_path/'invalid.ipt','missing')
    assert not list(tmp_path.glob('invalid-conversion-*'))
