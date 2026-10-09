from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.firmware_bundle import (FirmwareBundle, FirmwareExportCancelled, FirmwareFile,
    create_binding, create_bundle, export_bundle_atomic, programmable_board_ids,
    to_program_attachment, verify_bundle_binding)


def workspace():
    return ElectricalWorkspace.model_validate({'nodes':['GND','V5','PWM','OTHER'], 'components':[
        {'id':'board','name':'Controller','kind':'mcu','a':'V5','b':'GND','catalog_id':'rpi4b',
         'part_registration':True,'part_id':'cad_controller','pinout_catalog_id':'rpi4b',
         'signal_pins':{'GPIO18':'PWM'},'rated_voltage_v':5,'rated_current_a':.02},
        {'id':'wire','name':'PWM lead','kind':'wire','a':'PWM','b':'OTHER','closed':True,
         'length_mm':100,'cross_section_mm2':.5}]})


def candidate(work=None, **changes):
    options=dict(name='Controller source',target='raspberry_python',workspace=work or workspace(),
        board_id='board',files=[{'path':'main.py','content':'value = 1\n'},
            {'path':'README.md','content':'Review wiring and limits.\n','role':'documentation'}],
        entrypoint='main.py',pin_bindings=[{'pin':'GPIO18','node':'PWM','function':'Motor command'}])
    options.update(changes)
    return create_bundle(**options)


def test_portable_roundtrip_contains_exact_source_identity_and_trusted_registration():
    work=workspace(); bundle=candidate(work)
    loaded=FirmwareBundle.model_validate_json(bundle.model_dump_json())
    assert loaded==bundle
    assert bundle.files[0].sha256==sha256(b'value = 1\n').hexdigest()
    assert bundle.binding.board_component_id=='board' and bundle.binding.part_id=='cad_controller'
    assert bundle.binding.board_model=='Raspberry Pi 4 Model B'
    assert verify_bundle_binding(loaded,work).status=='current'
    assert programmable_board_ids(work)==['board']
    assert to_program_attachment(bundle,work).source=='value = 1\n'


@pytest.mark.parametrize('path',['../main.py','/main.py','C:/main.py','folder\\main.py','folder//main.py',
    './main.py','folder/../main.py','main.py.','CON.py','aux.py','COM1.h','folder/NUL.txt',
    '.git/config.json','.vscode/tasks.json','@arguments.py','-main.py','folder/main.py:stream',
    'firmware-bundle.json'])
def test_unsafe_paths_are_rejected_before_export(path):
    role='configuration' if path.endswith('.json') else 'source'
    with pytest.raises(ValueError):
        FirmwareFile(path=path,content='{}' if role=='configuration' else 'pass\n',role=role,
            sha256=sha256(('{}' if role=='configuration' else 'pass\n').encode()).hexdigest())


@pytest.mark.parametrize('path',['run.exe','setup.cmd','install.ps1','hook.sh','CMakeLists.txt','module.pyc'])
def test_candidate_cannot_export_binary_installers_or_build_hooks(path):
    with pytest.raises(ValueError):
        FirmwareFile(path=path,content='text',sha256=sha256(b'text').hexdigest())


def test_duplicate_case_and_file_directory_aliases_rejected():
    for paths in [('main.py','MAIN.py'),('main.py','main.py/helper.py')]:
        with pytest.raises(ValueError):
            candidate(files=[{'path':path,'content':'pass\n'} for path in paths])


def test_utf8_byte_limit_and_sha_tampering_rejected():
    with pytest.raises(ValueError):
        candidate(files=[{'path':'main.py','content':'가'*100_000}])
    raw=candidate().model_dump();raw['files'][0]['content']='value = 2\n'
    with pytest.raises(ValueError,match='SHA-256'):
        FirmwareBundle.model_validate(raw)


def test_saved_stale_bundle_survives_project_load_but_explicit_review_blocks_reuse():
    work=workspace();bundle=candidate(work)
    changed=work.model_dump();changed['components'][1]['closed']=False
    changed['firmware_bundles']=[bundle.model_dump()]
    loaded=ElectricalWorkspace.model_validate(changed)
    assert loaded.firmware_bundles[0]==bundle
    assert verify_bundle_binding(bundle,loaded).status=='stale'
    with pytest.raises(ValueError,match='stale'):
        to_program_attachment(bundle,loaded)


def test_cosmetic_rename_links_wire_color_and_position_do_not_change_wiring_fingerprint():
    work=workspace();binding=create_binding(work,'board')
    raw=work.model_dump();raw['components'][0]['name']='Renamed board'
    raw['components'][0]['source_url']='https://www.raspberrypi.com/products/raspberry-pi-4-model-b/'
    raw['components'][1]['wire_color']='#00FF00'
    raw['components'][1]['source_url']='https://example.com/wire-specification'
    raw['schematic_positions']={'board':{'x':120,'y':-50}}
    assert create_binding(raw,'board')==binding


