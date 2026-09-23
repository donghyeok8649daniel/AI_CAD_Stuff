"""Verified, transactional updates of an existing Windows portable installation.

Only files owned by a release manifest are replaced/removed. User documents and
the application's LocalAppData directory are never enumerated for deletion.
This module intentionally has no CAD or GUI dependencies.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import urllib.request
from zipfile import ZipFile

APP_ID = 'PromptCADStudio'
MANIFEST = 'install-manifest.json'
EXE = 'PromptCADStudio.exe'
REPOSITORY = 'donghyeok8649daniel/AI_CAD_Stuff'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
DOWNLOAD = f'https://github.com/{REPOSITORY}/releases/download/'
MAX_ARCHIVE = 1024**3
MAX_EXPANDED = 3 * 1024**3
RESERVED = {'.cad-update', '.cad-update.lock', MANIFEST.casefold()}


class UpdateError(RuntimeError):
    pass


def version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise UpdateError('지원하지 않는 버전 번호입니다.')
    return tuple(map(int, match.groups()))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative_path(name):
    """Use Windows rules even when validation tests run on another platform."""
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise UpdateError('잘못된 업데이트 파일 경로입니다.')
    parts = name.split('/')
    if any(not p or p in {'.', '..'} or p.endswith((' ', '.')) or
           re.search(r'[<>"|?*\x00-\x1f]', p) or
           re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
           for p in parts):
        raise UpdateError('안전하지 않은 업데이트 파일 경로입니다.')
    if parts[0].casefold() in RESERVED:
        raise UpdateError('업데이트 관리 경로와 충돌합니다.')
    return PurePosixPath(name)


def contained(root, name):
    path = root.joinpath(*relative_path(name).parts)
    # Reject junctions/symlinks, including ones pointing back inside the install.
    for item in [path, *path.parents]:
        if item == root:
            break
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise UpdateError('설치 폴더의 링크 경로는 업데이트할 수 없습니다.')
        if item != path and item.exists() and not item.is_dir():
            raise UpdateError('업데이트 경로가 기존 파일과 겹칩니다.')
    if not path.resolve().is_relative_to(root.resolve()):
        raise UpdateError('설치 폴더 밖으로 나가는 경로입니다.')
    return path


def validate_manifest(data):
    if data.get('app') != APP_ID or data.get('schema') != 1:
        raise UpdateError('Prompt CAD Studio 설치 정보가 아닙니다.')
    version(data['version'])
    files = data.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 20000 or EXE not in files:
        raise UpdateError('업데이트 파일 목록이 잘못되었습니다.')
    seen = set()
    total = 0
    for name, entry in files.items():
        relative_path(name)
        if name.casefold() in seen:
            raise UpdateError('업데이트에 중복 경로가 있습니다.')
        seen.add(name.casefold())
        if not isinstance(entry, dict) or not re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256', ''))):
            raise UpdateError('업데이트 파일 해시가 없습니다.')
        size = entry.get('size')
        if type(size) is not int or not 0 <= size <= MAX_EXPANDED:
            raise UpdateError('잘못된 업데이트 파일 크기입니다.')
        total += size
    if total > MAX_EXPANDED:
        raise UpdateError('업데이트 용량 제한을 초과했습니다.')
    return data


def write_json(path, data):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def make_manifest(bundle, release_version):
    data = {'app': APP_ID, 'schema': 1, 'version': release_version, 'files': {}}
    for path in sorted(bundle.rglob('*')):
        if path.is_file() and path.name != MANIFEST:
            name = path.relative_to(bundle).as_posix()
            data['files'][name] = {'size': path.stat().st_size, 'sha256': digest(path)}
    validate_manifest(data)
    write_json(bundle / MANIFEST, data)
    return data


def installation(folder):
    folder = Path(folder).resolve()
    if folder == Path(folder.anchor) or not (folder / EXE).is_file() or not (folder / '_internal').is_dir():
        raise UpdateError('PromptCADStudio.exe와 _internal이 들어 있는 기존 앱 폴더를 선택하세요.')
    for path in (folder / EXE, folder / '_internal', folder / MANIFEST):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise UpdateError('링크로 연결된 앱 폴더는 업데이트할 수 없습니다.')
    return folder


def require_closed(folder):
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(folder / EXE), 0x40000000, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise UpdateError('현재 폴더의 CAD 앱을 저장 후 종료하세요. 폴더에 쓰기 권한도 필요합니다.')
    kernel.CloseHandle(handle)


def installed_version(folder):
    path = Path(folder) / MANIFEST
    return validate_manifest(json.loads(path.read_text(encoding='utf-8')))['version'] if path.is_file() else None


def latest_release():
    request = urllib.request.Request(API, headers={'User-Agent': 'PromptCADStudio-Updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read(2 * 1024**2))
    tag = data['tag_name']
    version(tag)
    if data.get('draft') or data.get('prerelease'):
        raise UpdateError('정식 릴리스가 아닙니다.')
    name = f'PromptCADStudio-Windows-x64-{tag}.zip'
    asset = next((a for a in data['assets'] if a['name'] == name and a.get('state') == 'uploaded'), None)
    if not asset or not str(asset.get('browser_download_url', '')).startswith(DOWNLOAD + tag + '/'):
        raise UpdateError('최신 Windows 배포 파일이 아직 준비되지 않았습니다. 잠시 후 다시 확인하세요.')
    sha = str(asset.get('digest', ''))
    if not re.fullmatch('sha256:[0-9a-f]{64}', sha) or not 0 < asset['size'] <= MAX_ARCHIVE:
        raise UpdateError('배포 파일의 검증 정보가 없습니다.')
    return {'version': tag.removeprefix('v'), 'url': asset['browser_download_url'],
            'sha256': sha[7:], 'size': asset['size']}


def download(release, destination, progress=lambda text, percent: None):
    sha = hashlib.sha256()
    received = 0
    request = urllib.request.Request(release['url'], headers={'User-Agent': 'PromptCADStudio-Updater'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open('wb') as stream:
            if not response.url.startswith('https://'):
                raise UpdateError('암호화되지 않은 다운로드 주소입니다.')
            while chunk := response.read(1024**2):
                received += len(chunk)
                if received > release['size']:
                    raise UpdateError('다운로드 크기가 배포 정보와 다릅니다.')
                stream.write(chunk)
                sha.update(chunk)
                progress(f'다운로드 {received / 1024**2:.1f} / {release["size"] / 1024**2:.1f} MB', int(received * 55 / release['size']))
        if received != release['size'] or sha.hexdigest() != release['sha256']:
            raise UpdateError('다운로드 검증에 실패했습니다. 기존 앱은 변경하지 않았습니다.')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


@contextmanager
def install_lock(folder):
    path = folder / '.cad-update.lock'
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise UpdateError('업데이트 잠금 파일 경로가 잘못되었습니다.')
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise UpdateError('이 설치 폴더의 업데이트가 이미 실행 중입니다.') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def transaction_dir(folder):
    work = folder / '.cad-update'
    if work.exists():
        if work.is_symlink() or (hasattr(work, 'is_junction') and work.is_junction()):
            raise UpdateError('업데이트 작업 폴더가 링크입니다.')
        marker = work / 'owner.json'
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')) != {'app': APP_ID, 'install': str(folder)}:
            raise UpdateError('업데이트 임시 폴더를 확인할 수 없습니다.')
    else:
        work.mkdir()
        write_json(work / 'owner.json', {'app': APP_ID, 'install': str(folder)})
    return work


def clean_transaction(folder, work):
    # Recheck the absolute boundary immediately before recursive deletion.
    if work.resolve() != folder.resolve() / '.cad-update' or work.is_symlink():
        raise UpdateError('업데이트 정리 경로를 확인할 수 없습니다.')
    transaction_dir(folder)  # Verify our ownership marker again.
    # Do not let a junction inserted into the temporary tree cross the boundary.
    for path in work.rglob('*'):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise UpdateError('임시 폴더 안에 링크가 있어 정리를 중단했습니다.')
    shutil.rmtree(work)


def recover(folder, work):
    journal = work / 'transaction.json'
    if not journal.exists():
        return
    plan = json.loads(journal.read_text(encoding='utf-8'))
    if plan['state'] == 'committed':
        return
    for entry in reversed(plan['operations']):
        name = entry['name']
        # The manifest is an internal operation, never an arbitrary input path.
        dest = folder / MANIFEST if name == MANIFEST else contained(folder, name)
        backup = work / 'backup' / name
        if backup.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, dest)
        elif not entry['existed'] and dest.is_file():
            # Only erase the exact new file installed by this transaction.
            if digest(dest) != entry['new_hash']:
                raise UpdateError(f'복구 중 변경된 파일을 발견했습니다: {name}. 백업을 보존합니다.')
            dest.unlink()
    journal.unlink()


def prepare_archive(folder, archive, expected_sha, work, progress):
    if not re.fullmatch('[0-9a-f]{64}', expected_sha) or digest(archive) != expected_sha:
        raise UpdateError('업데이트 ZIP의 SHA256이 일치하지 않습니다.')
    with ZipFile(archive) as zipfile:
        infos = zipfile.infolist()
        if len(infos) > 21000 or any(stat.S_ISLNK(i.external_attr >> 16) for i in infos):
            raise UpdateError('지원하지 않는 업데이트 압축 파일입니다.')
        prefix = 'PromptCADStudio/'
        manifest_info = zipfile.getinfo(prefix + MANIFEST)
        if manifest_info.file_size > 8 * 1024**2:
            raise UpdateError('업데이트 파일 목록이 너무 큽니다.')
        manifest = validate_manifest(json.loads(zipfile.read(manifest_info)))
        previous_path = folder / MANIFEST
        previous = validate_manifest(json.loads(previous_path.read_text(encoding='utf-8'))) if previous_path.is_file() else None
        if previous and version(manifest['version']) < version(previous['version']):
            raise UpdateError('이전 버전으로 덮어쓰지 않습니다.')
        if previous:
            previous_case = {name.casefold(): name for name in previous['files']}
            if any(name.casefold() in previous_case and previous_case[name.casefold()] != name for name in manifest['files']):
                raise UpdateError('파일 경로의 대소문자만 변경하는 업데이트는 지원하지 않습니다.')
        expected = {prefix + name for name in manifest['files']} | {prefix + MANIFEST}
        names = [i.filename for i in infos if not i.is_dir()]
        if len(names) != len(set(n.casefold() for n in names)) or set(names) != expected:
            raise UpdateError('ZIP 파일 목록과 설치 정보가 다릅니다.')
        changed = []
        preserved = []
        for name, entry in manifest['files'].items():
            dest = contained(folder, name)
            if dest.exists() and not dest.is_file():
                raise UpdateError(f'기존 폴더와 업데이트 파일이 겹칩니다: {name}')
            info = zipfile.getinfo(prefix + name)
            if info.file_size != entry['size']:
                raise UpdateError('압축 파일의 크기 정보가 다릅니다.')
            if not dest.is_file() or dest.stat().st_size != entry['size'] or digest(dest) != entry['sha256']:
                if name.startswith(('examples/', 'docs/')) and dest.is_file():
                    if not previous or name not in previous['files'] or digest(dest) != previous['files'][name]['sha256']:
                        preserved.append(name)
                        continue
                # Files unknown to an existing manifest belong to the user.
                if previous and name not in previous['files'] and dest.exists():
                    raise UpdateError(f'사용자 파일과 업데이트 경로가 겹칩니다: {name}')
                changed.append(name)
        needed = sum(manifest['files'][name]['size'] for name in changed)
        if shutil.disk_usage(folder).free < needed + 64 * 1024**2:
            raise UpdateError('업데이트 임시 공간이 부족합니다. 기존 앱은 변경하지 않았습니다.')
        stage = work / 'stage'
        stage.mkdir(exist_ok=True)
        for index, name in enumerate(changed):
            path = contained(stage, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.open(prefix + name) as source, path.open('wb') as dest:
                shutil.copyfileobj(source, dest, 1024**2)
            if digest(path) != manifest['files'][name]['sha256']:
                raise UpdateError(f'파일 검증에 실패했습니다: {name}')
            progress('변경된 파일 검증 중…', 55 + int(25 * (index + 1) / max(1, len(changed))))
        removed = []
        if previous:
            for name, entry in previous['files'].items():
                if name not in manifest['files']:
                    dest = contained(folder, name)
                    # Preserve locally modified documents even when once bundled.
                    if dest.is_file() and digest(dest) == entry['sha256']:
                        removed.append(name)
        write_json(stage / MANIFEST, manifest)
        return manifest, changed, removed, preserved


def apply_archive(folder, archive, expected_sha, progress=lambda text, percent: None, *, release=None):
    folder = installation(folder)
    with install_lock(folder):
        require_closed(folder)
        work = transaction_dir(folder)
        try:
            recover(folder, work)
            # Remove leftovers from an interrupted download/previous commit.
            clean_transaction(folder, work)
            work = transaction_dir(folder)
            require_closed(folder)
            if release:
                if shutil.disk_usage(folder).free < release['size'] + 64 * 1024**2:
                    raise UpdateError('다운로드 임시 공간이 부족합니다.')
                archive = work / 'download.zip'
                expected_sha = release['sha256']
                download(release, archive, progress)
            manifest, changed, removed, preserved = prepare_archive(folder, Path(archive), expected_sha, work, progress)
            if release:
                archive.unlink()
            require_closed(folder)
            operations = []
            for name in changed + removed + [MANIFEST]:
                dest = folder / MANIFEST if name == MANIFEST else contained(folder, name)
                new_hash = digest(work / 'stage' / MANIFEST) if name == MANIFEST else manifest['files'].get(name, {}).get('sha256')
                operations.append({'name': name, 'existed': dest.exists(), 'new_hash': new_hash})
            plan = {'state': 'applying', 'operations': operations}
            write_json(work / 'transaction.json', plan)
            for index, entry in enumerate(operations):
                name = entry['name']
                dest = folder / MANIFEST if name == MANIFEST else contained(folder, name)
                backup = work / 'backup' / name
                staged = work / 'stage' / name
                if dest.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(dest, backup)
                if staged.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, dest)
                progress('기존 설치 파일 교체 중…', 80 + int(19 * (index + 1) / len(operations)))
            plan['state'] = 'committed'
            write_json(work / 'transaction.json', plan)
        except BaseException:
            recover(folder, work)
            clean_transaction(folder, work)
            raise
        clean_transaction(folder, work)
        progress('업데이트 완료 · 임시 파일과 이전 프로그램 파일 정리 완료', 100)
        return {'version': manifest['version'], 'changed': len(changed), 'removed': len(removed), 'preserved_documents': preserved}
