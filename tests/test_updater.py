import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from cadstudio import updater as U


def bundle(root, release='2.1.1', **files):
    root.mkdir(parents=True)
    payload = {'PromptCADStudio.exe': b'new executable', '_internal/shared.dll': b'shared dependency', **files}
    for name, value in payload.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    U.make_manifest(root, release)
    return root


def archive(root, destination):
    with ZipFile(destination, 'w') as zipped:
        for file in root.rglob('*'):
            if file.is_file():
                zipped.write(file, 'PromptCADStudio/' + file.relative_to(root).as_posix())
    return destination, U.digest(destination)


def test_replaces_in_place_and_removes_owned_obsolete_files(tmp_path):
    target = bundle(tmp_path/'기존 설치', '2.1.0', **{'PromptCADStudio.exe': b'old', '_internal/obsolete.dll': b'old lib'})
    project = target/'my robot.cad.json'
    project.write_text('precious document')
    shared_time = (target/'_internal/shared.dll').stat().st_mtime_ns
    source = bundle(tmp_path/'release')
    zip_path, sha = archive(source, tmp_path/'update.zip')
    result = U.apply_archive(target, zip_path, sha)
    assert result['changed'] == 1 and result['removed'] == 1
    assert (target/U.EXE).read_bytes() == b'new executable'
    assert not (target/'_internal/obsolete.dll').exists()
    assert (target/'_internal/shared.dll').stat().st_mtime_ns == shared_time
    assert project.read_text() == 'precious document'
    assert not (target/'.cad-update').exists()
    assert U.installed_version(target) == '2.1.1'


