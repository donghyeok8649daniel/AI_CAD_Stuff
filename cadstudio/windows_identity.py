"""Stable Windows taskbar identity for this process, without global changes.

Call explicitly in native startup before creating any application UI. Importing
this module does not set an identity, register file types or change shortcuts.
"""
from __future__ import annotations

import ctypes
import sys


APP_USER_MODEL_ID = 'PromptCADStudio.Native'


def set_windows_app_identity() -> bool:
    """Set the current Windows process identity; return False on other systems.

    The API documents S_OK (zero) as its success result. A failed DLL load or
    any other HRESULT is surfaced to the startup caller rather than reporting
    an identity that was not applied. No QApplication or Windows UI is created.
    """
    if sys.platform != 'win32':
        return False
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    setter = shell.SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_long  # HRESULT is a signed 32-bit LONG on Windows.
    result = setter(APP_USER_MODEL_ID)
    if result != 0:
        code = result & 0xffffffff
        error = OSError(f'SetCurrentProcessExplicitAppUserModelID failed: HRESULT 0x{code:08X}')
        error.hresult = code
        raise error
    return True
