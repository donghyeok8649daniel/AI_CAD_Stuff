"""Explicit, bounded firmware syntax checks; never execute, link or flash.

Python is parsed/compiled in memory without execution. An explicitly selected
installed GNU/Clang compiler may parse C/C++ in a disposable directory using
fixed arguments. Project hooks, response files and arbitrary compiler flags are
never accepted. Neither check proves target SDK integration or hardware safety.
"""
from __future__ import annotations

import ast
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .firmware_bundle import (FirmwareBundle, verify_bundle_binding, validate_relative_path,
    bundle_source_files, library_search_paths)

MAX_DIAGNOSTIC_BYTES = 32 * 1024
_COMPILERS = {'gcc', 'g++', 'clang', 'clang++', 'arm-none-eabi-gcc', 'arm-none-eabi-g++'}
_STANDARD_HEADERS = {'assert.h', 'ctype.h', 'errno.h', 'float.h', 'inttypes.h', 'limits.h',
    'math.h', 'stddef.h', 'stdint.h', 'stdio.h', 'stdlib.h', 'string.h', 'stdbool.h',
    'stdarg.h', 'stdbool.h', 'time.h', 'stdint', 'cstdint', 'cstddef', 'cstring', 'cmath',
    'array', 'algorithm', 'utility', 'limits', 'type_traits', 'atomic'}


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class FirmwareBuildDiagnostic(_Model):
    severity: Literal['error', 'warning', 'pending', 'info']
    code: str
    message: str
    path: str = ''
    line: int | None = None
    column: int | None = None


class FirmwareBuildCheck(_Model):
    name: str
    status: Literal['passed', 'pending', 'failed']
    message: str


class FirmwareBuildReport(_Model):
    status: Literal['syntax_ok', 'pending', 'failed', 'cancelled']
    bundle_id: str
    source_sha256: dict[str, str]
    checks: list[FirmwareBuildCheck] = Field(default_factory=list)
    diagnostics: list[FirmwareBuildDiagnostic] = Field(default_factory=list)
    full_target_build: Literal[False] = False
    executed_generated_code: Literal[False] = False
    flashed_hardware: Literal[False] = False
    elapsed_s: float = 0
    compiler_path: str = ''
    scope: str = 'Source syntax only. No execution, linking, target SDK integration, firmware emulation or hardware validation.'


def _compiler(path):
    if path is None or str(path) == '':
        return None
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file() or candidate.is_symlink():
        raise ValueError('Select the absolute path of an existing installed compiler executable.')
    name = candidate.name.casefold()
    if os.name == 'nt':
        if candidate.suffix.casefold() != '.exe':
            raise ValueError('Compiler scripts and command wrappers are not accepted.')
        name = name[:-4]
    if name not in _COMPILERS:
        raise ValueError('Only an explicitly selected GNU/Clang compiler is supported; no build scripts or response files are run.')
    return candidate.resolve(strict=True)


def _preflight_c(bundle):
    """Keep preprocessing within the bundle or ordinary compiler headers."""
    issues = []
    paths = {file.path for file in bundle_source_files(bundle)}
    search_paths = library_search_paths(bundle)
    for file in bundle_source_files(bundle):
        if file.role != 'source' or PurePosixPath(file.path).suffix.lower() == '.py':
            continue
        # Replace comments with spaces while retaining diagnostic line numbers.
        source = re.sub(r'/\*.*?\*/|//[^\n]*',
                        lambda match: '\n' * match.group().count('\n') + ' ', file.content, flags=re.S)
        source = source.replace('\\\r\n', '').replace('\\\n', '')
        source = source.replace('%:', '#')  # C's alternative preprocessor-token spelling.
        if '__has_include' in source or '__has_embed' in source or '_Pragma' in source or '??' in source:
            issues.append(FirmwareBuildDiagnostic(severity='error', code='unsafe_preprocessor',
                path=file.path, message='Computed filesystem probes, pragmas and trigraphs are not accepted in the safe compiler check.'))
        for line_number, line in enumerate(source.splitlines(), 1):
            directive = re.match(r'^\s*#\s*(\w+)\s*(.*?)\s*$', line)
            if not directive:
                continue
            command, argument = directive.groups()
            if command in ('embed', 'include_next', 'import', 'line') or (command == 'pragma' and argument != 'once'):
                issues.append(FirmwareBuildDiagnostic(severity='error', code='unsafe_preprocessor',
                    path=file.path, line=line_number, message='This preprocessor directive is not permitted by the safe syntax checker.'))
            if command != 'include':
                continue
            match = re.fullmatch(r'[<"]([^>"]+)[>"]', argument)
            if not match:
                issues.append(FirmwareBuildDiagnostic(severity='error', code='computed_include',
                    path=file.path, line=line_number, message='Include filenames must be explicit safe literals, not macros or compiler options.'))
                continue
            header = match.group(1)
            try:
                validate_relative_path(header)
            except ValueError:
                issues.append(FirmwareBuildDiagnostic(severity='error', code='unsafe_include_path',
                    path=file.path, line=line_number, message='A source include cannot read an absolute or traversing filesystem path.'))
                continue
            local = str(PurePosixPath(file.path).parent / header)
            if (header not in _STANDARD_HEADERS and header not in paths and local not in paths and
                    not any(str(PurePosixPath(root) / header) in paths for root in search_paths)):
                issues.append(FirmwareBuildDiagnostic(severity='pending', code='sdk_header_missing',
                    path=file.path, line=line_number, message=f'Required target SDK/core header is not bundled or configured: {header}. No SDK or driver interface is guessed.'))
    return issues


