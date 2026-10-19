"""One per-user installation, with verified payloads and no forced app exit.

The filesystem installer accepts an explicit destination and a closed callback
for isolated tests. Production CLI always chooses the canonical Windows path.
No OS query, registry edit, shortcut or process launch occurs on import.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from uuid import uuid4
from zipfile import ZIP_STORED,ZipFile

from . import updater as U

# Every installer/updater path uses the same manifest ownership policy.
reject_profile_ownership = U.reject_profile_ownership


def canonical_install_dir():
    local=os.environ.get('LOCALAPPDATA')
    if not local:raise U.UpdateError('LOCALAPPDATA가 없어 사용자 설치 위치를 확인할 수 없습니다.')
    return Path(os.path.abspath(local))/'Programs'/'PromptCADStudio'


def no_reparse(path):
    path=Path(os.path.abspath(path))
    for item in (path,*path.parents):
        try:info=item.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise U.UpdateError('설치 경로의 심볼릭 링크·정션·재분석 지점은 사용할 수 없습니다.')
    return path


def require_canonical_directory(folder):
    path=no_reparse(folder);expected=no_reparse(canonical_install_dir())
    if os.path.normcase(str(path))!=os.path.normcase(str(expected)):
        raise U.UpdateError('기본 앱은 사용자 Programs/PromptCADStudio 한 곳에서만 설치·등록합니다. Install.ps1을 실행하세요.')
    return path


def require_canonical_executable(executable):
    path=no_reparse(executable);folder=require_canonical_directory(path.parent)
    if path.name!=U.EXE or not path.is_file():raise U.UpdateError('정식 설치 실행 파일을 찾을 수 없습니다.')
    manifest=U.validate_manifest(json.loads((folder/U.MANIFEST).read_text(encoding='utf-8')))
    entry=manifest['files'][U.EXE]
    if path.stat().st_size!=entry['size'] or U.digest(path)!=entry['sha256']:
        raise U.UpdateError('설치 실행 파일이 검증된 설치 정보와 다릅니다.')
    return path


def verify_payload(folder,*,preserved_documents=()):
    folder=no_reparse(folder)
    no_reparse(folder/'_internal')
    if not folder.is_dir() or not (folder/'_internal').is_dir():raise U.UpdateError('전체 Windows 배포 폴더를 선택하세요.')
    no_reparse(folder/U.MANIFEST)
    manifest=U.validate_manifest(json.loads((folder/U.MANIFEST).read_text(encoding='utf-8')))
    reject_profile_ownership(manifest)
    preserved=set(preserved_documents)
    for name in preserved:
        U.relative_path(name)
        if not name.startswith(('docs/','examples/')):
            raise U.UpdateError('보존 문서 범위가 잘못되었습니다.')
        if not no_reparse(U.contained(folder,name)).is_file():
            raise U.UpdateError('보존할 사용자 문서가 없습니다: '+name)
    for name,entry in manifest['files'].items():
        path=U.contained(folder,name);no_reparse(path)
        if not path.is_file():raise U.UpdateError('배포 파일이 없습니다: '+name)
        if name not in preserved and (path.stat().st_size!=entry['size'] or U.digest(path)!=entry['sha256']):
            raise U.UpdateError('배포 파일 검증에 실패했습니다: '+name)
    return manifest


@contextmanager
def owned_work(parent,destination):
    parent=no_reparse(parent);parent.mkdir(parents=True,exist_ok=True);no_reparse(parent)
    work=Path(tempfile.mkdtemp(prefix='.PromptCADStudio-install-',dir=parent))
    owner={'app':U.APP_ID,'destination':str(destination),'nonce':uuid4().hex}
    (work/'owner.json').write_text(json.dumps(owner),encoding='utf-8')
    try:yield work
    finally:
        # A private, newly created staging directory only. Any changed owner or
        # link fails closed; no user folder or old release is searched/deleted.
        no_reparse(work)
        if work.parent!=parent or not work.name.startswith('.PromptCADStudio-install-'):
            raise U.UpdateError('임시 설치 경계가 변경되어 보존했습니다.')
        if json.loads((work/'owner.json').read_text(encoding='utf-8'))!=owner:
            raise U.UpdateError('임시 설치 소유 정보가 변경되어 보존했습니다.')
        for directory,dirs,files in os.walk(work,followlinks=False):
            no_reparse(directory)
            for name in (*dirs,*files):no_reparse(Path(directory)/name)
        shutil.rmtree(work)


def install_canonical(source,destination=None,*,closed_callback,progress=lambda text,percent:None):
    """Verify and install only owned release files; the callback must fail closed.

    Existing installs reuse the updater's journal/rollback/obsolete-file cleanup.
    Explicit destinations are for pure fixtures; the production entry does not
    expose an alternate install folder. Unknown nonempty destinations are held.
    """
    if not callable(closed_callback):raise U.UpdateError('실행 중인 CAD 확인 절차가 필요합니다.')
    source=no_reparse(source);destination=no_reparse(destination or canonical_install_dir())
    manifest=verify_payload(source);checks=[]
    def closed():
        outcome=closed_callback()
        if outcome is False:raise U.UpdateError('CAD 앱을 저장 후 모두 종료하세요.')
        checks.append(outcome)
    if source==destination:
        closed()
        return dict(success=True,install_dir=str(destination),version=manifest['version'],mode='already_canonical',
            changed=0,removed=0,preserved_documents=[],closed_checks=len(checks),verified_payload=True)
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise U.UpdateError('배포 원본과 설치 위치가 서로 포함될 수 없습니다.')
    if destination.exists() and not destination.is_dir():raise U.UpdateError('설치 위치가 파일과 겹칩니다.')
    previous=None
    if destination.is_dir() and any(destination.iterdir()):
        previous_path=destination/U.MANIFEST;no_reparse(previous_path)
        if not previous_path.is_file():raise U.UpdateError('기존의 알 수 없는 비어 있지 않은 폴더를 덮어쓰지 않습니다.')
        previous=U.validate_manifest(json.loads(previous_path.read_text(encoding='utf-8')))
        reject_profile_ownership(previous)
        U.installation(destination)
        if U.version(manifest['version'])<U.version(previous['version']):raise U.UpdateError('이전 버전으로 덮어쓰지 않습니다.')
    closed();destination.parent.mkdir(parents=True,exist_ok=True);no_reparse(destination.parent)
    required=sum(entry['size'] for entry in manifest['files'].values())*(2 if previous else 1)+64*1024**2
    if shutil.disk_usage(destination.parent).free<required:raise U.UpdateError('검증·교체용 임시 공간이 부족합니다.')
    with owned_work(destination.parent,destination) as work:
        if previous:
            archive=work/'release.zip'
            with ZipFile(archive,'x',compression=ZIP_STORED) as output:
                for name in manifest['files']:output.write(U.contained(source,name),'PromptCADStudio/'+name)
                output.write(source/U.MANIFEST,'PromptCADStudio/'+U.MANIFEST)
            closed()
            result=U.apply_archive(destination,archive,U.digest(archive),progress,closed_callback=closed)
            verify_payload(destination,preserved_documents=result['preserved_documents'])
            mode='updated'
        else:
            stage=work/'stage';stage.mkdir()
            for name in manifest['files']:
                target=U.contained(stage,name);target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(U.contained(source,name),target)
            shutil.copyfile(source/U.MANIFEST,stage/U.MANIFEST);verify_payload(stage)
            closed();no_reparse(destination)
            had_empty=destination.exists()
            if had_empty:
                if any(destination.iterdir()):raise U.UpdateError('설치 중 새 사용자 파일이 생겨 교체를 보류했습니다.')
                destination.rmdir()
            try:os.replace(stage,destination)
            except BaseException:
                if had_empty and not destination.exists():destination.mkdir()
                raise
            result=dict(version=manifest['version'],changed=len(manifest['files']),removed=0,preserved_documents=[])
            mode='installed'
        result.update(success=True,install_dir=str(destination),mode=mode,closed_checks=len(checks),verified_payload=True)
        return result


def validate_process_snapshot(rows,*,installer_pid,executable,window_pids):
    """Pure classification: only this headless installer and proven parent exempt.

    A parent qualifies only with the identical validated EXE and command line,
    an explicit installer flag, and no top-level window. No subtree exclusions.
    """
    if not isinstance(rows,list):raise U.UpdateError('전체 CAD 프로세스 조회가 불완전합니다.')
    current=next((r for r in rows if r.get('ProcessId')==installer_pid),None)
    same=lambda value: isinstance(value,str) and os.path.normcase(os.path.abspath(value))==os.path.normcase(os.path.abspath(executable))
    if not current or not same(current.get('ExecutablePath')) or not isinstance(current.get('CommandLine'),str):
        raise U.UpdateError('현재 설치 프로세스의 경로·인자를 확인할 수 없습니다.')
    if not re.search(r'(?:^|\s)--install-canonical(?:\s|=)',current['CommandLine']) or installer_pid in window_pids:
        raise U.UpdateError('창이 없는 명시적 설치 프로세스만 제외할 수 있습니다.')
    excluded={installer_pid};parent=next((r for r in rows if r.get('ProcessId')==current.get('ParentProcessId')),None)
    if parent and same(parent.get('ExecutablePath')) and parent.get('CommandLine')==current['CommandLine'] and parent['ProcessId'] not in window_pids:
        excluded.add(parent['ProcessId'])
    blocked=[]
    for row in rows:
        name=str(row.get('Name','')).casefold();command=str(row.get('CommandLine') or '')
        if name in ('python.exe','pythonw.exe') and not isinstance(row.get('CommandLine'),str):
            raise U.UpdateError('Python CAD 실행 여부를 확인할 수 없는 프로세스가 있어 설치를 보류합니다.')
        cad=name=='promptcadstudio.exe' or name.startswith(('promptcadstudio-','promptcadstudio_','promptcadstudio ')) and name.endswith('.exe')
        source=name in ('python.exe','pythonw.exe') and re.search(r'(?i)native_desktop[.]py(?:["\s]|$)',command)
        if (cad or source) and row.get('ProcessId') not in excluded:blocked.append(row.get('ProcessId'))
    if blocked:raise U.UpdateError('CAD 앱을 저장 후 모두 종료하세요. 실행 중 PID: '+', '.join(map(str,blocked)))
    return dict(all_CAD_closed=True,excluded_headless_pids=sorted(excluded),observed_rows=len(rows))


def windows_closed_guard(executable):
    """Return a fresh, fail-closed global check. Definition/import queries no OS."""
    executable=str(no_reparse(executable));pid=os.getpid()
    def closed():
        if os.name!='nt':raise U.UpdateError('실제 설치는 Windows에서만 지원합니다.')
        script=r'''
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding $false
$OutputEncoding=[Console]::OutputEncoding
$cadPid=[int]$env:CADSTUDIO_INSTALL_PID
$cadAll=@(Get-CimInstance Win32_Process -ErrorAction Stop)
$cadSelf=@($cadAll | Where-Object {$_.ProcessId -eq $cadPid})
if($cadSelf.Count -ne 1){throw 'Installer process identity unavailable'}
$cadParent=$cadSelf[0].ParentProcessId
$cadRows=@($cadAll | Where-Object {
  $_.ProcessId -eq $cadPid -or $_.ProcessId -eq $cadParent -or
  $_.Name -match '^PromptCADStudio(?:[-_ ].*)?[.]exe$' -or
  ($_.Name -match '^pythonw?[.]exe$' -and ($null -eq $_.CommandLine -or $_.CommandLine -match 'native_desktop[.]py(?:["\s]|$)'))
} | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine)
ConvertTo-Json -InputObject $cadRows -Compress -Depth 4
'''
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
            env=dict(os.environ,CADSTUDIO_INSTALL_PID=str(pid)),capture_output=True,encoding='utf-8',timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode!=0:raise U.UpdateError('전체 CAD 실행 상태를 확인하지 못했습니다. 설치 파일은 교체하지 않습니다.')
        try:rows=json.loads(result.stdout.lstrip('\ufeff'))
        except ValueError:raise U.UpdateError('전체 CAD 실행 상태 결과가 불완전합니다.') from None
        import ctypes
        from ctypes import wintypes
        windows=set();user=ctypes.WinDLL('user32',use_last_error=True)
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user.EnumWindows.argtypes=[callback,wintypes.LPARAM];user.EnumWindows.restype=wintypes.BOOL
        @callback
        def found(handle,_):
            owner=wintypes.DWORD();user.GetWindowThreadProcessId(handle,ctypes.byref(owner));windows.add(owner.value);return True
        if not user.EnumWindows(found,0):raise U.UpdateError('설치 프로세스의 창 상태를 확인하지 못했습니다.')
        return validate_process_snapshot(rows,installer_pid=pid,executable=executable,window_pids=windows)
    return closed


def run_install_cli(executable,report):
    """Production-only dispatch; no Qt/UI/automatic application restart."""
    report=Path(report)
    if report.exists():raise FileExistsError(report)
    result={}
    try:
        if not getattr(sys,'frozen',False):raise U.UpdateError('전체 Windows 배포 EXE에서 Install.ps1을 실행하세요.')
        target=canonical_install_dir()
        result=install_canonical(Path(executable).parent,target,closed_callback=windows_closed_guard(executable))
        canonical=require_canonical_executable(target/U.EXE)
        from .file_associations import refresh_owned_pcad_routes
        try:
            registration=refresh_owned_pcad_routes(canonical)
            result['registration']=registration;result['registration_succeeded']=True
            result['pcad_routes_current']=registration['pcad_routes_current']
            if registration.get('file_association_warning'):result['file_association_warning']=registration['file_association_warning']
        except (OSError,ValueError,RuntimeError) as exc:
            result['registration_succeeded']=False;result['pcad_routes_current']=False;result['file_association_warning']=str(exc)
        result['payload_installed']=True
        result['installation_complete']=result['registration_succeeded'] and result['pcad_routes_current']
    except (OSError,ValueError,RuntimeError) as exc:result=dict(success=False,error=str(exc))
    with report.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    return (0 if result.get('installation_complete') else 3) if result.get('success') else 2
