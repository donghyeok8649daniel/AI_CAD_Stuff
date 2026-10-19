"""New .pcad route-migration checks using only owned files and fake registries.

No real registry, application, process query, GUI, install transaction, or old
whole-suite execution is used by these tests.
"""
import json
import hashlib
from pathlib import Path
import sys

import pytest
from cadstudio import file_associations as F
from cadstudio import single_install as S
import update_desktop as D


class Registry:
    def __init__(self):
        self.values={};self.keys=set();self.fail=None;self.writes=[]

    def get(self,key,name):return self.values.get((key,name))
    def key_exists(self,key):return key in self.keys or any(k==key or k.startswith(key+'\\') for k,_ in self.values)
    def merged_default(self,extension):return self.get(F.CLASSES+'\\'+extension,'')
    def choice_present(self,extension):return F._WindowsRegistry.choice_present(self,extension)

    def set(self,key,name,value):
        self.writes.append((key,name))
        if self.fail==(key,name):self.fail=None;raise OSError('owned fake write failure')
        self.keys.add(key);self.values[key,name]=value

    def delete(self,key,name):self.values.pop((key,name),None)
    def prune_empty(self,key):
        if not any(k==key or k.startswith(key+'\\') for k,_ in self.values):self.keys.discard(key)


@pytest.fixture
def apps(tmp_path):
    paths=[]
    for folder in ('old 한글 install','canonical current app','other historical app'):
        p=tmp_path/folder/F.EXE_NAME;p.parent.mkdir();p.write_bytes(b'owned fake app bytes');paths.append(p.resolve())
    return paths


def refresh(path,registry,*,verified=()):
    def canonical(p):
        assert Path(p)==path
        return path
    return F.refresh_owned_pcad_routes(path,_backend=registry,_canonical_validator=canonical,
        _legacy_verifier=lambda p:any(F._path_identity(p)==F._path_identity(v) for v in verified))


def choose(registry,progid,*,latest=False):
    key=r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pcad'
    key+=r'\UserChoiceLatest\UserChoice' if latest else r'\UserChoice'
    registry.values[key,'ProgId']=(progid,F.REG_SZ);registry.values[key,'Hash']=('owned fake protected hash',F.REG_SZ)


def protected_values(registry):
    return {k:v for k,v in registry.values.items() if '\\Explorer\\FileExts\\' in k[0]}


def test_selected_windows_auto_file_migrates_owned_old_command_and_preserves_protected_choices(apps):
    old,current,_=apps;r=Registry();F.register(old,_backend=r)
    r.values[F.PCAD,'']=(F.COMPAT_PROGID,F.REG_SZ)
    choose(r,F.COMPAT_PROGID,latest=True)
    r.values[F.COMPAT_COMMAND,'']=(f'"{old}" "%1"',F.REG_SZ)
    before=protected_values(r)
    result=refresh(current,r)
    expected=(f'"{current}" --open "%1"',F.REG_SZ)
    assert result['pcad_routes_current'] and result['compatibility_routes_updated']==1
    assert r.get(F.COMPAT_COMMAND,'')==expected
    assert r.get(F.PROJECT+r'\shell\open\command','')==expected
    assert r.get(F.APPLICATION+r'\shell\open\command','')==expected
    assert r.get(F.PCAD,'')==(F.COMPAT_PROGID,F.REG_SZ)
    assert protected_values(r)==before and not result['userchoice_written']
    journal=json.loads(r.get(F.STATE_KEY,F.COMPAT_STATE_VALUE)[0])
    assert journal['entries'][0]['previous']==[f'"{old}" "%1"',F.REG_SZ]
    assert refresh(current,r)['pcad_routes_current']
    assert json.loads(r.get(F.STATE_KEY,F.COMPAT_STATE_VALUE)[0])==journal


def test_selected_applications_route_without_registration_state_uses_exact_release_proof(apps):
    old,current,_=apps;r=Registry();choose(r,r'Applications\PromptCADStudio.exe')
    r.values[F.APPLICATION+r'\shell\open\command','']=(f'"{old}" "%1"',F.REG_SZ)
    before=protected_values(r)
    result=refresh(current,r,verified=[old])
    assert result['pcad_routes_current'] and not result['needs_user_selection']
    assert r.get(F.APPLICATION+r'\shell\open\command','')==(f'"{current}" --open "%1"',F.REG_SZ)
    assert protected_values(r)==before