def test_legacy_install_preserves_documents_and_unknown_files(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0', **{'PromptCADStudio.exe': b'old', 'examples/user.cad.json': b'user changes', 'docs/guide.md': b'old notes'})
    (target/U.MANIFEST).unlink()
    source = bundle(tmp_path/'new', **{'examples/user.cad.json': b'new example', 'docs/guide.md': b'new notes'})
    result = U.apply_archive(target, *archive(source, tmp_path/'update.zip'))
    assert (target/'examples/user.cad.json').read_bytes() == b'user changes'
    assert (target/'docs/guide.md').read_bytes() == b'old notes'
    assert sorted(result['preserved_documents']) == ['docs/guide.md', 'examples/user.cad.json']
    assert U.installed_version(target) == '2.1.1'


def test_modified_examples_are_preserved_on_future_updates(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0', **{'examples/keep.cad.json': b'original', 'docs/removed.md': b'original'})
    (target/'examples/keep.cad.json').write_bytes(b'edited design')
    (target/'docs/removed.md').write_bytes(b'edited notes')
    source = bundle(tmp_path/'new', **{'examples/keep.cad.json': b'new example'})
    U.apply_archive(target, *archive(source, tmp_path/'update.zip'))
    assert (target/'examples/keep.cad.json').read_bytes() == b'edited design'
    assert (target/'docs/removed.md').read_bytes() == b'edited notes'


def test_wrong_hash_makes_no_change(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0')
    source = bundle(tmp_path/'new')
    zip_path, _ = archive(source, tmp_path/'update.zip')
    before = (target/U.MANIFEST).read_bytes()
    with pytest.raises(U.UpdateError, match='SHA256'):
        U.apply_archive(target, zip_path, '0'*64)
    assert (target/U.MANIFEST).read_bytes() == before
    assert not (target/'.cad-update').exists()


@pytest.mark.parametrize('bad', ['../outside', '/absolute', 'C:/file', 'a\\b', 'a:ads', 'aux.txt', 'a/../b', 'x.', '.cad-update/x', 'a//b', 'COM1', 'a/<b'])
def test_windows_path_attacks_rejected(bad):
    with pytest.raises(U.UpdateError):
        U.relative_path(bad)


def test_archive_extra_member_rejected_before_mutation(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0', **{'PromptCADStudio.exe': b'old'})
    source = bundle(tmp_path/'new')
    zip_path, _ = archive(source, tmp_path/'update.zip')
    with ZipFile(zip_path, 'a') as zipped:
        zipped.writestr('../outside.txt', b'no')
    with pytest.raises(U.UpdateError, match='파일 목록'):
        U.apply_archive(target, zip_path, U.digest(zip_path))
    assert (target/U.EXE).read_bytes() == b'old'
    assert not (tmp_path/'outside.txt').exists()


def test_failure_halfway_restores_previous_install(tmp_path, monkeypatch):
    target = bundle(tmp_path/'old', '2.1.0', **{'PromptCADStudio.exe': b'old', '_internal/obsolete.dll': b'old lib'})
    source = bundle(tmp_path/'new', **{'_internal/new.dll': b'new lib'})
    zip_path, sha = archive(source, tmp_path/'update.zip')
    old_manifest = (target/U.MANIFEST).read_bytes()
    real_replace = U.os.replace
    triggered = []
    def broken(src, dest):
        if Path(src).name == U.MANIFEST and 'stage' in Path(src).parts and not triggered:
            triggered.append(True)
            raise PermissionError('simulated locked file')
        return real_replace(src, dest)
    monkeypatch.setattr(U.os, 'replace', broken)
    with pytest.raises(PermissionError):
        U.apply_archive(target, zip_path, sha)
    assert triggered
    assert (target/U.EXE).read_bytes() == b'old'
    assert (target/'_internal/obsolete.dll').read_bytes() == b'old lib'
    assert not (target/'_internal/new.dll').exists()
    assert (target/U.MANIFEST).read_bytes() == old_manifest
    assert not (target/'.cad-update').exists()


def test_interrupted_transaction_recovered_before_next_update(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0', **{'PromptCADStudio.exe': b'old'})
    work = U.transaction_dir(target)
    (work/'backup').mkdir()
    (target/U.EXE).replace(work/'backup'/U.EXE)
    (target/U.EXE).write_bytes(b'half installed')
    U.write_json(work/'transaction.json', {'state': 'applying', 'operations': [{'name': U.EXE, 'existed': True, 'new_hash': U.digest(target/U.EXE)}]})
    U.recover(target, work)
    assert (target/U.EXE).read_bytes() == b'old'
    source = bundle(tmp_path/'new')
    U.apply_archive(target, *archive(source, tmp_path/'update.zip'))
    assert (target/U.EXE).read_bytes() == b'new executable'
    assert not work.exists()


def test_not_enough_space_and_downgrade_are_non_destructive(tmp_path, monkeypatch):
    target = bundle(tmp_path/'old', '2.1.0', **{'PromptCADStudio.exe': b'old'})
    source = bundle(tmp_path/'new')
    zip_path, sha = archive(source, tmp_path/'update.zip')
    monkeypatch.setattr(U.shutil, 'disk_usage', lambda path: type('Disk', (), {'free': 0})())
    with pytest.raises(U.UpdateError, match='공간'):
        U.apply_archive(target, zip_path, sha)
    assert (target/U.EXE).read_bytes() == b'old'
    older = bundle(tmp_path/'older', '2.0.0')
    with pytest.raises(U.UpdateError, match='이전 버전'):
        U.apply_archive(target, *archive(older, tmp_path/'older.zip'))
    assert U.installed_version(target) == '2.1.0'


def test_download_failure_cleans_temp_and_preserves_app(tmp_path, monkeypatch):
    target = bundle(tmp_path/'old', '2.1.0', **{'PromptCADStudio.exe': b'old'})
    def fail(release, destination, progress):
        destination.write_bytes(b'partial network response')
        raise ConnectionError('disconnected')
    monkeypatch.setattr(U, 'download', fail)
    with pytest.raises(ConnectionError):
        U.apply_archive(target, None, None, release={'size': 100, 'sha256': '0'*64})
    assert (target/U.EXE).read_bytes() == b'old'
    assert not (target/'.cad-update').exists()


def test_unowned_collision_and_case_renames_do_not_overwrite(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0')
    (target/'mine.txt').write_bytes(b'my data')
    source = bundle(tmp_path/'new', **{'mine.txt': b'release data'})
    with pytest.raises(U.UpdateError, match='사용자 파일'):
        U.apply_archive(target, *archive(source, tmp_path/'update.zip'))
    assert (target/'mine.txt').read_bytes() == b'my data'
    manifest = json.loads((source/U.MANIFEST).read_text())
    manifest['files']['_internal/SHARED.dll'] = manifest['files'].pop('_internal/shared.dll')
    U.write_json(source/U.MANIFEST, manifest)
    with pytest.raises(U.UpdateError, match='대소문자'):
        U.apply_archive(target, *archive(source, tmp_path/'case.zip'))


def test_repeated_update_keeps_single_copy(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0', **{'PromptCADStudio.exe': b'old'})
    source = bundle(tmp_path/'new')
    zip_path, sha = archive(source, tmp_path/'update.zip')
    U.apply_archive(target, zip_path, sha)
    result = U.apply_archive(target, zip_path, sha)
    assert result['changed'] == result['removed'] == 0
    assert len(list(target.rglob(U.EXE))) == 1
    assert not list(target.rglob('*.zip'))
    assert not (target/'.cad-update').exists()


def test_unknown_staging_folder_is_never_deleted(tmp_path):
    target = bundle(tmp_path/'old', '2.1.0')
    work = target/'.cad-update'
    work.mkdir()
    (work/'my-file').write_text('keep')
    source = bundle(tmp_path/'new')
    with pytest.raises(U.UpdateError, match='임시 폴더'):
        U.apply_archive(target, *archive(source, tmp_path/'update.zip'))
    assert (work/'my-file').read_text() == 'keep'
