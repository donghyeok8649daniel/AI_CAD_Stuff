from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import stat
import zipfile

import pytest

from cadstudio.firmware_bundle import (FirmwareBundle, FirmwareLibrary, create_bundle,
    export_bundle_atomic, dependency_manifest)
from cadstudio.firmware_libraries import import_library_directory, import_library_zip, pinned_dependency
from cadstudio.firmware_generation import build_context, validate_candidate, generation_context_data
from cadstudio.firmware_build import check_firmware_bundle


def work(catalog='rpi4b'):
    return {'nodes':['GND','V5'],'components':[{'id':'board','name':'Board','kind':'mcu',
        'a':'V5','b':'GND','catalog_id':catalog,'part_registration':True,'part_id':'cad_board',
        'pinout_catalog_id':catalog,'analysis_enabled':False}]}


def library(tmp_path, source='VALUE = 42\n'):
    root = tmp_path/'sensor-source'; root.mkdir()
    (root/'sensor.py').write_bytes(source.encode('utf-8'))
    (root/'LICENSE').write_text('User supplied library license', encoding='utf-8')
    return import_library_directory(root, name='Sensor', version='1.2.3', ecosystem='python')


def candidate(libraries=(), source='import sensor\nvalue = sensor.VALUE\n', catalog='rpi4b', target='raspberry_python'):
    path = 'main.py' if target == 'raspberry_python' else 'main.c'
    return create_bundle('Library controller',target,work(catalog),'board',
        [{'path':path,'content':source}],path,libraries=libraries)


def test_directory_source_snapshot_pinned_identity_and_no_execution(tmp_path):
    marker = tmp_path/'never-executed'
    source = f'from pathlib import Path\nPath({str(marker)!r}).write_text("wrong")\nVALUE = 42\n'
    item = library(tmp_path, source)
    assert not marker.exists()
    assert item.version == '1.2.3' and item.origin == 'directory'
    assert item.files[1].sha256 == sha256(source.encode()).hexdigest()
    assert item.source_sha256 and item.include_paths == ['']
    assert FirmwareLibrary.model_validate_json(item.model_dump_json()) == item
    raw = item.model_dump(); raw['source_sha256'] = '0'*64
    with pytest.raises(ValueError, match='identity'):
        FirmwareLibrary.model_validate(raw)


@pytest.mark.parametrize('version',['latest','main','master','HEAD','unknown','>=1.2','1.*','1.2 3',''])
def test_external_dependencies_require_exact_nonmoving_pin(version):
    with pytest.raises(ValueError):
        pinned_dependency('sensor',version,'python',module_names=['sensor'])


def test_library_identifier_cannot_be_a_reserved_windows_directory():
    assert pinned_dependency('AUX','1.0','c_cpp').id=='lib-aux'
    with pytest.raises(ValueError,match='Reserved'):
        FirmwareLibrary(id='aux',name='AUX',version='1.0',ecosystem='c_cpp',origin='external')


def test_zip_wrapper_binary_and_hooks_are_explicitly_omitted(tmp_path):
    archive = tmp_path/'library.zip'
    with zipfile.ZipFile(archive,'w') as out:
        out.writestr('package-1.0/src/sensor.h','#pragma once\nint read_sensor(void);\n')
        out.writestr('package-1.0/src/sensor.c','#include "sensor.h"\nint read_sensor(void){return 42;}\n')
        out.writestr('package-1.0/library.properties','name=Sensor\nversion=1.0\n')
        out.writestr('package-1.0/LICENSE','Example license')
        out.writestr('package-1.0/setup.py','raise RuntimeError("never imported")\n')
        out.writestr('package-1.0/install.ps1','Write-Host unsafe')
        out.writestr('package-1.0/binary.h',b'\x00\xff\x00')
    item = import_library_zip(archive,name='Sensor',version='1.0',ecosystem='c_cpp')
    assert item.include_paths == ['', 'src']
    assert 'install.ps1' in item.omitted_files and 'binary.h' in item.omitted_files
    assert any(file.path=='LICENSE' for file in item.files)
    # Python setup code can be source data, but is never executed by import/check.
    assert any(file.path=='setup.py' for file in item.files)


