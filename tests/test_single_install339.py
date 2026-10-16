"""Fake-byte filesystem installs only; no live process queries or app execution."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cadstudio import single_install as S
from cadstudio import updater as U


@pytest.fixture(autouse=True)
def no_live_os_or_process_operations(monkeypatch):
    monkeypatch.setattr(U,'require_closed',lambda folder:None)
    def forbidden(*args,**kwargs):raise AssertionError('No live process query or launch in this fixture.')
    monkeypatch.setattr(S.subprocess,'run',forbidden)
    monkeypatch.setattr(S,'windows_closed_guard',forbidden)


def bundle(path,version='3.4.0',extra=None):
    path.mkdir(parents=True)
    for name,value in {U.EXE:b'new fake executable','_internal/shared.dll':b'shared fake dependency',**(extra or {})}.items():
        target=path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
    U.make_manifest(path,version)
    return path


def test_first_install_copies_owned_payload_only_and_has_one_stable_destination(tmp_path):
    source=bundle(tmp_path/'download');(source/'private.pcad').write_bytes(b'private project')
    destination=tmp_path/'Programs/PromptCADStudio';checks=[]
    result=S.install_canonical(source,destination,closed_callback=lambda:checks.append('closed'))
    assert result['success'] and result['mode']=='installed' and result['verified_payload']
    assert len(checks)==2 and destination.joinpath(U.EXE).read_bytes()==b'new fake executable'
    assert not (destination/'private.pcad').exists() and (source/'private.pcad').read_bytes()==b'private project'
    assert S.verify_payload(destination)['version']=='3.4.0'
    assert not list(destination.parent.glob('.PromptCADStudio-install-*'))


def test_existing_update_removes_only_owned_old_program_files_preserves_profile_and_custom_files(tmp_path):
    source=bundle(tmp_path/'new',extra={'_internal/new.dll':b'new dependency','docs/guide.md':b'new guide'})
    target=bundle(tmp_path/'install','3.3.0',extra={U.EXE:b'old app','_internal/old.exe':b'old program','docs/guide.md':b'old guide'})
    (target/'docs/guide.md').write_bytes(b'user edited guide')
    (target/'my.pcad').write_bytes(b'user project');(target/'profile-public-3.3.0').mkdir()
    (target/'profile-public-3.3.0/settings.json').write_bytes(b'private settings')
    checks=[];result=S.install_canonical(source,target,closed_callback=lambda:checks.append('closed'))
    assert result['mode']=='updated' and result['removed']==1 and len(checks)==5
    assert not (target/'_internal/old.exe').exists() and (target/U.EXE).read_bytes()==b'new fake executable'
    assert (target/'my.pcad').read_bytes()==b'user project'
    assert (target/'profile-public-3.3.0/settings.json').read_bytes()==b'private settings'
    assert (target/'docs/guide.md').read_bytes()==b'user edited guide' and result['preserved_documents']==['docs/guide.md']
    assert not (target/'.cad-update').exists() and not list(target.parent.glob('.PromptCADStudio-install-*'))


def test_unknown_nonempty_destination_and_unknown_path_collision_are_preserved(tmp_path):
    source=bundle(tmp_path/'release',extra={'custom.dll':b'release file'})
    unknown=tmp_path/'unknown';unknown.mkdir();(unknown/'private.pcad').write_bytes(b'precious')
    with pytest.raises(U.UpdateError,match='알 수 없는'):S.install_canonical(source,unknown,closed_callback=lambda:None)
    assert list(unknown.iterdir())==[unknown/'private.pcad']
    target=bundle(tmp_path/'old','3.3.0');(target/'custom.dll').write_bytes(b'custom user file')
    with pytest.raises(U.UpdateError,match='사용자 파일'):S.install_canonical(source,target,closed_callback=lambda:None)
    assert (target/'custom.dll').read_bytes()==b'custom user file' and U.installed_version(target)=='3.3.0'


def test_payload_hash_failure_and_downgrade_do_not_mutate_destination(tmp_path):
    target=bundle(tmp_path/'old','3.4.0');before=(target/U.MANIFEST).read_bytes()
    source=bundle(tmp_path/'source','3.3.0')
    with pytest.raises(U.UpdateError,match='이전 버전'):S.install_canonical(source,target,closed_callback=lambda:None)
    assert (target/U.MANIFEST).read_bytes()==before
    bad=bundle(tmp_path/'bad','3.5.0');(bad/'_internal/shared.dll').write_bytes(b'tampered')
    with pytest.raises(U.UpdateError,match='검증'):S.install_canonical(bad,target,closed_callback=lambda:None)
    assert (target/U.MANIFEST).read_bytes()==before


@pytest.mark.parametrize('fail_at',[1,2,3,4,5])
def test_fresh_global_close_check_failure_before_swap_preserves_old_install(tmp_path,fail_at):
    source=bundle(tmp_path/'new');target=bundle(tmp_path/'old','3.3.0',extra={U.EXE:b'old executable'})
    before=(target/U.MANIFEST).read_bytes();calls=[]
    def closed():
        calls.append(len(calls)+1)
        if len(calls)==fail_at:raise U.UpdateError('Owned simulated CAD reopened')
    with pytest.raises(U.UpdateError,match='reopened'):S.install_canonical(source,target,closed_callback=closed)
    assert len(calls)==fail_at and (target/U.MANIFEST).read_bytes()==before and (target/U.EXE).read_bytes()==b'old executable'
    assert not (target/'.cad-update').exists() and not list(target.parent.glob('.PromptCADStudio-install-*'))


def test_transaction_failure_after_partial_replace_rolls_back_and_cleans_owned_temp(tmp_path,monkeypatch):
    source=bundle(tmp_path/'new',extra={'_internal/new.dll':b'new'})
    target=bundle(tmp_path/'old','3.3.0',extra={U.EXE:b'old','_internal/old.exe':b'old helper'})
    before=(target/U.MANIFEST).read_bytes();replace=U.os.replace;triggered=[]
    def fail_once(src,dst):
        if Path(src).name==U.MANIFEST and Path(src).parent.name=='stage' and not triggered:
            triggered.append(True);raise PermissionError('Owned simulated commit failure')
        return replace(src,dst)
    monkeypatch.setattr(U.os,'replace',fail_once)
    with pytest.raises(PermissionError,match='simulated'):S.install_canonical(source,target,closed_callback=lambda:None)
    assert triggered and (target/U.MANIFEST).read_bytes()==before and (target/U.EXE).read_bytes()==b'old'
    assert (target/'_internal/old.exe').read_bytes()==b'old helper' and not (target/'_internal/new.dll').exists()
    assert not (target/'.cad-update').exists() and not list(target.parent.glob('.PromptCADStudio-install-*'))


@pytest.mark.parametrize('preexisting_empty',[False,True])
def test_first_install_failed_atomic_swap_restores_empty_or_absent_target(tmp_path,monkeypatch,preexisting_empty):
    source=bundle(tmp_path/'source');target=tmp_path/'target'
    if preexisting_empty:target.mkdir()
    replace=S.os.replace
    def fail_stage(src,dst):
        if Path(src).name=='stage' and Path(dst)==target:raise PermissionError('Owned atomic rename failure')
        return replace(src,dst)
    monkeypatch.setattr(S.os,'replace',fail_stage)
    with pytest.raises(PermissionError,match='rename'):S.install_canonical(source,target,closed_callback=lambda:None)
    assert target.exists()==preexisting_empty
    if preexisting_empty:assert not list(target.iterdir())
    assert not list(tmp_path.glob('.PromptCADStudio-install-*'))


def test_canonical_self_install_is_verified_no_change_and_noncanonical_registration_is_blocked(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path));canonical=bundle(S.canonical_install_dir())
    before={p.relative_to(canonical).as_posix():p.read_bytes() for p in canonical.rglob('*') if p.is_file()}
    result=S.install_canonical(canonical,canonical,closed_callback=lambda:None)
    assert result['mode']=='already_canonical' and result['changed']==result['removed']==0
    assert S.require_canonical_executable(canonical/U.EXE)==canonical/U.EXE
    assert before=={p.relative_to(canonical).as_posix():p.read_bytes() for p in canonical.rglob('*') if p.is_file()}
    download=bundle(tmp_path/'download')
    with pytest.raises(U.UpdateError,match='한 곳'):S.require_canonical_executable(download/U.EXE)


def test_false_close_callback_blocks_without_install(tmp_path):
    source=bundle(tmp_path/'source');target=tmp_path/'target'
    with pytest.raises(U.UpdateError,match='종료'):S.install_canonical(source,target,closed_callback=lambda:False)
    assert not target.exists()


def process(pid,name='PromptCADStudio.exe',parent=1,exe='C:/test/PromptCADStudio.exe',command='"C:/test/PromptCADStudio.exe" --install-canonical "C:/test/report.json"'):
    return dict(ProcessId=pid,ParentProcessId=parent,Name=name,ExecutablePath=exe,CommandLine=command)


def test_global_guard_excludes_only_exact_headless_self_and_verified_windowless_parent():
    rows=[process(10,parent=9),process(9,parent=8),process(8,name='powershell.exe',exe='C:/Windows/powershell.exe',command='powershell')]
    result=S.validate_process_snapshot(rows,installer_pid=10,executable='C:/test/PromptCADStudio.exe',window_pids=set())
    assert result['excluded_headless_pids']==[9,10]
    for extra in [process(11,parent=10),process(12,parent=9),process(13,exe='C:/old/PromptCADStudio.exe')]:
        with pytest.raises(U.UpdateError,match=str(extra['ProcessId'])):
            S.validate_process_snapshot(rows+[extra],installer_pid=10,executable='C:/test/PromptCADStudio.exe',window_pids=set())
    with pytest.raises(U.UpdateError,match='9'):
        S.validate_process_snapshot(rows,installer_pid=10,executable='C:/test/PromptCADStudio.exe',window_pids={9})


def test_guard_does_not_hide_gui_parent_or_unreadable_python_source_and_never_queries_OS():
    rows=[process(10,parent=9),process(9,command='"C:/test/PromptCADStudio.exe" --open design.pcad')]
    with pytest.raises(U.UpdateError,match='9'):S.validate_process_snapshot(rows,installer_pid=10,executable='C:/test/PromptCADStudio.exe',window_pids=set())
    python=process(14,name='pythonw.exe',exe='C:/python/pythonw.exe',command='pythonw.exe "C:/source/native_desktop.py"')
    with pytest.raises(U.UpdateError,match='14'):S.validate_process_snapshot([rows[0],python],installer_pid=10,executable='C:/test/PromptCADStudio.exe',window_pids=set())
    python['CommandLine']=None
    with pytest.raises(U.UpdateError,match='확인할 수 없는'):S.validate_process_snapshot([rows[0],python],installer_pid=10,executable='C:/test/PromptCADStudio.exe',window_pids=set())
    with pytest.raises(U.UpdateError,match='현재 설치 프로세스'):S.validate_process_snapshot([],installer_pid=10,executable='C:/test/PromptCADStudio.exe',window_pids=set())


def test_updater_detects_canonical_not_download_folder_and_explicit_wrong_path_is_rejected(tmp_path,monkeypatch):
    import update_desktop as desktop
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path));download=bundle(tmp_path/'download')
    monkeypatch.setattr(desktop.sys,'frozen',True,raising=False);monkeypatch.setattr(desktop.sys,'executable',str(download/'PromptCADStudioUpdater.exe'))
    assert desktop.detect_install() is None
    canonical=bundle(S.canonical_install_dir());assert desktop.detect_install()==canonical
    with pytest.raises(U.UpdateError,match='한 곳'):desktop.canonical_installation(download)


def test_reparse_payload_member_blocks_before_destination_mutation(tmp_path,monkeypatch):
    from types import SimpleNamespace
    source=bundle(tmp_path/'source');target=tmp_path/'target';real_lstat=Path.lstat
    def injected(path,*args,**kwargs):
        result=real_lstat(path,*args,**kwargs)
        if path==source/'_internal/shared.dll':
            return SimpleNamespace(st_mode=result.st_mode,st_file_attributes=0x400)
        return result
    monkeypatch.setattr(Path,'lstat',injected)
    with pytest.raises(U.UpdateError,match='재분석'):S.install_canonical(source,target,closed_callback=lambda:None)
    assert not target.exists()


def test_release_manifest_cannot_take_ownership_of_user_profile(tmp_path):
    # Malformed historic/untrusted manifests bypass the normal authoring helper,
    # which now rejects profile ownership at shared manifest validation too.
    def claim_profile(path,value):
        member=path/'profile-public-old/settings.json';member.parent.mkdir();member.write_bytes(value)
        data=json.loads((path/U.MANIFEST).read_text(encoding='utf-8'))
        data['files']['profile-public-old/settings.json']=dict(size=len(value),sha256=U.digest(member))
        U.write_json(path/U.MANIFEST,data)
        return path
    source=claim_profile(bundle(tmp_path/'source'),b'not a program file')
    with pytest.raises(U.UpdateError,match='사용자 프로필'):S.install_canonical(source,tmp_path/'target',closed_callback=lambda:None)
    target=claim_profile(bundle(tmp_path/'old','3.3.0'),b'precious private settings')
    source=bundle(tmp_path/'clean-source')
    with pytest.raises(U.UpdateError,match='사용자 프로필'):S.install_canonical(source,target,closed_callback=lambda:None)
    assert (target/'profile-public-old/settings.json').read_bytes()==b'precious private settings'


def test_updater_optional_callback_preserves_all_three_legacy_folder_close_checks(tmp_path,monkeypatch):
    from zipfile import ZipFile
    source=bundle(tmp_path/'source');target=bundle(tmp_path/'target','3.3.0');archive=tmp_path/'update.zip'
    with ZipFile(archive,'x') as zipped:
        for path in source.rglob('*'):
            if path.is_file():zipped.write(path,'PromptCADStudio/'+path.relative_to(source).as_posix())
    calls=[];monkeypatch.setattr(U,'require_closed',lambda folder:calls.append(folder))
    result=U.apply_archive(target,archive,U.digest(archive))
    assert result['version']=='3.4.0' and calls==[target,target,target]


def test_updater_false_global_callback_does_not_replace_any_program_file(tmp_path):
    source=bundle(tmp_path/'source');target=bundle(tmp_path/'target','3.3.0',extra={U.EXE:b'old app'})
    with pytest.raises(U.UpdateError,match='종료 확인'):
        U.apply_archive(target,tmp_path/'not-read.zip','0'*64,closed_callback=lambda:False)
    assert (target/U.EXE).read_bytes()==b'old app' and U.installed_version(target)=='3.3.0'