def test_user_selected_verified_legacy_auto_file_does_not_need_matching_old_state_path(apps):
    old,current,historical=apps;r=Registry();F.register(old,_backend=r);choose(r,F.COMPAT_PROGID)
    r.values[F.COMPAT_COMMAND,'']=(f'"{historical}" --open "%1"',F.REG_SZ)
    assert refresh(current,r,verified=[historical])['pcad_routes_current']


@pytest.mark.parametrize('command',[
    'cmd.exe /c "C:\\Old\\PromptCADStudio.exe" "%1"',
    '"C:\\Old\\PromptCADStudio.exe" --open "%1" --extra',
    '"C:\\Old\\PromptCADStudio.exe" --open %1',
    '"PromptCADStudio.exe" "%1"',
    '"C:\\Old\\DifferentCAD.exe" "%1"',
    '"C:\\%APPDATA%\\PromptCADStudio.exe" "%1"',
])
def test_unsafe_or_unproved_compatibility_commands_are_never_rewritten(apps,command):
    old,current,_=apps;r=Registry();F.register(old,_backend=r);choose(r,F.COMPAT_PROGID)
    original=(command,F.REG_SZ);r.values[F.COMPAT_COMMAND,'']=original
    result=refresh(current,r,verified=[r'C:\Old\PromptCADStudio.exe'])
    assert not result['pcad_routes_current'] and result['needs_user_selection']
    assert result['compatibility_routes_updated']==0 and r.get(F.COMPAT_COMMAND,'')==original
    assert 'file_association_warning' in result


def test_other_cad_selection_and_json_state_are_preserved_and_reported_incomplete(apps):
    old,current,_=apps;r=Registry();F.register(old,_backend=r);choose(r,r'OtherVendor.CAD')
    key=F.CLASSES+r'\OtherVendor.CAD\shell\open\command'
    r.values[key,'']=('"C:\\OtherApp.exe" "%1"',F.REG_SZ)
    r.values[F.CLASSES+r'\.json','']=('JsonEditor.Project',F.REG_SZ)
    before=protected_values(r);other=r.get(key,'');json_default=r.get(F.CLASSES+r'\.json','')
    result=refresh(current,r)
    assert not result['pcad_routes_current'] and result['needs_user_selection']
    assert r.get(key,'')==other and r.get(F.CLASSES+r'\.json','')==json_default
    assert protected_values(r)==before


def test_same_basename_without_release_or_state_proof_is_not_ownership(apps):
    old,current,unproved=apps;r=Registry();F.register(old,_backend=r);choose(r,F.COMPAT_PROGID)
    original=(f'"{unproved}" "%1"',F.REG_SZ);r.values[F.COMPAT_COMMAND,'']=original
    assert refresh(current,r)['pcad_routes_current'] is False
    assert r.get(F.COMPAT_COMMAND,'')==original


def test_compatibility_metadata_failure_rolls_back_standard_commands_alias_and_ownership(apps):
    old,current,_=apps;r=Registry();F.register(old,_backend=r);choose(r,F.COMPAT_PROGID)
    r.values[F.COMPAT_COMMAND,'']=(f'"{old}" "%1"',F.REG_SZ)
    before=dict(r.values);r.fail=(F.STATE_KEY,F.COMPAT_STATE_VALUE)
    with pytest.raises(OSError,match='fake write failure'):refresh(current,r)
    assert r.values==before


def test_third_party_application_command_conflict_rolls_back_without_claiming_it(apps):
    old,current,_=apps;r=Registry();F.register(old,_backend=r);choose(r,r'Applications\PromptCADStudio.exe')
    r.values[F.APPLICATION+r'\shell\open\command','']=('"C:\\OtherApp.exe" "%1"',F.REG_SZ)
    before=dict(r.values)
    with pytest.raises(F.AssociationError,match='겹칩니다'):refresh(current,r)
    assert r.values==before