@pytest.mark.parametrize('path',['../secret.py','/absolute.py','C:/secret.py','folder\\secret.py',
    'module.py/child.py','CON.py'])
def test_unsafe_zip_names_and_directory_aliases_rejected(tmp_path,path):
    archive = tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as out:
        out.writestr('module.py','pass\n'); out.writestr(path,'pass\n')
    if '\\' in path:
        # Windows ZipInfo normalizes its input; construct the hostile archive bytes.
        archive.write_bytes(archive.read_bytes().replace(path.replace('\\','/').encode(), path.encode()))
    with pytest.raises(ValueError):
        import_library_zip(archive,name='unsafe',version='1.0',ecosystem='python')


def test_zip_case_alias_symlink_size_and_scan_limits_rejected(tmp_path):
    archive = tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as out:
        out.writestr('sensor.py','pass'); out.writestr('SENSOR.py','pass')
    with pytest.raises(ValueError,match='aliases'):
        import_library_zip(archive,name='sensor',version='1.0',ecosystem='python')
    with zipfile.ZipFile(archive,'w') as out:
        info = zipfile.ZipInfo('sensor.py'); info.create_system=3
        info.external_attr=(stat.S_IFLNK|0o777)<<16; out.writestr(info,'/private/source.py')
    with pytest.raises(ValueError,match='symbolic'):
        import_library_zip(archive,name='sensor',version='1.0',ecosystem='python')
    with zipfile.ZipFile(archive,'w') as out: out.writestr('huge.py','x'*262145)
    with pytest.raises(ValueError,match='256 KiB'):
        import_library_zip(archive,name='sensor',version='1.0',ecosystem='python')
    with zipfile.ZipFile(archive,'w') as out:
        for i in range(257): out.writestr(f'f{i}.py','pass')
    with pytest.raises(ValueError,match='256 entries'):
        import_library_zip(archive,name='sensor',version='1.0',ecosystem='python')


def test_cancelled_import_never_changes_source(tmp_path):
    root = tmp_path/'source'; root.mkdir(); source=root/'sensor.py'; source.write_text('VALUE = 42\n')
    with pytest.raises(InterruptedError):
        import_library_directory(root,name='Sensor',version='1.0',ecosystem='python',cancelled=lambda:True)
    assert source.read_text() == 'VALUE = 42\n'


def test_library_version_mismatch_and_utf8_bom_source_preservation(tmp_path):
    root=tmp_path/'source';root.mkdir()
    raw=b'\xef\xbb\xbfVALUE = 42\r\n';(root/'sensor.py').write_bytes(raw)
    (root/'library.properties').write_bytes(b'name=Sensor\nversion=1.2.3\n')
    with pytest.raises(ValueError,match='differs'):
        import_library_directory(root,name='Sensor',version='2.0',ecosystem='python')
    item=import_library_directory(root,name='Sensor',version='1.2.3',ecosystem='python')
    bundle=candidate([item]);report=check_firmware_bundle(bundle,workspace=work())
    assert report.status=='syntax_ok'
    exported=export_bundle_atomic(bundle,tmp_path/'bom-export')
    assert (exported/'libraries/sensor/sensor.py').read_bytes()==raw


def test_missing_dotted_and_relative_python_imports_stay_unverified(tmp_path):
    item=library(tmp_path)
    report=check_firmware_bundle(candidate([item],source='import sensor.missing\nfrom .unknown import value\n'),workspace=work())
    assert report.status=='pending'
    assert len([issue for issue in report.diagnostics if issue.code=='python_dependency_unverified'])==2


