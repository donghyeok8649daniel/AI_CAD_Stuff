"""Small standalone Windows updater. No CAD runtime needed to upgrade v2.1."""
import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from cadstudio.updater import (APP_ID, EXE, UpdateError, apply_archive,
                               installation, installed_version, latest_release, version)


def hidden_process(args, **kwargs):
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(args, **kwargs)


def detect_install():
    """Prefer this bundle, then the user's actual Desktop shortcut."""
    candidates = [Path(sys.executable).parent] if getattr(sys, 'frozen', False) else []
    if os.name == 'nt':
        command = "$p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Prompt CAD Studio.lnk'; if(Test-Path -LiteralPath $p){(New-Object -ComObject WScript.Shell).CreateShortcut($p).TargetPath}"
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.stdout.strip():
                candidates.append(Path(result.stdout.strip()).parent)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for folder in candidates:
        try:
            return installation(folder)
        except UpdateError:
            pass
    return None


def wait_for_app(pid):
    if not pid or os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 60000) != 0:
                raise UpdateError('CAD 앱이 아직 종료되지 않았습니다. 저장 후 종료하고 다시 실행하세요.')
        finally:
            kernel.CloseHandle(handle)


def relocate_if_needed(args):
    """Run a temporary copy so the installed updater EXE can also be replaced."""
    if not getattr(sys, 'frozen', False) or args.cleanup_root:
        return False
    executable = Path(sys.executable).resolve()
    if not executable.is_relative_to(Path(args.install_dir).resolve()):
        return False
    folder = Path(tempfile.mkdtemp(prefix='PromptCADStudio-updater-')).resolve()
    (folder / 'owner.json').write_text(json.dumps({'app': APP_ID}), encoding='utf-8')
    copied = folder / 'PromptCADStudioUpdater.exe'
    shutil.copy2(executable, copied)
    # Explicit install path survives relocation and shortcut changes.
    command = [str(copied), *sys.argv[1:], '--install-dir', str(args.install_dir), '--cleanup-root', str(folder), '--wait-updater-pid', str(os.getppid())]
    hidden_process(command, cwd=str(folder))
    return True


def cleanup_temporary_executable(folder):
    if not folder or os.name != 'nt':
        return
    root = Path(folder).resolve()
    if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith('PromptCADStudio-updater-'):
        raise UpdateError('업데이트 실행 파일의 임시 경로가 잘못되었습니다.')
    if Path(sys.executable).resolve().parent != root or json.loads((root / 'owner.json').read_text()) != {'app': APP_ID}:
        raise UpdateError('임시 실행 파일의 소유 정보를 확인할 수 없습니다.')
    # Single PowerShell process verifies the same absolute boundary, waits for
    # both the Python child and one-file bootloader, then removes only this copy.
    script = r"""
$cadCleanup=[IO.Path]::GetFullPath($env:CADSTUDIO_CLEANUP_ROOT)
$cadTemp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
if((Split-Path -Parent $cadCleanup).TrimEnd('\') -ne $cadTemp -or (Split-Path -Leaf $cadCleanup) -notlike 'PromptCADStudio-updater-*'){exit 2}
if((Get-Item -LiteralPath $cadCleanup).Attributes -band [IO.FileAttributes]::ReparsePoint){exit 3}
Wait-Process -Id ([int]$env:CADSTUDIO_CLEANUP_PID) -ErrorAction SilentlyContinue
for($cadAttempt=0;$cadAttempt -lt 120;$cadAttempt++){
  try {Remove-Item -LiteralPath $cadCleanup -Recurse -Force -ErrorAction Stop;exit 0} catch {Start-Sleep -Seconds 1}
}
"""
    env = dict(os.environ, CADSTUDIO_CLEANUP_ROOT=str(root), CADSTUDIO_CLEANUP_PID=str(os.getpid()))
    hidden_process(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], env=env, cwd=tempfile.gettempdir())


def restart(folder):
    # PyInstaller modifies the DLL search path; clear it for the updated process.
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    hidden_process([str(Path(folder) / EXE)], cwd=str(folder), env=env)