@pytest.mark.parametrize('registration,expected_exit',[(True,0),(False,3),('raises',3)])
def test_installer_distinguishes_payload_success_from_route_completion_without_OS(apps,tmp_path,monkeypatch,registration,expected_exit):
    _,current,_=apps
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(S,'canonical_install_dir',lambda:current.parent)
    monkeypatch.setattr(S,'windows_closed_guard',lambda exe:lambda:True)
    monkeypatch.setattr(S,'install_canonical',lambda *a,**k:dict(success=True,verified_payload=True,install_dir=str(current.parent),version='9.0.0'))
    monkeypatch.setattr(S,'require_canonical_executable',lambda exe:current)
    def fake_refresh(exe):
        assert exe==current
        if registration=='raises':raise F.AssociationError('owned connection conflict')
        return {'registration_succeeded':True,'pcad_routes_current':registration,'file_association_warning':'needs user selection' if not registration else ''}
    monkeypatch.setattr(F,'refresh_owned_pcad_routes',fake_refresh)
    report=tmp_path/'owned-install-result.json'
    assert S.run_install_cli(current,report)==expected_exit
    value=json.loads(report.read_text(encoding='utf-8'))
    assert value['success'] and value['verified_payload'] and value['payload_installed']
    assert value['installation_complete']==(expected_exit==0)


def test_updater_never_silently_skips_when_old_registration_identity_does_not_match(apps,monkeypatch):
    _,current,_=apps;calls=[]
    monkeypatch.setattr(D,'require_canonical_executable',lambda exe:current)
    monkeypatch.setattr(F,'is_registered',lambda *a,**k:False)
    def fake_refresh(exe):calls.append(exe);return dict(registration_succeeded=True,pcad_routes_current=True)
    monkeypatch.setattr(F,'refresh_owned_pcad_routes',fake_refresh)
    result={'version':'9.0.0'}
    D.refresh_file_registration(current.parent,result)
    assert calls==[current] and result['installation_complete']


def test_updater_cli_connection_failure_reports_partial_exit_without_reapplying_or_restarting(apps,tmp_path,monkeypatch):
    _,current,_=apps;apply_calls=[]
    monkeypatch.setattr(D,'require_canonical_directory',lambda p:current.parent)
    monkeypatch.setattr(D,'require_canonical_executable',lambda p:current)
    monkeypatch.setattr(D,'relocate_if_needed',lambda args:False)
    monkeypatch.setattr(D,'wait_for_app',lambda pid:None)
    monkeypatch.setattr(D,'cleanup_temporary_executable',lambda folder:None)
    def apply(*args,**kwargs):apply_calls.append(args);return dict(version='9.0.0',changed=1)
    monkeypatch.setattr(D,'apply_archive',apply)
    monkeypatch.setattr(F,'refresh_owned_pcad_routes',lambda exe:dict(registration_succeeded=True,pcad_routes_current=False,file_association_warning='kept other app'))
    report=tmp_path/'owned-update-result.json'
    monkeypatch.setattr(sys,'argv',['update_desktop.py','--install-dir',str(current.parent),'--apply-archive',str(tmp_path/'not-used.zip'),'--sha256','0'*64,'--report',str(report)])
    assert D.main()==3 and len(apply_calls)==1
    value=json.loads(report.read_text(encoding='utf-8'))
    assert value['payload_installed'] and value['changed']==1 and not value['installation_complete']
    assert value['file_association_warning']=='kept other app'


def test_powershell_installer_has_a_separate_partial_connection_exit():
    source=Path(__file__).resolve().parents[1]/'scripts/install_native.ps1'
    text=source.read_text(encoding='utf-8')
    assert '$cadProcess.ExitCode -notin @(0, 3)' in text
    assert 'if ($cadConnectionIncomplete) { exit 3 }' in text
    assert '$cadResult.installation_complete -and $cadResult.pcad_routes_current' in text
    assert '.pcad connection is NOT complete.' in text


