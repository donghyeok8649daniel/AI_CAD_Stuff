"""Process-scoped Windows identity; never registry, shortcut or live UI edits."""
import ast
import ctypes
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cadstudio import windows_identity


class Setter:
    def __init__(self, result=0):
        self.result = result
        self.calls = []

    def __call__(self, value):
        self.calls.append(value)
        return self.result


def mock_shell(monkeypatch, result=0):
    setter = Setter(result)
    loads = []

    class Shell:
        SetCurrentProcessExplicitAppUserModelID = setter

    def load(name, **options):
        loads.append((name, options))
        return Shell()

    monkeypatch.setattr(windows_identity.sys, 'platform', 'win32')
    monkeypatch.setattr(windows_identity.ctypes, 'WinDLL', load, raising=False)
    return setter, loads


def test_module_import_never_calls_windows_or_creates_ui(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Import must not change a process identity.')
    monkeypatch.setattr(windows_identity.ctypes, 'WinDLL', forbidden, raising=False)
    importlib.reload(windows_identity)
    assert windows_identity.APP_USER_MODEL_ID == 'PromptCADStudio.Native'


def test_non_windows_is_a_noop_without_loading_shell(monkeypatch):
    monkeypatch.setattr(windows_identity.sys, 'platform', 'linux')
    def forbidden(*args, **kwargs):
        raise AssertionError('No Windows DLL load on another platform.')
    monkeypatch.setattr(windows_identity.ctypes, 'WinDLL', forbidden, raising=False)
    assert windows_identity.set_windows_app_identity() is False


def test_windows_uses_unicode_stable_identity_and_typed_hresult(monkeypatch):
    setter, loads = mock_shell(monkeypatch)
    assert windows_identity.set_windows_app_identity() is True
    assert loads == [('shell32', {'use_last_error': True})]
    assert setter.calls == ['PromptCADStudio.Native']
    assert setter.argtypes == [ctypes.c_wchar_p]
    assert setter.restype is ctypes.c_long


@pytest.mark.parametrize('result', [-2147024891, 2147942405, 1])
def test_nonzero_hresult_is_not_reported_as_success(monkeypatch, result):
    setter, _ = mock_shell(monkeypatch, result)
    with pytest.raises(OSError, match=f'0x{result & 0xffffffff:08X}') as raised:
        windows_identity.set_windows_app_identity()
    assert raised.value.hresult == result & 0xffffffff
    assert setter.calls == ['PromptCADStudio.Native']


def test_shell_load_failure_is_surfaced_without_fallback(monkeypatch):
    monkeypatch.setattr(windows_identity.sys, 'platform', 'win32')
    def unavailable(*args, **kwargs):
        raise OSError('Owned simulated shell DLL load failure')
    monkeypatch.setattr(windows_identity.ctypes, 'WinDLL', unavailable, raising=False)
    with pytest.raises(OSError, match='simulated shell DLL load failure'):
        windows_identity.set_windows_app_identity()


def test_native_startup_sets_identity_before_argument_dispatch_or_any_qapplication():
    # Inspect the product entry point; importing it must not start the real UI.
    entry = Path(__file__).resolve().parents[1] / 'native_desktop.py'
    tree = ast.parse(entry.read_text(encoding='utf-8'))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    direct_calls = [(index, node.value) for index, node in enumerate(main.body)
                    if isinstance(node, (ast.Expr, ast.Assign, ast.AnnAssign))
                    and isinstance(node.value, ast.Call)]
    identity = [(index, call) for index, call in direct_calls
                if isinstance(call.func, ast.Name) and call.func.id == 'set_windows_app_identity']
    assert len(identity) == 1, 'Call identity once, unconditionally during initial native startup.'
    index, identity_call = identity[0]
    assert not identity_call.args and not identity_call.keywords
    dispatch = next(index for index, node in enumerate(main.body)
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name) and node.value.func.id == 'parse_startup_args')
    assert index < dispatch
    later_qt_calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == 'QApplication']
    assert later_qt_calls and all(identity_call.lineno < call.lineno for call in later_qt_calls)


def current_identity():
    """Read this test process only and release the allocated PWSTR correctly."""
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    getter = shell.GetCurrentProcessExplicitAppUserModelID
    getter.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
    getter.restype = ctypes.c_long
    free = ctypes.WinDLL('ole32').CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    value = ctypes.c_wchar_p()
    result = getter(ctypes.byref(value))
    try:
        return result, value.value if result == 0 else None
    finally:
        if value:
            free(ctypes.cast(value, ctypes.c_void_p))


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Shell32 identity is Windows-only.')
def test_real_windows_set_and_get_are_confined_to_new_owned_child_process(record_property):
    before = current_identity()
    source = Path(windows_identity.__file__).resolve().parents[1]
    code = r'''
import ctypes, hashlib, json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules)
from cadstudio.windows_identity import APP_USER_MODEL_ID, set_windows_app_identity
assert set_windows_app_identity() is True
shell = ctypes.WinDLL('shell32', use_last_error=True)
getter = shell.GetCurrentProcessExplicitAppUserModelID
getter.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
getter.restype = ctypes.c_long
free = ctypes.WinDLL('ole32').CoTaskMemFree
free.argtypes = [ctypes.c_void_p]
free.restype = None
value = ctypes.c_wchar_p()
result = getter(ctypes.byref(value))
try:
    assert result == 0 and value.value == APP_USER_MODEL_ID
    assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules)
    print(json.dumps(dict(pid=os.getpid(), identity=value.value, setter_succeeded=True,
        getter_hresult=result, source_sha256=hashlib.sha256((pathlib.Path(sys.argv[1])/'cadstudio/windows_identity.py').read_bytes()).hexdigest())))
finally:
    if value: free(ctypes.cast(value, ctypes.c_void_p))
'''
    process = subprocess.run([sys.executable, '-B', '-c', code, str(source)],
        capture_output=True, text=True, encoding='utf-8', timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result['pid'] != os.getpid() and result['identity'] == 'PromptCADStudio.Native'
    assert result['setter_succeeded'] and result['getter_hresult'] == 0
    assert current_identity() == before
    record_property('owned_child_identity_result', json.dumps(result, sort_keys=True))
    record_property('parent_identity_unchanged', True)
