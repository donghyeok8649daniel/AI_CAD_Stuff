"""New ownership regressions only; fake bytes, no live install/OS/process calls."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from cadstudio import single_install as S
from cadstudio import updater as U


@pytest.fixture(autouse=True)
def no_live_operations(monkeypatch):
    monkeypatch.setattr(U,'require_closed',lambda folder:None)
    def forbidden(*args,**kwargs):raise AssertionError('No OS query or process launch in ownership fixtures.')
    monkeypatch.setattr(S,'windows_closed_guard',forbidden)
    monkeypatch.setattr(S.subprocess,'run',forbidden)


def bundle(path,version='3.4.0',extra=None):
    path.mkdir()
    for name,value in {U.EXE:b'new fake app','_internal/core.dll':b'fake dependency',**(extra or {})}.items():
        target=path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
    U.make_manifest(path,version)
    return path


def archive(path,destination,overrides=None):
    with ZipFile(destination,'x') as output:
        for item in path.rglob('*'):
            if item.is_file():
                name=item.relative_to(path).as_posix()
                output.writestr('PromptCADStudio/'+name,(overrides or {}).get(name,item.read_bytes()))
    return destination,U.digest(destination)


def snapshot(path):
    return {p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob('*')
            if p.is_file() and p.name!='.cad-update.lock'}


def claim_profile(path,name='profile-private/settings.json'):
    target=path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'private profile')
    data=json.loads((path/U.MANIFEST).read_text(encoding='utf-8'))
    data['files'][name]=dict(size=target.stat().st_size,sha256=U.digest(target))
    U.write_json(path/U.MANIFEST,data)
    return path


def test_identical_unowned_program_is_not_claimed_and_destination_stays_exact(tmp_path):
    target=bundle(tmp_path/'old','3.3.0',extra={U.EXE:b'old fake app'})
    (target/'unowned.dll').write_bytes(b'same bytes')
    source=bundle(tmp_path/'new',extra={'unowned.dll':b'same bytes'})
    before=snapshot(target)
    with pytest.raises(U.UpdateError,match='사용자 파일'):
        U.apply_archive(target,*archive(source,tmp_path/'release.zip'))
    assert snapshot(target)==before and not (target/'.cad-update').exists()
    assert 'unowned.dll' not in json.loads((target/U.MANIFEST).read_text())['files']


@pytest.mark.parametrize('name,value',[('docs/user.md',b'same document'),('examples/user.pcad',b'same document'),('docs/different.md',b'personal edits')])
def test_unowned_documents_never_become_release_owned_or_removed_on_next_update(tmp_path,name,value):
    target=bundle(tmp_path/'old','3.3.0',extra={'docs/known.md':b'old owned guide'})
    (target/'docs/known.md').write_bytes(b'edited owned guide')
    user=target/name;user.parent.mkdir(parents=True,exist_ok=True);user.write_bytes(value)
    source=bundle(tmp_path/'new',extra={name:b'same document','docs/known.md':b'new owned guide'})
    source_manifest=(source/U.MANIFEST).read_bytes()
    result=S.install_canonical(source,target,closed_callback=lambda:None)
    installed=json.loads((target/U.MANIFEST).read_text())
    assert set(result['preserved_documents'])=={name,'docs/known.md'}
    assert user.read_bytes()==value and name not in installed['files']
    # Existing owned-but-edited document behavior is intentionally unchanged.
    assert 'docs/known.md' in installed['files'] and (target/'docs/known.md').read_bytes()==b'edited owned guide'
    assert (source/U.MANIFEST).read_bytes()==source_manifest
    assert result['verified_payload'] and S.verify_payload(target,preserved_documents=result['preserved_documents'])
    later=bundle(tmp_path/'later','3.5.0')
    U.apply_archive(target,*archive(later,tmp_path/'later.zip'))
    assert user.read_bytes()==value and name not in json.loads((target/U.MANIFEST).read_text())['files']
    assert (target/'docs/known.md').read_bytes()==b'edited owned guide'
    assert not (target/'.cad-update').exists() and not list(tmp_path.glob('.PromptCADStudio-install-*'))


@pytest.mark.parametrize('member',['_internal/core.dll','docs/user.md'])
def test_all_archive_member_hashes_checked_even_for_equal_or_preserved_destinations(tmp_path,member):
    source=bundle(tmp_path/'new',extra={'docs/user.md':b'official guide'})
    target=bundle(tmp_path/'old','3.3.0')
    (target/'docs').mkdir();(target/'docs/user.md').write_bytes(b'official guide')
    original=(source/member).read_bytes();corrupt=b'x'*len(original)
    before=snapshot(target)
    with pytest.raises(U.UpdateError,match='검증'):
        U.apply_archive(target,*archive(source,tmp_path/'bad.zip',{member:corrupt}))
    assert snapshot(target)==before and not (target/'.cad-update').exists()


@pytest.mark.parametrize('which',['incoming','previous'])
def test_direct_updater_rejects_profile_ownership_before_any_payload_change(tmp_path,which):
    target=bundle(tmp_path/'old','3.3.0',extra={U.EXE:b'old fake app'})
    source=bundle(tmp_path/'new')
    claim_profile(source if which=='incoming' else target)
    before=snapshot(target)
    with pytest.raises(U.UpdateError,match='사용자 프로필'):
        U.apply_archive(target,*archive(source,tmp_path/'profile.zip'))
    assert snapshot(target)==before and not (target/'.cad-update').exists()
    assert S.reject_profile_ownership is U.reject_profile_ownership


@pytest.mark.parametrize('prefix',['profile','profiles','userdata','PROFILE-private'])
def test_shared_manifest_guard_rejects_every_reserved_profile_root(tmp_path,prefix):
    source=bundle(tmp_path/'source')
    data=json.loads((source/U.MANIFEST).read_text())
    data['files'][prefix+'/settings.json']=dict(size=0,sha256=hashlib.sha256(b'').hexdigest())
    with pytest.raises(U.UpdateError,match='사용자 프로필'):U.validate_manifest(data)


def test_legacy_without_manifest_keeps_equal_document_unowned_across_updates(tmp_path):
    target=bundle(tmp_path/'legacy','3.3.0',extra={'docs/user.md':b'identical notes'})
    (target/U.MANIFEST).unlink()
    source=bundle(tmp_path/'new',extra={'docs/user.md':b'identical notes'})
    first=U.apply_archive(target,*archive(source,tmp_path/'first.zip'))
    assert first['preserved_documents']==['docs/user.md']
    assert 'docs/user.md' not in json.loads((target/U.MANIFEST).read_text())['files']
    later=bundle(tmp_path/'later','3.5.0')
    U.apply_archive(target,*archive(later,tmp_path/'second.zip'))
    assert (target/'docs/user.md').read_bytes()==b'identical notes'