def test_calibration_dates_roundtrip_and_numeric_scale_changes_require_review():
    raw=workspace().model_dump()
    raw['components'].append({'id':'loadcell','name':'Load cell','kind':'load','a':'V5','b':'GND',
        'analysis_enabled':False,'measurement':{'role':'load_cell','source_checked_at':'2026-10-09',
            'calibration':{'status':'user_calibrated','zero_offset_counts':12,'scale_n_per_count':.01,
                'calibrated_at':'2026-10-09'}}})
    validated=ElectricalWorkspace.model_validate(raw)
    before=create_binding(raw,'board')
    assert create_binding(validated,'board')==before
    changed=validated.model_dump();changed['components'][-1]['measurement']['calibration']['scale_n_per_count']=.02
    assert create_binding(changed,'board').wiring_sha256!=before.wiring_sha256


def test_pin_wrong_node_unknown_pin_and_source_family_fail_new_generation():
    for item in [{'pin':'GPIO18','node':'OTHER'}, {'pin':'GPIO99','node':'PWM'}]:
        with pytest.raises(ValueError,match='assignment'):
            candidate(pin_bindings=[item])
    with pytest.raises(ValueError,match='source family'):
        candidate(target='stm32_hal',files=[{'path':'main.c','content':'int main(void){return 0;}'}],entrypoint='main.c')


def test_unregistered_manual_board_is_not_a_new_generation_target():
    raw=workspace().model_dump();raw['components'][0]['part_registration']=False
    assert programmable_board_ids(raw)==[]
    with pytest.raises(ValueError,match='Register the actual CAD'):
        create_binding(raw,'board')


def test_documented_programmable_esc_is_exportable_without_false_gpio_trace_attachment():
    raw={'nodes':['GND','BUS','COMMAND'],'components':[{'id':'esc','name':'Exact ESC',
        'kind':'load','a':'BUS','b':'GND','catalog_id':'st_b_g431b_esc1',
        'product_pinout_catalog_id':'st_b_g431b_esc1','part_registration':True,'part_id':'driver_body',
        'analysis_enabled':False,'terminal_pins':{'J3_PWM':'COMMAND'}}]}
    bundle=create_bundle('ESC review','stm32_hal',raw,'esc',
        [{'path':'main.c','content':'int main(void){return 0;}'}],'main.c',
        pin_bindings=[{'pin':'J3_PWM','node':'COMMAND'}],missing_parameters=['Verified MCSDK configuration'])
    assert programmable_board_ids(raw)==['esc']
    assert verify_bundle_binding(bundle,raw).status=='current'
    with pytest.raises(ValueError,match='MCU / MPU'):
        to_program_attachment(bundle,raw)


def test_provenance_is_trusted_input_bounded_utc_and_allows_many_repairs():
    generation={'request':'Generate a stop-safe controller.','provider':'codex','model':'verified-model',
        'created_utc':datetime(2026,10,9,tzinfo=timezone.utc),'attempts':100}
    bundle=candidate(generation=generation)
    assert bundle.generation.attempts==100
    assert bundle.model_dump()['generation']['created_utc']=='2026-10-09T00:00:00Z'
    assert FirmwareBundle.model_validate_json(bundle.model_dump_json()).generation==bundle.generation
    generation['created_utc']=datetime(2026,10,9)
    with pytest.raises(ValueError,match='UTC'):
        candidate(generation=generation)