def test_legacy_release_proof_reads_only_named_fixture_exe_and_checks_its_manifest_bytes(apps):
    old,_,_=apps
    assert not F._verify_release_executable(old)
    manifest={'app':'PromptCADStudio','schema':1,'version':'1.0.0','files':{
        F.EXE_NAME:{'size':old.stat().st_size,'sha256':hashlib.sha256(old.read_bytes()).hexdigest()}}}
    (old.parent/'install-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    assert F._verify_release_executable(old)
    old.write_bytes(b'changed fake app')
    assert not F._verify_release_executable(old)


def test_large_or_invalid_legacy_release_manifest_cannot_prove_an_alias(apps):
    old,_,_=apps;manifest=old.parent/'install-manifest.json'
    manifest.write_text('{invalid owned fixture',encoding='utf-8')
    assert not F._verify_release_executable(old)
    with manifest.open('wb') as stream:stream.truncate(8*1024**2+1)
    assert not F._verify_release_executable(old)


def test_malformed_compatibility_ownership_is_preserved_without_any_registry_write(apps):
    old,current,_=apps;r=Registry();F.register(old,_backend=r)
    r.values[F.STATE_KEY,F.COMPAT_STATE_VALUE]=('{invalid owned metadata',F.REG_SZ)
    before=dict(r.values);writes=len(r.writes)
    with pytest.raises(F.AssociationError,match='소유 기록'):refresh(current,r)
    assert r.values==before and len(r.writes)==writes


def test_noncanonical_validation_failure_happens_before_registry_access(apps):
    _,current,_=apps;r=Registry()
    def reject(path):raise RuntimeError('not the canonical verified EXE')
    with pytest.raises(RuntimeError,match='canonical'):
        F.refresh_owned_pcad_routes(current,_backend=r,_canonical_validator=reject)
    assert r.values=={} and r.writes==[]


def test_hard_payload_failure_returns_install_exit_two_and_does_not_register(apps,tmp_path,monkeypatch):
    _,current,_=apps
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(S,'canonical_install_dir',lambda:current.parent)
    monkeypatch.setattr(S,'windows_closed_guard',lambda exe:lambda:True)
    def blocked(*a,**k):raise S.U.UpdateError('owned fake running-app gate blocked')
    monkeypatch.setattr(S,'install_canonical',blocked)
    def forbidden(*a,**k):raise AssertionError('No registration after payload failure')
    monkeypatch.setattr(F,'refresh_owned_pcad_routes',forbidden)
    report=tmp_path/'owned-hard-failure.json'
    assert S.run_install_cli(current,report)==2
    value=json.loads(report.read_text(encoding='utf-8'))
    assert not value['success'] and 'payload_installed' not in value


def test_updater_registry_conflict_is_reported_as_partial_without_undoing_payload(apps,monkeypatch):
    _,current,_=apps
    monkeypatch.setattr(D,'require_canonical_executable',lambda p:current)
    def blocked(*a,**k):raise F.AssociationError('owned fake conflicting handler')
    monkeypatch.setattr(F,'refresh_owned_pcad_routes',blocked)
    result={'version':'9.0.0','changed':7}
    assert D.refresh_file_registration(current.parent,result) is result
    assert result['payload_installed'] and not result['installation_complete']
    assert result['changed']==7 and 'conflicting handler' in result['file_association_warning']


def test_schema_two_retired_json_values_restore_if_later_compatibility_metadata_write_fails(apps):
    old,current,_=apps;r=Registry();F.register(old,_backend=r)
    state=json.loads(r.get(F.STATE_KEY,F.STATE_VALUE)[0])
    state['schema']=2
    for entry in F._retired_entries():
        r.values[entry.key,entry.name]=(entry.value,F.REG_SZ)
        state['entries'].append(dict(key=entry.key,name=entry.name,value=entry.value))
    r.values[F.STATE_KEY,F.STATE_VALUE]=(json.dumps(state),F.REG_SZ)
    choose(r,F.COMPAT_PROGID)
    r.values[F.COMPAT_COMMAND,'']=(f'"{old}" "%1"',F.REG_SZ)
    before=dict(r.values);r.fail=(F.STATE_KEY,F.COMPAT_STATE_VALUE)
    with pytest.raises(OSError,match='fake write failure'):refresh(current,r)
    assert r.values==before
    assert all(r.get(entry.key,entry.name)==(entry.value,F.REG_SZ) for entry in F._retired_entries())
    assert json.loads(r.get(F.STATE_KEY,F.STATE_VALUE)[0])['schema']==2