def _python_import_diagnostics(file, tree, bundle):
    """Static availability only: never find_spec/import a user package."""
    paths = {item.path for item in bundle_source_files(bundle) if item.path.endswith('.py')}
    roots = ['', str(PurePosixPath(bundle.entrypoint).parent), str(PurePosixPath(file.path).parent), *library_search_paths(bundle)]
    declared = {module for library in bundle.libraries for module in library.module_names}
    stdlib = getattr(sys, 'stdlib_module_names', set())
    issues = []
    for node in ast.walk(tree):
        names = ([item.name for item in node.names] if isinstance(node, ast.Import) else
                 [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
        for name in names:
            first = name.split('.')[0]
            module_path = name.replace('.', '/')
            available = any((str(PurePosixPath(root) / (module_path + '.py')) in paths or
                             str(PurePosixPath(root) / module_path / '__init__.py') in paths or
                             any(path.startswith(str(PurePosixPath(root) / module_path) + '/') for path in paths))
                            for root in roots)
            if first in stdlib or available:
                continue
            issues.append(FirmwareBuildDiagnostic(severity='pending', code='python_dependency_unverified',
                path=file.path, line=node.lineno, message=f'Import {name}: ' +
                ('an exact external dependency is recorded; installation and target compatibility are unverified.'
                 if any(name == module or name.startswith(module + '.') for module in declared)
                 else 'no bundled module or declared exact dependency was found. Configure its target package separately.')))
        if isinstance(node, ast.ImportFrom) and node.level and node.module:
            base = PurePosixPath(file.path).parent
            for _ in range(node.level - 1): base = base.parent
            module_path = str(base / node.module.replace('.', '/'))
            if not (module_path + '.py' in paths or module_path + '/__init__.py' in paths or
                    any(path.startswith(module_path + '/') for path in paths)):
                issues.append(FirmwareBuildDiagnostic(severity='pending', code='python_dependency_unverified',
                    path=file.path, line=node.lineno, message=f'Relative import {node.module}: no bundled module was found. Runtime package resolution is unverified.'))
    return issues


class _CompilerJob:
    """Contain only the owned compiler process tree, including its child cc1."""
    def __init__(self, pid):
        self.handle = None; self.pid = pid; self.closed = False
        if os.name != 'nt':
            return
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('ProcessUserTimeLimit', ctypes.c_int64), ('JobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount',
                'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', Io), ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        # KILL_ON_JOB_CLOSE | JOB_MEMORY | ACTIVE_PROCESS. No native code from
        # the generated bundle is loaded, and diagnostic buffers are bounded.
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x200 | 0x8
        info.BasicLimitInformation.ActiveProcessLimit = 8
        info.JobMemoryLimit = 512 * 1024 * 1024
        process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        try:
            if (not job or not process or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
                    or not kernel.AssignProcessToJobObject(job, process)):
                if job:
                    kernel.CloseHandle(job)
                raise ValueError('The compiler process tree could not be safely contained. No target build was completed.')
            self.handle = job; self.kernel = kernel
        finally:
            if process:
                kernel.CloseHandle(process)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.handle:
            self.kernel.CloseHandle(self.handle); self.handle = None
        elif os.name != 'nt':
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _resume_owned_process(pid):
    """Resume the suspended owned compiler only after job containment.

    Public Windows thread APIs avoid the race where gcc starts cc1 before its
    parent has entered the kill-on-close job. The freshly created suspended
    process cannot exit or create compiler children before this step.
    """
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ThreadID', w.DWORD),
            ('th32OwnerProcessID', w.DWORD), ('tpBasePri', w.LONG), ('tpDeltaPri', w.LONG), ('dwFlags', w.DWORD)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Thread32First.restype = w.BOOL
    kernel.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Thread32Next.restype = w.BOOL
    kernel.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenThread.restype = w.HANDLE
    kernel.ResumeThread.argtypes = [w.HANDLE]
    kernel.ResumeThread.restype = w.DWORD
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        raise ValueError('The owned compiler thread could not be enumerated safely.')
    entry = Entry(); entry.dwSize = ctypes.sizeof(entry)
    try:
        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == pid:
                thread = kernel.OpenThread(0x2, False, entry.th32ThreadID)  # THREAD_SUSPEND_RESUME
                if not thread:
                    raise ValueError('The owned compiler thread could not be resumed safely.')
                try:
                    if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ValueError('The contained compiler could not be resumed.')
                    return
                finally:
                    kernel.CloseHandle(thread)
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        raise ValueError('The suspended compiler thread was not found; no check was completed.')
    finally:
        kernel.CloseHandle(snapshot)


class _BoundedReader:
    def __init__(self, stream):
        self.stream = stream; self.data = bytearray(); self.truncated = False
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while True:
                chunk = self.stream.read(4096)
                if not chunk:
                    break
                remaining = MAX_DIAGNOSTIC_BYTES - len(self.data)
                self.data.extend(chunk[:max(remaining, 0)])
                self.truncated |= len(chunk) > remaining
        except (OSError, ValueError):
            pass


def _stop_owned_process(process, job):
    if job is not None:
        job.close()
    if os.name != 'nt':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _run_compiler(argv, directory, compiler, cancelled, timeout_s):
    # Source candidates cannot add flags, alter PATH, select plugins, supply
    # GCC specs, environment include paths or run project lifecycle hooks.
    env = {key: value for key, value in os.environ.items() if key.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC'}}
    env.update(PATH=str(compiler.parent) + os.pathsep + os.defpath,
               TEMP=str(directory), TMP=str(directory), LANG='C', LC_ALL='C')
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW | 0x4} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(argv, cwd=directory, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **kwargs)
    job = None; readers = []
    outcome = 'complete'
    try:
        job = _CompilerJob(process.pid)
        readers = [_BoundedReader(process.stdout), _BoundedReader(process.stderr)]
        _resume_owned_process(process.pid)
        deadline = time.monotonic() + timeout_s
        while process.poll() is None:
            if cancelled():
                outcome = 'cancelled'; break
            if time.monotonic() >= deadline:
                outcome = 'timeout'; break
            time.sleep(.02)
        if outcome != 'complete':
            _stop_owned_process(process, job)
        else:
            process.wait(timeout=5)
    finally:
        # Closing the job also removes a compiler child left after its parent.
        if job is not None:
            job.close()
        if process.poll() is None:
            _stop_owned_process(process, job)
        for reader in readers:
            reader.thread.join(timeout=2)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    text = '\n'.join(bytes(reader.data).decode('utf-8', errors='replace') for reader in readers)
    if any(reader.truncated for reader in readers):
        text += '\n[Compiler diagnostic output truncated.]'
    return outcome, process.returncode, text


def check_firmware_bundle(bundle: FirmwareBundle | dict, *, workspace=None, compiler_path=None,
                          cancelled=lambda: False, timeout_s=30) -> FirmwareBuildReport:
    started = time.monotonic()
    bundle = FirmwareBundle.model_validate(bundle.model_dump() if isinstance(bundle, FirmwareBundle) else bundle)
    if not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 120:
        raise ValueError('The explicit syntax check requires a timeout between 0 and 120 seconds.')
    report = FirmwareBuildReport(status='pending', bundle_id=bundle.id,
        source_sha256={file.path: file.sha256 for file in bundle_source_files(bundle)})
    def finish(status):
        report.status = status; report.elapsed_s = time.monotonic() - started
        return report
    if cancelled():
        return finish('cancelled')
    if workspace is not None:
        binding = verify_bundle_binding(bundle, workspace)
        if binding.status != 'current':
            report.diagnostics += [FirmwareBuildDiagnostic(severity='error', code=issue.code, message=issue.message) for issue in binding.issues]
            return finish('failed')
        report.checks.append(FirmwareBuildCheck(name='board_wiring_binding', status='passed', message='The exact board and saved wiring match the candidate snapshot.'))
    else:
        report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='binding_not_checked', message='No current CAD workspace was provided; source identity is checked but current wiring is unverified.'))
    for library in bundle.libraries:
        report.checks.append(FirmwareBuildCheck(name='library:' + library.id,
            status='pending' if library.origin == 'external' else 'passed',
            message=f'{library.name}@{library.version}: ' + ('external requirement recorded; not installed or linked.'
                if library.origin == 'external' else f'{len(library.files)} source/data files match snapshot SHA-256 {library.source_sha256}. Version is user declared; target linkage is unverified.')))
        if library.origin == 'external':
            report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='external_dependency_unverified',
                message=f'{library.name}@{library.version}: installation, API and target linkage are unverified.'))
        if library.omitted_files:
            report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='library_files_omitted',
                message=f'{library.name}: {len(library.omitted_files)} unsupported/binary files were omitted. Review the dependency manifest before target integration.'))
    python_files = [file for file in bundle_source_files(bundle) if file.role == 'source' and PurePosixPath(file.path).suffix.lower() == '.py']
    for file in python_files:
        if cancelled():
            return finish('cancelled')
        try:
            source = file.content[1:] if file.content.startswith('\ufeff') else file.content
            tree = ast.parse(source, filename=file.path)
            compile(tree, file.path, 'exec', dont_inherit=True)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            report.diagnostics.append(FirmwareBuildDiagnostic(severity='error', code='python_syntax',
                message=str(getattr(exc, 'msg', exc)), path=file.path,
                line=getattr(exc, 'lineno', None), column=getattr(exc, 'offset', None)))
            return finish('failed')
        report.checks.append(FirmwareBuildCheck(name=file.path, status='passed', message='Python AST and compile check passed without importing or executing the source.'))
        report.diagnostics.extend(_python_import_diagnostics(file, tree, bundle))
    c_files = [file for file in bundle_source_files(bundle) if file.role == 'source' and PurePosixPath(file.path).suffix.lower() in {'.c', '.cpp', '.ino'}]
    if c_files:
        preflight = _preflight_c(bundle)
        report.diagnostics.extend(preflight)
        if any(issue.severity == 'error' for issue in preflight):
            return finish('failed')
        try:
            compiler = _compiler(compiler_path)
        except ValueError as exc:
            report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='unsupported_toolchain', message=str(exc)))
            return finish('pending')
        if compiler is None:
            report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='toolchain_missing', message='No installed compiler was explicitly selected. Install/configure the actual board toolchain and SDK separately; no compiler or SDK is downloaded.'))
            return finish('pending')
        report.compiler_path = str(compiler)
        if any(issue.severity == 'pending' for issue in preflight):
            return finish('pending')
        try:
            with tempfile.TemporaryDirectory(prefix='cad-firmware-check-') as folder:
                directory = Path(folder)
                for file in bundle_source_files(bundle):
                    if cancelled():
                        return finish('cancelled')
                    path = directory.joinpath(*PurePosixPath(file.path).parts)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(file.content.encode('utf-8'))
                for file in c_files:
                    if cancelled():
                        return finish('cancelled')
                    language = 'c' if PurePosixPath(file.path).suffix.lower() == '.c' else 'c++'
                    standard = '-std=c11' if language == 'c' else '-std=c++17'
                    argv = [str(compiler), '-fsyntax-only', '-fdiagnostics-color=never', '-x', language,
                            standard, '-I', str(directory)]
                    for path in library_search_paths(bundle):
                        argv += ['-I', str(directory.joinpath(*PurePosixPath(path).parts))]
                    argv.append(str(directory.joinpath(*PurePosixPath(file.path).parts)))
                    outcome, returncode, output = _run_compiler(argv, directory, compiler, cancelled,
                        max(.01, timeout_s - (time.monotonic() - started)))
                    output = output.replace(str(directory), '<bundle>')
                    if outcome == 'cancelled':
                        return finish('cancelled')
                    if outcome == 'timeout':
                        report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='compiler_timeout', path=file.path, message='The bounded compiler check timed out. No target build or hardware execution completed.'))
                        return finish('pending')
                    if output.strip():
                        report.diagnostics.append(FirmwareBuildDiagnostic(severity='error' if returncode else 'warning', code='compiler_diagnostic', path=file.path, message=output[:MAX_DIAGNOSTIC_BYTES]))
                    if returncode:
                        if not output.strip():
                            report.diagnostics.append(FirmwareBuildDiagnostic(severity='error', code='compiler_failed', path=file.path, message='Compiler parsing did not complete successfully.'))
                        return finish('failed')
                    report.checks.append(FirmwareBuildCheck(name=file.path, status='passed', message='C/C++ syntax parsed with fixed arguments; no linking, target object build or execution.'))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='compiler_unavailable', message=str(exc)))
            return finish('pending')
        report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='target_build_not_done', message='Syntax parsed only. Board SDK, clock/startup, linker map, peripheral configuration, FOC/core integration and target build remain unverified.'))
    for value in bundle.missing_parameters:
        report.diagnostics.append(FirmwareBuildDiagnostic(severity='pending', code='missing_parameter', message=value))
    report.diagnostics.append(FirmwareBuildDiagnostic(severity='info', code='execution_not_attempted', message='Generated source was not imported, executed, linked or flashed. Installed Python modules and hardware behavior are not validated by syntax checks.'))
    return finish('pending' if any(item.severity == 'pending' for item in report.diagnostics) else 'syntax_ok')