def test_native_document_generation_save_reload_edit_and_exact_history_undo_redo(tmp_path):
    from cadstudio.models import Design
    from cadstudio.native.document import Document, read_project

    original=Design.model_validate({'name':'Research controller','parts':[
        {'id':'cad_controller','name':'User controller','role':'electrical','color':'#112233',
         'geometry':{'kind':'plate','length':85,'width':56,'thickness':2,'hole_count':0}}],
        'electrical':workspace().model_dump()})
    before=original.model_dump()
    generation={'request':'제어 코드 검토 후보를 만들어줘.','model':'verified-model','effort':'high',
        'created_utc':datetime(2026,10,9,1,2,3,456789,tzinfo=timezone.utc),'attempts':100}
    bundle=candidate(original.electrical,generation=generation)
    doc=Document();doc.commit(original,'Original')
    changed=original.model_dump();changed['electrical']['firmware_bundles']=[bundle.model_dump()]
    changed=Design.model_validate(changed)
    # Exercise the real Python-mode history path, which must only hold JSON values.
    assert json.loads(json.dumps(changed.model_dump(),ensure_ascii=False))['electrical'][
        'firmware_bundles'][0]['generation']['created_utc']=='2026-10-09T01:02:03.456789Z'
    doc.commit(changed,'Save firmware',{'tool':'electrical-firmware'})
    edited=candidate(original.electrical,generation=generation,
        files=[{'path':'main.py','content':'value = 2\n'}])
    edited_raw=changed.model_dump();edited_raw['electrical']['firmware_bundles']=[edited.model_dump()]
    doc.commit(Design.model_validate(edited_raw),'Edit firmware',{'tool':'electrical-firmware'})
    file=tmp_path/'portable-with-generation.cad.json';doc.write(file)
    restored=read_project(file)
    assert restored.design.electrical.firmware_bundles==[edited]
    assert restored.design.electrical.firmware_bundles[0].generation.created_utc==generation['created_utc']
    doc.load(restored,file);entries=doc.journal.path()
    assert len(entries)==3 and doc.journal.at(entries[0]['id'])==before
    doc.commit(doc.journal.at(entries[1]['id']),'Undo edit',cursor=entries[1]['id'])
    assert doc.project().design.electrical.firmware_bundles==[bundle]
    doc.commit(doc.journal.at(entries[0]['id']),'Undo save',cursor=entries[0]['id'])
    assert 'firmware_bundles' not in doc.project().design.electrical.model_dump()
    doc.commit(doc.journal.at(entries[-1]['id']),'Redo edit',cursor=entries[-1]['id'])
    assert doc.project().design.electrical.firmware_bundles==[edited]
    doc.write(file)
    assert read_project(file).design.electrical.firmware_bundles[0].generation==bundle.generation
    assert original.model_dump()==before


def test_atomic_export_has_manifest_and_preserves_utf8(tmp_path):
    bundle=candidate(files=[{'path':'src/main.py','content':'문자 = 1\n'},
        {'path':'README.md','content':'검토 필요\n','role':'documentation'}],entrypoint='src/main.py')
    folder=export_bundle_atomic(bundle,tmp_path/'new-project')
    assert (folder/'src/main.py').read_text(encoding='utf-8')=='문자 = 1\n'
    assert FirmwareBundle.model_validate_json((folder/'firmware-bundle.json').read_text(encoding='utf-8'))==bundle
    assert not list(tmp_path.glob('.cad-firmware-*'))


def test_existing_destination_is_never_overwritten(tmp_path):
    target=tmp_path/'existing';target.mkdir();(target/'user.txt').write_text('Keep me.')
    with pytest.raises(FileExistsError):
        export_bundle_atomic(candidate(),target)
    assert (target/'user.txt').read_text()=='Keep me.'


def test_cancel_after_staging_does_not_publish_partial_project(tmp_path):
    calls=0
    def cancelled():
        nonlocal calls
        calls+=1
        return calls>=3
    with pytest.raises(FirmwareExportCancelled):
        export_bundle_atomic(candidate(),tmp_path/'cancelled',cancelled=cancelled)
    assert not (tmp_path/'cancelled').exists()
    assert not list(tmp_path.glob('.cad-firmware-*'))


def test_concurrent_destination_creation_is_not_replaced(tmp_path,monkeypatch):
    import cadstudio.firmware_bundle as module
    original=module._rename_new_directory
    def race(stage,target):
        target.mkdir();(target/'user.txt').write_text('Concurrent user project')
        return original(stage,target)
    monkeypatch.setattr(module,'_rename_new_directory',race)
    with pytest.raises(OSError):
        export_bundle_atomic(candidate(),tmp_path/'raced')
    assert (tmp_path/'raced/user.txt').read_text()=='Concurrent user project'
    assert not list(tmp_path.glob('.cad-firmware-*'))


def test_export_rejects_symlink_parent(tmp_path):
    actual=tmp_path/'actual';actual.mkdir();link=tmp_path/'link'
    try:
        link.symlink_to(actual,target_is_directory=True)
    except OSError:
        pytest.skip('This Windows account cannot create symbolic links.')
    with pytest.raises(ValueError,match='symbolic links'):
        export_bundle_atomic(candidate(),link/'child')
    assert not (actual/'child').exists()


def test_export_rejects_mocked_windows_junction(tmp_path,monkeypatch):
    import cadstudio.firmware_bundle as module
    actual_lstat=Path.lstat
    class Junction:
        st_mode=0o40700
        st_file_attributes=0x400
    def lstat(path,*args,**kwargs):
        return Junction() if path==tmp_path else actual_lstat(path,*args,**kwargs)
    monkeypatch.setattr(Path,'lstat',lstat)
    with pytest.raises(ValueError,match='reparse points'):
        export_bundle_atomic(candidate(),tmp_path/'new')