def test_library_sources_preserved_through_generation_export_and_pinned_manifest(tmp_path):
    item = library(tmp_path); external=pinned_dependency('RPi.GPIO','0.7.1','python',module_names=['RPi.GPIO'])
    context=build_context(work(),'board','Read sensor',libraries=[item,external])
    message=generation_context_data(context)
    assert 'files' not in message['library_dependencies'][0]
    assert message['library_source_snapshots'][1]['text']=='VALUE = 42\n'
    reply=dict(status='candidate', name='Sensor controller',target='raspberry_python',
        files=[dict(path='main.py',content='import sensor\nvalue = sensor.VALUE\n',role='source')],
        entrypoint='main.py',notes='Target libraries need verification',missing_parameters=[],pin_bindings=[])
    _,bundle=validate_candidate(reply,work(),context)
    assert bundle.libraries == [item,external]
    exported=export_bundle_atomic(bundle,tmp_path/'export')
    assert (exported/'libraries/sensor/sensor.py').read_text(encoding='utf-8')==item.files[1].content
    manifest=json.loads((exported/'firmware-dependencies.json').read_text(encoding='utf-8'))
    assert manifest==dependency_manifest(bundle)
    assert manifest['libraries'][0]['version']=='1.2.3' and not manifest['installation_performed']
    assert FirmwareBundle.model_validate_json((exported/'firmware-bundle.json').read_text(encoding='utf-8'))==bundle
    reply['files'][0]['path']='libraries/sensor/sensor.py';reply['entrypoint']=reply['files'][0]['path']
    with pytest.raises(ValueError,match='preserved'):
        validate_candidate(reply,work(),context)


def test_python_library_imports_compile_without_importing_modules_and_unresolved_stays_pending(tmp_path):
    marker=tmp_path/'never-imported'
    item=library(tmp_path,f'from pathlib import Path\nPath({str(marker)!r}).write_text("bad")\nVALUE = 42\n')
    report=check_firmware_bundle(candidate([item]),workspace=work())
    assert report.status=='syntax_ok' and not marker.exists()
    assert 'libraries/sensor/sensor.py' in report.source_sha256
    assert not report.executed_generated_code and not report.full_target_build
    pending=check_firmware_bundle(candidate([pinned_dependency('sensor','1.2.3','python',module_names=['sensor'])]),workspace=work())
    assert pending.status=='pending' and any(item.code=='external_dependency_unverified' for item in pending.diagnostics)


def test_c_imported_header_paths_are_fixed_and_full_target_build_remains_unverified(tmp_path,monkeypatch):
    import cadstudio.firmware_build as module
    source=tmp_path/'source';(source/'src').mkdir(parents=True)
    (source/'src/sensor.h').write_text('int read_sensor(void);\n')
    (source/'src/sensor.c').write_text('#include "sensor.h"\nint read_sensor(void){return 42;}\n')
    item=import_library_directory(source,name='Sensor',version='1.0',ecosystem='c_cpp')
    compiler=tmp_path/'gcc.exe';compiler.write_text('test placeholder, never executed')
    calls=[]
    def run(argv,directory,*args):
        calls.append(argv)
        assert (directory/'libraries/sensor/src/sensor.h').exists()
        assert str(directory/'libraries/sensor/src') in argv
        assert '-fsyntax-only' in argv
        return 'complete',0,''
    monkeypatch.setattr(module,'_run_compiler',run)
    result=check_firmware_bundle(candidate([item],source='#include "sensor.h"\nint main(void){return read_sensor();}\n',
        catalog='nucleo_f446re',target='stm32_hal'),workspace=work('nucleo_f446re'),compiler_path=compiler)
    assert len(calls)==2 and result.status=='pending' and not result.full_target_build
    assert not any(issue.code=='sdk_header_missing' for issue in result.diagnostics)


def test_legacy_bundle_dump_omits_default_libraries_and_snapshot_path_collisions_rejected(tmp_path):
    assert 'libraries' not in candidate(source='pass\n').model_dump()
    item=library(tmp_path)
    with pytest.raises(ValueError,match='unique'):
        candidate([item,item])
    with pytest.raises(ValueError,match='unique'):
        create_bundle('Alias','raspberry_python',work(),'board',
            [{'path':'libraries/sensor/sensor.py','content':'pass\n'}],
            'libraries/sensor/sensor.py',libraries=[item])