def show_window(args):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('Prompt CAD Studio · 업데이트')
    root.geometry('630x350')
    root.minsize(580, 350)
    root.configure(bg='#17212c')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('TFrame', background='#17212c')
    style.configure('TLabel', background='#17212c', foreground='#ecf2f6', font=('Malgun Gothic', 10))
    style.configure('TButton', font=('Malgun Gothic', 10), padding=8)
    style.configure('TProgressbar', background='#68cfb9', troughcolor='#273544')
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='PROMPT / CAD', font=('Malgun Gothic', 18, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='기존 앱을 업데이트합니다. 설치 폴더는 그대로 유지합니다.').pack(anchor='w', pady=(8, 18))
    folder_value = tk.StringVar(value=str(args.install_dir or ''))
    row = ttk.Frame(frame)
    row.pack(fill='x')
    entry = ttk.Entry(row, textvariable=folder_value)
    entry.pack(side='left', fill='x', expand=True)
    status = tk.StringVar(value='최신 버전 확인 중…')
    ttk.Label(frame, textvariable=status, wraplength=555).pack(anchor='w', pady=(18, 10))
    progress = ttk.Progressbar(frame, maximum=100)
    progress.pack(fill='x')
    ttk.Label(frame, text='프로젝트 파일은 보존합니다. 완료 후 다운로드·교체용 백업을 정리합니다.', wraplength=555).pack(anchor='w', pady=(12, 14))
    messages = queue.Queue()
    state = {'running': False, 'release': None}

    def choose():
        value = filedialog.askdirectory(title='PromptCADStudio.exe가 들어 있는 기존 폴더', initialdir=folder_value.get() or None)
        if value:
            folder_value.set(value)
            refresh()

    browse = ttk.Button(row, text='폴더 선택', command=choose)
    browse.pack(side='right', padx=(8, 0))

    def refresh():
        release = state['release']
        if not release:
            return
        try:
            folder = installation(folder_value.get())
            current = installed_version(folder)
            if current and version(current) >= version(release['version']):
                status.set(f'이미 최신 버전입니다. v{current} · 추가 다운로드 없음')
                action.configure(state='disabled')
                return
            status.set(f'새 버전 v{release["version"]} · 다운로드 {release["size"] / 1024**2:.0f} MB\n작업을 저장하고 이 폴더의 CAD 앱을 종료한 뒤 업데이트하세요.')
            action.configure(state='normal')
        except (ValueError, OSError, UpdateError) as exc:
            status.set(str(exc))
            action.configure(state='disabled')

    def start():
        try:
            folder = installation(folder_value.get())
        except Exception as exc:
            messagebox.showerror('설치 폴더 확인', str(exc), parent=root)
            return
        state['running'] = True
        action.configure(state='disabled')
        browse.configure(state='disabled')
        entry.configure(state='disabled')
        release = state['release']

        def work():
            try:
                wait_for_app(args.wait_pid)
                result = apply_archive(folder, None, None, lambda text, value: messages.put(('progress', text, value)), release=release)
                messages.put(('done', folder, result))
            except Exception as exc:
                messages.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    action = ttk.Button(frame, text='기존 앱 업데이트', command=start, state='disabled')
    action.pack(anchor='e')
    entry.bind('<FocusOut>', lambda _: refresh())

    def check():
        try:
            messages.put(('release', latest_release()))
        except Exception as exc:
            messages.put(('error', '업데이트 확인에 실패했습니다. 인터넷 연결 후 다시 실행하세요.\n' + str(exc)))

    def poll():
        try:
            while True:
                message = messages.get_nowait()
                if message[0] == 'release':
                    state['release'] = message[1]
                    refresh()
                    if args.auto_update and str(action['state']) == 'normal':
                        start()
                elif message[0] == 'progress':
                    status.set(message[1])
                    progress['value'] = message[2]
                elif message[0] == 'error':
                    state['running'] = False
                    status.set(message[1])
                    browse.configure(state='normal')
                    entry.configure(state='normal')
                    action.configure(state='normal' if state['release'] else 'disabled')
                elif message[0] == 'done':
                    state['running'] = False
                    progress['value'] = 100
                    status.set(f'v{message[2]["version"]} 업데이트 완료. 이전 파일과 임시 다운로드를 정리했습니다.')
                    action.configure(text='CAD 실행', state='normal', command=lambda: (restart(message[1]), root.destroy()))
                    if args.restart:
                        restart(message[1])
                        root.destroy()
                        return
        except queue.Empty:
            pass
        root.after(100, poll)

    def close():
        if state['running']:
            messagebox.showinfo('업데이트 중', '파일 검증과 교체를 마친 후 닫을 수 있습니다.', parent=root)
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    threading.Thread(target=check, daemon=True).start()
    root.after(100, poll)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install-dir', type=Path)
    parser.add_argument('--wait-pid', type=int)
    parser.add_argument('--wait-updater-pid', type=int)
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--auto-update', action='store_true')
    parser.add_argument('--cleanup-root', type=Path)
    parser.add_argument('--apply-archive', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not args.install_dir:
        args.install_dir = detect_install()
    if args.install_dir and relocate_if_needed(args):
        return 0
    try:
        wait_for_app(args.wait_updater_pid)
        if args.apply_archive:
            wait_for_app(args.wait_pid)
            result = apply_archive(args.install_dir, args.apply_archive, args.sha256)
            if args.report:
                args.report.write_text(json.dumps(result), encoding='utf-8')
            if args.restart:
                restart(args.install_dir)
        else:
            show_window(args)
    finally:
        cleanup_temporary_executable(args.cleanup_root)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        if '--apply-archive' not in sys.argv and os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'Prompt CAD Studio 업데이트', 0x10)
        raise
